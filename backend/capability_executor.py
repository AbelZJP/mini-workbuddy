from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import shutil
import ssl
import subprocess
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .model_router import model_config, route_model


class CapabilityExecutionError(RuntimeError):
    pass


def _safe_output_path(workspace_root: str, output_filename: str) -> tuple[Path, str]:
    root = Path(workspace_root).expanduser().resolve()
    filename = Path(output_filename or "").name
    if not filename or filename in {".", ".."}:
        filename = f"generated-image-{uuid.uuid4().hex[:10]}.png"
    if Path(output_filename or filename).name != output_filename and output_filename:
        raise CapabilityExecutionError("图片输出文件名只能是当前工作空间内的文件名")
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        filename += ".png"
    target = (root / "outputs" / filename).resolve()
    if not target.is_relative_to(root):
        raise CapabilityExecutionError("图片输出路径超出当前工作空间，已拒绝写入")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, target.relative_to(root).as_posix()


def _is_ark_seedream_i2i(model: dict[str, Any]) -> bool:
    config = model_config(model)
    adapter = str(config.get("image_adapter") or "").lower()
    identity = " ".join(str(model.get(key) or "") for key in ("model", "name", "provider")).lower()
    return adapter == "ark_seedream_i2i" or "seedream" in identity


def _seedream_reference_data_url(workspace_root: str, relative_path: str) -> str:
    root = Path(workspace_root).expanduser().resolve()
    source = Path(relative_path or "")
    if source.is_absolute():
        raise CapabilityExecutionError("Seedream 参考图必须来自当前工作空间内的图片节点")
    target = (root / source).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise CapabilityExecutionError("未找到可作为 Seedream 参考图的图片文件")
    media_type = mimetypes.guess_type(target.name)[0] or ""
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise CapabilityExecutionError("Seedream 参考图仅支持 JPEG、PNG 或 WebP 图片")
    if target.stat().st_size > 20 * 1024 * 1024:
        raise CapabilityExecutionError("Seedream 参考图不能超过 20MB")
    encoded = base64.b64encode(target.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _request_image(
    model: dict[str, Any],
    prompt: str,
    size: str,
    reference_images: list[str] | None = None,
) -> bytes:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise CapabilityExecutionError(
            f"图片模型“{model.get('name', model.get('model', '当前模型'))}”未读取到 API Key。"
        )
    config = model_config(model)
    base_url = str(
        model.get("base_url") or config.get("base_url") or "https://api.openai.com/v1"
    )
    endpoint = base_url.rstrip("/") + "/images/generations"
    payload = {
        "model": model.get("model"),
        "prompt": prompt,
        "size": size or str(config.get("image_size") or "1024x1024"),
    }
    if reference_images:
        if not _is_ark_seedream_i2i(model):
            raise CapabilityExecutionError(
                f"图片模型“{model.get('name', model.get('model', '当前模型'))}”未配置参考图生图能力。"
            )
        payload["image"] = reference_images
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(
            f"图片模型请求失败（HTTP {exc.code}）：{detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(f"图片模型请求失败：{exc}") from exc
    items = body.get("data") if isinstance(body, dict) else None
    first = items[0] if isinstance(items, list) and items else {}
    if first.get("b64_json"):
        try:
            return base64.b64decode(first["b64_json"])
        except (ValueError, TypeError) as exc:
            raise CapabilityExecutionError(
                "图片模型返回了无效的 Base64 图片数据"
            ) from exc
    if first.get("url"):
        try:
            with urllib.request.urlopen(str(first["url"]), timeout=180) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CapabilityExecutionError(f"下载图片模型结果失败：{exc}") from exc
    raise CapabilityExecutionError("图片模型没有返回可保存的图片数据")


async def generate_image(
    store: Any,
    workspace_root: str,
    prompt: str,
    size: str = "1024x1024",
    output_filename: str = "",
    preferred_model_id: str = "",
    reference_image_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Execute the stable image.generate capability through the routed model."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "retryable": False, "message": "图片描述不能为空"}
    model = route_model(store, "image.generate", preferred_model_id)
    if not model:
        return {
            "ok": False,
            "retryable": False,
            "message": "没有配置图片生成模型。请在设置中添加并勾选“支持图片生成”。",
        }
    target, relative_path = _safe_output_path(workspace_root, output_filename)
    try:
        references = [
            _seedream_reference_data_url(workspace_root, path)
            for path in (reference_image_paths or [])
            if path
        ]
        image_bytes = await asyncio.to_thread(_request_image, model, prompt, size, references)
        target.write_bytes(image_bytes)
    except (OSError, CapabilityExecutionError) as exc:
        return {"ok": False, "retryable": False, "message": str(exc)}
    return {
        "ok": True,
        "retryable": False,
        "message": "图片已生成",
        "artifact_path": relative_path,
        "artifact_type": "image",
        "artifact_operation": "created",
        "model_id": model["id"],
    }


def _safe_video_output_path(workspace_root: str, output_filename: str) -> tuple[Path, str]:
    root = Path(workspace_root).expanduser().resolve()
    filename = Path(output_filename or "").name
    if not filename or filename in {".", ".."}:
        filename = f"generated-video-{uuid.uuid4().hex[:10]}.mp4"
    if Path(output_filename or filename).name != output_filename and output_filename:
        raise CapabilityExecutionError("视频输出文件名只能是当前工作空间内的文件名")
    if Path(filename).suffix.lower() not in {".mp4", ".webm", ".mov"}:
        filename += ".mp4"
    target = (root / "outputs" / filename).resolve()
    if not target.is_relative_to(root):
        raise CapabilityExecutionError("视频输出路径超出当前工作空间，已拒绝写入")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, target.relative_to(root).as_posix()


def _safe_audio_output_path(workspace_root: str, output_filename: str) -> tuple[Path, str]:
    root = Path(workspace_root).expanduser().resolve()
    filename = Path(output_filename or "").name
    if not filename or filename in {".", ".."}:
        filename = f"generated-voice-{uuid.uuid4().hex[:10]}.mp3"
    if Path(output_filename or filename).name != output_filename and output_filename:
        raise CapabilityExecutionError("语音输出文件名只能是当前工作空间内的文件名")
    if Path(filename).suffix.lower() not in {".mp3", ".wav", ".m4a"}:
        filename += ".mp3"
    target = (root / "outputs" / filename).resolve()
    if not target.is_relative_to(root):
        raise CapabilityExecutionError("语音输出路径超出当前工作空间，已拒绝写入")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, target.relative_to(root).as_posix()


def _voice_clone_reference_path(workspace_root: str, relative_path: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    source = Path(relative_path or "")
    if source.is_absolute():
        raise CapabilityExecutionError("声音克隆参考音频必须来自当前工作空间")
    target = (root / source).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise CapabilityExecutionError("未找到可用于声音克隆的参考音频")
    if target.suffix.lower() not in {".mp3", ".m4a", ".wav"}:
        raise CapabilityExecutionError("声音克隆参考音频仅支持 MP3、M4A 或 WAV")
    if target.stat().st_size > 20 * 1024 * 1024:
        raise CapabilityExecutionError("声音克隆参考音频不能超过 20MB")
    return target


def _minimax_base_url(model: dict[str, Any]) -> str:
    config = model_config(model)
    base_url = str(model.get("base_url") or config.get("base_url") or "https://api.minimax.io/v1").rstrip("/")
    return base_url if base_url.endswith("/v1") else base_url + "/v1"


def _minimax_ssl_context() -> ssl.SSLContext:
    """MiniMax 中国站在部分网络环境下需固定使用 TLS 1.2。"""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


def _minimax_response_error(body: dict[str, Any]) -> str:
    base_resp = body.get("base_resp") if isinstance(body, dict) else {}
    if not isinstance(base_resp, dict):
        return "MiniMax 返回格式无效"
    if int(base_resp.get("status_code") or 0) == 0:
        return ""
    return str(base_resp.get("status_msg") or "MiniMax 请求失败")


def _multipart_upload_body(source: Path) -> tuple[str, bytes]:
    boundary = f"----MiniWorkBuddy{uuid.uuid4().hex}"
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nvoice_clone\r\n".encode(),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{source.name}\"\r\n"
            f"Content-Type: {media_type}\r\n\r\n"
        ).encode(),
        source.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return boundary, b"".join(chunks)


def _request_voice_clone(model: dict[str, Any], reference: Path, text: str) -> bytes:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise CapabilityExecutionError(
            f"MiniMax 语音模型“{model.get('name', model.get('model', '当前模型'))}”未读取到 API Key。"
        )
    base_url = _minimax_base_url(model)
    boundary, upload_body = _multipart_upload_body(reference)
    upload_request = urllib.request.Request(
        base_url + "/files/upload",
        data=upload_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    tls_context = _minimax_ssl_context()
    try:
        with urllib.request.urlopen(upload_request, timeout=180, context=tls_context) as response:
            upload_result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"MiniMax 参考音频上传失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(f"MiniMax 参考音频上传失败：{exc}") from exc
    error = _minimax_response_error(upload_result)
    file_id = (upload_result.get("file") or {}).get("file_id") if isinstance(upload_result, dict) else None
    if error or file_id is None:
        raise CapabilityExecutionError(f"MiniMax 参考音频上传失败：{error or '没有返回 file_id'}")

    clone_payload = {
        "file_id": file_id,
        "voice_id": f"workbuddy-{uuid.uuid4().hex}",
        "text": text,
        "model": model.get("model"),
    }
    clone_request = urllib.request.Request(
        base_url + "/voice_clone",
        data=json.dumps(clone_payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(clone_request, timeout=300, context=tls_context) as response:
            clone_result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"MiniMax 声音克隆失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(f"MiniMax 声音克隆失败：{exc}") from exc
    error = _minimax_response_error(clone_result)
    audio_url = str(clone_result.get("demo_audio") or "") if isinstance(clone_result, dict) else ""
    if error or not audio_url:
        raise CapabilityExecutionError(f"MiniMax 声音克隆失败：{error or '没有返回试听音频'}")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(audio_url), timeout=300, context=tls_context
        ) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise CapabilityExecutionError(f"下载 MiniMax 试听音频失败：{exc}") from exc


async def generate_voice_clone(
    store: Any,
    workspace_root: str,
    reference_audio_path: str,
    text: str,
    output_filename: str = "",
    preferred_model_id: str = "",
) -> dict[str, Any]:
    """Clone a workspace audio reference with MiniMax and persist its demo audio locally."""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "retryable": False, "message": "生成语音文案不能为空"}
    model = route_model(store, "voice.clone", preferred_model_id)
    if not model:
        return {
            "ok": False,
            "retryable": False,
            "message": "没有配置声音克隆模型。请在设置中添加 MiniMax 模型并勾选“支持声音克隆”。",
        }
    try:
        reference = _voice_clone_reference_path(workspace_root, reference_audio_path)
        target, relative_path = _safe_audio_output_path(workspace_root, output_filename)
        audio_bytes = await asyncio.to_thread(_request_voice_clone, model, reference, text)
        target.write_bytes(audio_bytes)
    except (OSError, CapabilityExecutionError) as exc:
        return {"ok": False, "retryable": False, "message": str(exc)}
    return {
        "ok": True,
        "retryable": False,
        "message": "声音克隆完成",
        "artifact_path": relative_path,
        "artifact_type": "audio",
        "artifact_operation": "created",
        "model_id": model["id"],
    }


def _video_size(ratio: str, resolution: str) -> str:
    quality = str(resolution or "1080p").lower()
    if quality == "4k":
        dimensions = {"16:9": "3840x2160", "9:16": "2160x3840", "1:1": "2160x2160"}
    elif quality == "720p":
        dimensions = {"16:9": "1280x720", "9:16": "720x1280", "1:1": "720x720"}
    else:
        dimensions = {"16:9": "1920x1080", "9:16": "1080x1920", "1:1": "1080x1080"}
    return dimensions.get(ratio, dimensions["16:9"])


def _video_item(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    data = body.get("data")
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return body


def _video_result_url(item: dict[str, Any]) -> str:
    for key in ("url", "video_url", "content_url", "download_url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    output = item.get("output")
    if isinstance(output, dict):
        return _video_result_url(output)
    video = item.get("video")
    if isinstance(video, dict):
        return _video_result_url(video)
    return ""


def _video_task_id(body: Any) -> str:
    """Read task IDs from both generic and DashScope-style responses."""
    if not isinstance(body, dict):
        return ""
    for key in ("id", "task_id", "job_id"):
        value = body.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    for key in ("output", "data", "result"):
        value = body.get(key)
        if isinstance(value, list):
            for item in value:
                task_id = _video_task_id(item)
                if task_id:
                    return task_id
        else:
            task_id = _video_task_id(value)
            if task_id:
                return task_id
    return ""


def _video_status(body: Any) -> str:
    """Read task states such as DashScope's output.task_status."""
    if not isinstance(body, dict):
        return ""
    for key in ("status", "state", "task_status"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value.lower()
    for key in ("output", "data", "result"):
        value = body.get(key)
        if isinstance(value, (dict, list)):
            status = _video_status(value)
            if status:
                return status
    return ""


def _video_endpoint(value: Any, fallback: str, base_url: str) -> str:
    endpoint = str(value or fallback)
    return base_url.rstrip("/") + endpoint if endpoint.startswith("/") else endpoint


def _video_task_url(endpoint: str, task_id: str) -> str:
    """Support both names commonly used in saved model configurations."""
    encoded_id = urllib.parse.quote(task_id, safe="")
    return endpoint.replace("{task_id}", encoded_id).replace("{id}", encoded_id)


def _download_video(url: str, headers: dict[str, str]) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise CapabilityExecutionError(f"下载视频模型结果失败：{exc}") from exc


def _is_wanxiang_i2v(model: dict[str, Any]) -> bool:
    config = model_config(model)
    adapter = str(config.get("video_adapter") or "").lower()
    identity = " ".join(str(model.get(key) or "") for key in ("model", "name", "provider")).lower()
    return adapter == "wanxiang_i2v" or "wan2.7-i2v" in identity


def _is_wanxiang_r2v(model: dict[str, Any]) -> bool:
    config = model_config(model)
    adapter = str(config.get("video_adapter") or "").lower()
    identity = " ".join(str(model.get(key) or "") for key in ("model", "name", "provider")).lower()
    return adapter == "wanxiang_r2v" or "wan2.7-r2v" in identity


def _r2v_reference_file(workspace_root: str, relative_path: str, media_kind: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    source = Path(relative_path or "")
    if source.is_absolute():
        raise CapabilityExecutionError("万相参考素材必须来自当前工作空间")
    target = (root / source).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise CapabilityExecutionError("未找到可用于万相参考生视频的素材文件")
    suffix = target.suffix.lower()
    if media_kind == "reference_image":
        if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            raise CapabilityExecutionError("万相参考图仅支持 JPG、JPEG、PNG、BMP 或 WebP")
        if target.stat().st_size > 20 * 1024 * 1024:
            raise CapabilityExecutionError("万相参考图不能超过 20MB")
    elif media_kind == "reference_video":
        if suffix not in {".mp4", ".mov"}:
            raise CapabilityExecutionError("万相参考视频仅支持 MP4 或 MOV")
        if target.stat().st_size > 100 * 1024 * 1024:
            raise CapabilityExecutionError("万相参考视频不能超过 100MB")
    else:
        raise CapabilityExecutionError("万相参考素材类型无效")
    _validate_r2v_media_metadata(target, media_kind)
    return target


def _validate_r2v_media_metadata(file_path: Path, media_kind: str) -> None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CapabilityExecutionError("未安装 ffprobe，无法校验万相参考素材")
    command = [
        ffprobe,
        "-v", "error",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json",
        str(file_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        body = json.loads(result.stdout)
        stream = next(item for item in body.get("streams", []) if item.get("width") and item.get("height"))
        width, height = int(stream["width"]), int(stream["height"])
    except (StopIteration, TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise CapabilityExecutionError("无法读取万相参考素材的尺寸信息") from exc
    if result.returncode != 0 or not width or not height:
        raise CapabilityExecutionError("无法读取万相参考素材的尺寸信息")
    longest, shortest = max(width, height), min(width, height)
    if shortest == 0 or longest / shortest > 8:
        raise CapabilityExecutionError("万相参考素材宽高比必须在 1:8 至 8:1 之间")
    maximum = 8000 if media_kind == "reference_image" else 4096
    if not 240 <= width <= maximum or not 240 <= height <= maximum:
        raise CapabilityExecutionError(f"万相参考{'图' if media_kind == 'reference_image' else '视频'}边长必须在 240 至 {maximum} 像素之间")
    if media_kind == "reference_video":
        try:
            duration = float(body.get("format", {}).get("duration"))
        except (TypeError, ValueError) as exc:
            raise CapabilityExecutionError("无法读取万相参考视频时长") from exc
        if not 1 <= duration <= 30:
            raise CapabilityExecutionError("万相参考视频时长必须在 1 至 30 秒之间")


def _multipart_form(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"----workbuddy-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
        f"Content-Type: {media_type}\r\n\r\n".encode(),
        file_path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _upload_dashscope_temporary_file(model: dict[str, Any], file_path: Path) -> str:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise CapabilityExecutionError(f"万相模型“{model.get('name', model.get('model', '当前模型'))}”未读取到 API Key。")
    model_name = str(model.get("model") or "").strip()
    if not model_name:
        raise CapabilityExecutionError("万相模型没有配置模型名称")
    policy_url = "https://dashscope.aliyuncs.com/api/v1/uploads?action=getPolicy&model=" + urllib.parse.quote(model_name, safe="")
    policy_request = urllib.request.Request(
        policy_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(policy_request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
        policy = body.get("data") if isinstance(body, dict) else None
        if not isinstance(policy, dict):
            raise ValueError("响应缺少 data")
        required = ("upload_host", "upload_dir", "oss_access_key_id", "policy", "signature", "x_oss_object_acl", "x_oss_forbid_overwrite")
        if any(not policy.get(key) for key in required):
            raise ValueError("响应缺少上传凭证")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"获取万相临时上传凭证失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CapabilityExecutionError(f"获取万相临时上传凭证失败：{exc}") from exc
    key = f"{str(policy['upload_dir']).rstrip('/')}/{uuid.uuid4().hex}{file_path.suffix.lower()}"
    body, content_type = _multipart_form({
        "OSSAccessKeyId": str(policy["oss_access_key_id"]),
        "policy": str(policy["policy"]),
        "Signature": str(policy["signature"]),
        "key": key,
        "x-oss-object-acl": str(policy["x_oss_object_acl"]),
        "x-oss-forbid-overwrite": str(policy["x_oss_forbid_overwrite"]),
        "success_action_status": "200",
    }, file_path)
    upload_request = urllib.request.Request(str(policy["upload_host"]), data=body, headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(upload_request, timeout=300):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"上传万相参考素材失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CapabilityExecutionError(f"上传万相参考素材失败：{exc}") from exc
    return f"oss://{key}"


def _wanxiang_r2v_media(model: dict[str, Any], workspace_root: str, image_paths: list[str], video_paths: list[str]) -> list[dict[str, str]]:
    if not image_paths or not video_paths:
        raise CapabilityExecutionError("万相参考生视频需要直连至少一张人物图片和一段参考视频")
    if len(image_paths) + len(video_paths) > 5:
        raise CapabilityExecutionError("万相参考图和参考视频合计不能超过 5 份")
    image_files = [_r2v_reference_file(workspace_root, path, "reference_image") for path in image_paths]
    video_files = [_r2v_reference_file(workspace_root, path, "reference_video") for path in video_paths]
    media: list[dict[str, str]] = []
    for file_path in image_files:
        media.append({"type": "reference_image", "url": _upload_dashscope_temporary_file(model, file_path)})
    for file_path in video_files:
        media.append({"type": "reference_video", "url": _upload_dashscope_temporary_file(model, file_path)})
    return media


def _r2v_prompt(prompt: str, image_count: int, video_count: int) -> str:
    image_labels = "、".join(f"图{index}" for index in range(1, image_count + 1))
    video_labels = "、".join(f"视频{index}" for index in range(1, video_count + 1))
    return f"{prompt}\n\n参考素材：{image_labels}为人物/形象参考；{video_labels}为动作、节奏和场景参考。"


def _r2v_character_replacement_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "人物替换硬约束：图1中的人物是视频全程唯一人物，必须保持她的脸、发型、体型和服饰；"
        "首帧必须出现图1中的人物。视频1仅用作动作、肢体节奏、运镜、场景和光照参考，"
        "禁止使用视频1中人物的脸、发型、服饰和体型。"
    )


def _r2v_character_replacement_media(media: list[dict[str, str]]) -> list[dict[str, str]]:
    first_image = next((item for item in media if item.get("type") == "reference_image" and item.get("url")), None)
    if not first_image:
        raise CapabilityExecutionError("万相参考生视频需要至少一张人物图片和一段参考视频")
    return [{"type": "first_frame", "url": str(first_image["url"])}] + media


def _r2v_duration_seconds(duration: str) -> int:
    try:
        seconds = int(str(duration or "5s").lower().replace("s", ""))
    except ValueError as exc:
        raise CapabilityExecutionError("万相参考生视频时长必须是 2 至 10 秒") from exc
    if not 2 <= seconds <= 10:
        raise CapabilityExecutionError("万相参考生视频在包含参考视频时仅支持 2 至 10 秒")
    return seconds


def _wanxiang_first_frame_data_url(workspace_root: str, relative_path: str) -> str:
    root = Path(workspace_root).expanduser().resolve()
    source = Path(relative_path or "")
    if source.is_absolute():
        raise CapabilityExecutionError("万相首帧必须来自当前工作空间内的图片产物")
    target = (root / source).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise CapabilityExecutionError("未找到可作为万相首帧的 AI 图片产物")
    media_type = mimetypes.guess_type(target.name)[0] or ""
    if media_type not in {"image/jpeg", "image/png", "image/bmp", "image/webp"}:
        raise CapabilityExecutionError("万相首帧仅支持 JPEG、PNG、BMP 或 WebP 图片")
    if target.stat().st_size > 20 * 1024 * 1024:
        raise CapabilityExecutionError("万相首帧图片不能超过 20MB")
    encoded = base64.b64encode(target.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _request_wanxiang_i2v(
    model: dict[str, Any],
    prompt: str,
    duration: str,
    resolution: str,
    first_frame_data_url: str,
) -> bytes:
    """Run Wan 2.7 image-to-video through its dedicated media-array protocol."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise CapabilityExecutionError(
            f"万相模型“{model.get('name', model.get('model', '当前模型'))}”未读取到 API Key。"
        )
    config = model_config(model)
    base_url = str(model.get("base_url") or config.get("base_url") or "https://dashscope.aliyuncs.com").rstrip("/")
    api_base = base_url if base_url.endswith("/api/v1") else base_url + "/api/v1"
    endpoint = str(config.get("video_endpoint") or "") or api_base + "/services/aigc/video-generation/video-synthesis"
    try:
        seconds = min(15, max(2, int(str(duration or "5s").lower().replace("s", ""))))
    except ValueError:
        seconds = 5
    payload = {
        "model": model.get("model"),
        "input": {
            "prompt": prompt,
            "media": [{"type": "first_frame", "url": first_frame_data_url}],
        },
        "parameters": {
            "resolution": "720P" if str(resolution or "").lower() == "720p" else "1080P",
            "duration": seconds,
            "prompt_extend": bool(config.get("wanxiang_prompt_extend", True)),
            "watermark": bool(config.get("wanxiang_watermark", False)),
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"万相视频请求失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(f"万相视频请求失败：{exc}") from exc
    job_id = _video_task_id(body)
    if not job_id:
        raise CapabilityExecutionError("万相没有返回视频任务 ID")
    status_endpoint = _video_endpoint(
        config.get("video_status_endpoint"),
        api_base + "/tasks/{id}",
        base_url,
    )
    content_endpoint = _video_endpoint(
        config.get("video_content_endpoint"),
        endpoint.rstrip("/") + "/{id}/content",
        base_url,
    )
    timeout_seconds = min(max(int(config.get("video_timeout_seconds") or 1800), 60), 3600)
    poll_seconds = min(max(float(config.get("video_poll_interval_seconds") or 3), 1), 15)
    deadline = time.monotonic() + timeout_seconds
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    while time.monotonic() < deadline:
        poll_url = _video_task_url(status_endpoint, job_id)
        try:
            with urllib.request.urlopen(urllib.request.Request(poll_url, headers=poll_headers), timeout=60) as response:
                poll_body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            raise CapabilityExecutionError(f"查询万相视频任务失败（HTTP {exc.code}）：{detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CapabilityExecutionError(f"查询万相视频任务失败：{exc}") from exc
        item = _video_item(poll_body)
        status = _video_status(poll_body)
        if status in {"failed", "error", "cancelled", "canceled"}:
            output = item.get("output") if isinstance(item.get("output"), dict) else {}
            raise CapabilityExecutionError(str(item.get("message") or item.get("error") or output.get("message") or "万相视频生成失败"))
        result_url = _video_result_url(item)
        if result_url:
            # 万相返回的是临时授权的产物 URL，应直接访问；携带模型 API 的
            # Bearer 令牌可能会被 OSS/CDN 拒绝为 403。
            return _download_video(result_url, {})
        if status in {"completed", "complete", "succeeded", "success", "done"}:
            if config.get("video_content_endpoint"):
                return _download_video(_video_task_url(content_endpoint, job_id), poll_headers)
            raise CapabilityExecutionError("万相任务已成功，但状态接口没有返回视频 URL")
        time.sleep(poll_seconds)
    raise CapabilityExecutionError("万相视频生成超时，请检查模型服务状态")


def _request_wanxiang_r2v(
    model: dict[str, Any],
    prompt: str,
    ratio: str,
    duration: str,
    resolution: str,
    media: list[dict[str, str]],
) -> bytes:
    """Run Wan 2.7 reference-to-video with uploaded OSS media."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise CapabilityExecutionError(f"万相模型“{model.get('name', model.get('model', '当前模型'))}”未读取到 API Key。")
    if not any(item.get("type") == "reference_image" for item in media) or not any(item.get("type") == "reference_video" for item in media):
        raise CapabilityExecutionError("万相参考生视频需要至少一张人物图片和一段参考视频")
    seconds = _r2v_duration_seconds(duration)
    media = _r2v_character_replacement_media(media)
    config = model_config(model)
    base_url = str(model.get("base_url") or config.get("base_url") or "https://dashscope.aliyuncs.com").rstrip("/")
    api_base = base_url if base_url.endswith("/api/v1") else base_url + "/api/v1"
    endpoint = str(config.get("video_endpoint") or "") or api_base + "/services/aigc/video-generation/video-synthesis"
    payload = {
        "model": model.get("model"),
        "input": {"prompt": _r2v_character_replacement_prompt(prompt), "media": media},
        "parameters": {
            "resolution": "720P" if str(resolution or "").lower() == "720p" else "1080P",
            "ratio": ratio or "16:9",
            "duration": seconds,
            "prompt_extend": False,
            "watermark": bool(config.get("wanxiang_watermark", False)),
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        "X-DashScope-OssResourceResolve": "enable",
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"万相参考生视频请求失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(f"万相参考生视频请求失败：{exc}") from exc
    job_id = _video_task_id(body)
    if not job_id:
        raise CapabilityExecutionError("万相参考生视频没有返回任务 ID")
    status_endpoint = _video_endpoint(config.get("video_status_endpoint"), api_base + "/tasks/{id}", base_url)
    timeout_seconds = min(max(int(config.get("video_timeout_seconds") or 1800), 60), 3600)
    poll_seconds = min(max(float(config.get("video_poll_interval_seconds") or 3), 1), 15)
    deadline = time.monotonic() + timeout_seconds
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    while time.monotonic() < deadline:
        poll_url = _video_task_url(status_endpoint, job_id)
        try:
            with urllib.request.urlopen(urllib.request.Request(poll_url, headers=poll_headers), timeout=60) as response:
                poll_body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            raise CapabilityExecutionError(f"查询万相参考生视频任务失败（HTTP {exc.code}）：{detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CapabilityExecutionError(f"查询万相参考生视频任务失败：{exc}") from exc
        item = _video_item(poll_body)
        status = _video_status(poll_body)
        if status in {"failed", "error", "cancelled", "canceled"}:
            output = item.get("output") if isinstance(item.get("output"), dict) else {}
            raise CapabilityExecutionError(str(item.get("message") or item.get("error") or output.get("message") or "万相参考生视频生成失败"))
        result_url = _video_result_url(item)
        if result_url:
            return _download_video(result_url, {})
        if status in {"completed", "complete", "succeeded", "success", "done"}:
            raise CapabilityExecutionError("万相参考生视频任务已成功，但状态接口没有返回视频 URL")
        time.sleep(poll_seconds)
    raise CapabilityExecutionError("万相参考生视频生成超时，请检查模型服务状态")


def _replace_video_audio(generated_path: Path, reference_video_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise CapabilityExecutionError("未安装 ffmpeg/ffprobe，无法保留参考视频原音轨")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(reference_video_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        raise CapabilityExecutionError("参考视频不包含可保留的音轨")
    duration_probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(generated_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        generated_duration = float(json.loads(duration_probe.stdout).get("format", {}).get("duration"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError("无法读取生成视频时长，无法保留参考视频原音轨") from exc
    if duration_probe.returncode != 0 or generated_duration <= 0:
        raise CapabilityExecutionError("无法读取生成视频时长，无法保留参考视频原音轨")
    temporary_path = generated_path.with_name(f"{generated_path.stem}-source-audio{generated_path.suffix}")
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(generated_path), "-i", str(reference_video_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-t", str(generated_duration), str(temporary_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not temporary_path.is_file():
        temporary_path.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout).strip()[-600:]
        raise CapabilityExecutionError(f"保留参考视频原音轨失败：{detail or 'ffmpeg 未生成输出'}")
    temporary_path.replace(generated_path)


def _request_video(
    model: dict[str, Any],
    prompt: str,
    ratio: str,
    duration: str,
    resolution: str,
    audio: str,
) -> bytes:
    """Call a configured video endpoint and poll async jobs when needed.

    Providers can override `video_endpoint`, `video_status_endpoint` and
    `video_content_endpoint` in the model config JSON. DashScope/百炼 uses its
    nested `input`/`parameters` request and returns the final video URL from
    the status response, while generic providers use the common `/videos`
    create/status/content contract.
    """
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise CapabilityExecutionError(
            f"视频模型“{model.get('name', model.get('model', '当前模型'))}”未读取到 API Key。"
        )
    config = model_config(model)
    base_url = str(model.get("base_url") or config.get("base_url") or "https://api.openai.com/v1")
    configured_endpoint = str(config.get("video_endpoint") or "")
    is_dashscope = (
        str(model.get("provider") or "").lower() in {"dashscope", "aliyun", "bailian"}
        or "maas.aliyuncs.com" in base_url.lower()
        or "dashscope.aliyuncs.com" in base_url.lower()
        or "maas.aliyuncs.com" in configured_endpoint.lower()
        or "dashscope.aliyuncs.com" in configured_endpoint.lower()
    )
    if is_dashscope and not configured_endpoint:
        endpoint = base_url.rstrip("/") + "/api/v1/services/aigc/video-generation/video-synthesis"
    else:
        endpoint = configured_endpoint or (base_url.rstrip("/") + "/videos")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if is_dashscope:
        headers["X-DashScope-Async"] = "enable"
    try:
        seconds = max(1, int(str(duration or "5s").lower().replace("s", "")))
    except ValueError:
        seconds = 5
    has_audio = str(audio or "有声") == "有声"
    if is_dashscope:
        # 百炼可灵接口要求 prompt 放在 input，视频参数放在 parameters。
        mode = "std" if str(resolution or "").lower() == "720p" else "pro"
        payload = {
            "model": model.get("model"),
            "input": {"prompt": prompt},
            "parameters": {
                "mode": mode,
                "aspect_ratio": ratio or "16:9",
                "duration": seconds,
                "audio": has_audio,
            },
        }
    else:
        payload = {
            "model": model.get("model"),
            "prompt": prompt,
            "seconds": seconds,
            "duration": seconds,
            "size": _video_size(ratio, resolution),
            "audio": has_audio,
        }
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
            content_type = str(response.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise CapabilityExecutionError(f"视频模型请求失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CapabilityExecutionError(f"视频模型请求失败：{exc}") from exc
    stripped = raw.lstrip()
    if content_type.startswith("video/") or (stripped and stripped[:1] not in {b"{", b"["}):
        return raw
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError("视频模型返回了无法解析的结果") from exc
    item = _video_item(body)
    if item.get("b64_json"):
        try:
            return base64.b64decode(item["b64_json"])
        except (ValueError, TypeError) as exc:
            raise CapabilityExecutionError("视频模型返回了无效的 Base64 视频数据") from exc
    result_url = _video_result_url(item)
    if result_url:
        return _download_video(result_url, headers)
    job_id = _video_task_id(body)
    if not job_id:
        raise CapabilityExecutionError("视频模型没有返回可保存的视频数据或任务 ID")
    configured_status_endpoint = str(config.get("video_status_endpoint") or "")
    status_fallback = (
        base_url.rstrip("/") + "/api/v1/tasks/{id}"
        if is_dashscope
        else endpoint.rstrip("/") + "/{id}"
    )
    status_endpoint = _video_endpoint(configured_status_endpoint, status_fallback, base_url)
    configured_content_endpoint = str(config.get("video_content_endpoint") or "")
    content_endpoint = _video_endpoint(
        configured_content_endpoint,
        endpoint.rstrip("/") + "/{id}/content",
        base_url,
    )
    timeout_seconds = min(max(int(config.get("video_timeout_seconds") or 1800), 60), 3600)
    poll_seconds = min(max(float(config.get("video_poll_interval_seconds") or 3), 1), 15)
    deadline = time.monotonic() + timeout_seconds
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    while time.monotonic() < deadline:
        poll_url = _video_task_url(status_endpoint, job_id)
        try:
            with urllib.request.urlopen(urllib.request.Request(poll_url, headers=poll_headers), timeout=60) as response:
                poll_body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:600]
            raise CapabilityExecutionError(
                f"查询视频生成任务失败（HTTP {exc.code}）：{detail or exc.reason}（请求地址：{poll_url}）"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CapabilityExecutionError(f"查询视频生成任务失败：{exc}") from exc
        poll_item = _video_item(poll_body)
        status = _video_status(poll_body)
        if status in {"failed", "error", "cancelled", "canceled"}:
            error_message = poll_item.get("error") or poll_item.get("message")
            output = poll_item.get("output")
            if not error_message and isinstance(output, dict):
                error_message = output.get("message") or output.get("error")
            raise CapabilityExecutionError(str(error_message or "视频生成失败"))
        result_url = _video_result_url(poll_item)
        if result_url:
            return _download_video(result_url, headers)
        if status in {"completed", "complete", "succeeded", "success", "done"}:
            if is_dashscope and not configured_content_endpoint:
                raise CapabilityExecutionError("百炼任务已成功，但状态接口没有返回视频 URL")
            return _download_video(_video_task_url(content_endpoint, job_id), poll_headers)
        time.sleep(poll_seconds)
    raise CapabilityExecutionError("视频生成超时，请检查模型服务状态")


async def generate_video(
    store: Any,
    workspace_root: str,
    prompt: str,
    ratio: str = "16:9",
    duration: str = "5s",
    resolution: str = "1080p",
    audio: str = "有声",
    output_filename: str = "",
    preferred_model_id: str = "",
    first_frame_path: str = "",
    reference_image_paths: list[str] | None = None,
    reference_video_paths: list[str] | None = None,
) -> dict[str, Any]:
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "retryable": False, "message": "视频描述不能为空"}
    model = route_model(store, "video.generate", preferred_model_id)
    if not model:
        return {
            "ok": False,
            "retryable": False,
            "message": "没有配置视频生成模型。请在设置中添加并勾选“支持视频生成”。",
        }
    image_paths = [path for path in (reference_image_paths or []) if path]
    video_paths = [path for path in (reference_video_paths or []) if path]
    if image_paths and video_paths and not _is_wanxiang_r2v(model):
        return {
            "ok": False,
            "retryable": False,
            "message": "当前视频模型不支持同时参考人物图片和视频，请选择 wan2.7-r2v。",
        }
    target, relative_path = _safe_video_output_path(workspace_root, output_filename)
    try:
        if _is_wanxiang_r2v(model):
            _r2v_duration_seconds(duration)
            media = await asyncio.to_thread(_wanxiang_r2v_media, model, workspace_root, image_paths, video_paths)
            video_bytes = await asyncio.to_thread(
                _request_wanxiang_r2v,
                model,
                _r2v_prompt(prompt, len(image_paths), len(video_paths)),
                ratio,
                duration,
                resolution,
                media,
            )
        elif _is_wanxiang_i2v(model):
            if not first_frame_path:
                raise CapabilityExecutionError("万相图生视频需要直接连接一个已生成图片的 AI 图片节点作为首帧")
            first_frame_data_url = _wanxiang_first_frame_data_url(workspace_root, first_frame_path)
            video_bytes = await asyncio.to_thread(
                _request_wanxiang_i2v,
                model,
                prompt,
                duration,
                resolution,
                first_frame_data_url,
            )
        else:
            video_bytes = await asyncio.to_thread(_request_video, model, prompt, ratio, duration, resolution, audio)
        target.write_bytes(video_bytes)
        if _is_wanxiang_r2v(model) and str(audio or "有声") == "有声":
            reference_video = _r2v_reference_file(workspace_root, (reference_video_paths or [""])[0], "reference_video")
            await asyncio.to_thread(_replace_video_audio, target, reference_video)
    except (OSError, CapabilityExecutionError) as exc:
        return {"ok": False, "retryable": False, "message": str(exc)}
    return {
        "ok": True,
        "retryable": False,
        "message": "视频已生成",
        "artifact_path": relative_path,
        "artifact_type": "video",
        "artifact_operation": "created",
        "model_id": model["id"],
    }
