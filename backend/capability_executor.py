from __future__ import annotations

import asyncio
import base64
import json
import os
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


def _request_image(model: dict[str, Any], prompt: str, size: str) -> bytes:
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
        image_bytes = await asyncio.to_thread(_request_image, model, prompt, size)
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


def _video_endpoint(value: Any, fallback: str, base_url: str) -> str:
    endpoint = str(value or fallback)
    return base_url.rstrip("/") + endpoint if endpoint.startswith("/") else endpoint


def _download_video(url: str, headers: dict[str, str]) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise CapabilityExecutionError(f"下载视频模型结果失败：{exc}") from exc


def _request_video(
    model: dict[str, Any],
    prompt: str,
    ratio: str,
    duration: str,
    resolution: str,
    audio: str,
) -> bytes:
    """Call an OpenAI-compatible video endpoint and poll async jobs when needed.

    Providers can override `video_endpoint`, `video_status_endpoint` and
    `video_content_endpoint` in the model config JSON. The defaults follow the
    common `/videos` create/status/content contract.
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
    endpoint = str(config.get("video_endpoint") or (base_url.rstrip("/") + "/videos"))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        seconds = max(1, int(str(duration or "5s").lower().replace("s", "")))
    except ValueError:
        seconds = 5
    payload = {
        "model": model.get("model"),
        "prompt": prompt,
        "seconds": seconds,
        "duration": seconds,
        "size": _video_size(ratio, resolution),
        "audio": str(audio or "有声") == "有声",
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
    job_id = str(item.get("id") or item.get("task_id") or item.get("job_id") or "")
    if not job_id:
        raise CapabilityExecutionError("视频模型没有返回可保存的视频数据或任务 ID")
    status_endpoint = _video_endpoint(config.get("video_status_endpoint"), endpoint.rstrip("/") + "/{id}", base_url)
    content_endpoint = _video_endpoint(config.get("video_content_endpoint"), endpoint.rstrip("/") + "/{id}/content", base_url)
    timeout_seconds = min(max(int(config.get("video_timeout_seconds") or 1800), 60), 3600)
    poll_seconds = min(max(float(config.get("video_poll_interval_seconds") or 3), 1), 15)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        poll_url = status_endpoint.format(id=urllib.parse.quote(job_id, safe=""))
        try:
            with urllib.request.urlopen(urllib.request.Request(poll_url, headers=headers), timeout=60) as response:
                poll_body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CapabilityExecutionError(f"查询视频生成任务失败：{exc}") from exc
        poll_item = _video_item(poll_body)
        status = str(poll_item.get("status") or poll_item.get("state") or "").lower()
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise CapabilityExecutionError(str(poll_item.get("error") or "视频生成失败"))
        result_url = _video_result_url(poll_item)
        if result_url:
            return _download_video(result_url, headers)
        if status in {"completed", "complete", "succeeded", "success", "done"}:
            return _download_video(content_endpoint.format(id=urllib.parse.quote(job_id, safe="")), headers)
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
    target, relative_path = _safe_video_output_path(workspace_root, output_filename)
    try:
        video_bytes = await asyncio.to_thread(_request_video, model, prompt, ratio, duration, resolution, audio)
        target.write_bytes(video_bytes)
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
