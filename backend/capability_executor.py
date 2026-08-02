from __future__ import annotations

import asyncio
import base64
import json
import os
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
) -> dict[str, Any]:
    """Execute the stable image.generate capability through the routed model."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "retryable": False, "message": "图片描述不能为空"}
    model = route_model(store, "image.generate")
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
