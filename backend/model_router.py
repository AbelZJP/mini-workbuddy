from __future__ import annotations

import json
from typing import Any


CAPABILITY_MODEL_SETTING_PREFIX = "capability_model:"


def model_config(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("config") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def model_capabilities(row: dict[str, Any]) -> set[str]:
    config = model_config(row)
    values = config.get("capabilities") or []
    capabilities = {str(value) for value in values if value}
    if config.get("supports_vision") or config.get("vision"):
        capabilities.add("vision.input")
    if config.get("supports_image_generation"):
        capabilities.add("image.generate")
    if config.get("supports_video_generation"):
        capabilities.add("video.generate")
    if config.get("supports_voice_cloning"):
        capabilities.add("voice.clone")
    return capabilities


def has_capability(row: dict[str, Any], capability_id: str) -> bool:
    return capability_id in model_capabilities(row) and bool(row.get("enabled", 1))


def capability_setting_key(capability_id: str) -> str:
    return f"{CAPABILITY_MODEL_SETTING_PREFIX}{capability_id}"


def configured_capability_model_id(store: Any, capability_id: str) -> str:
    setting = store.one("settings", "key=?", (capability_setting_key(capability_id),))
    return str(setting.get("value") or "") if setting else ""


def route_model(
    store: Any,
    capability_id: str,
    preferred_model_id: str = "",
) -> dict[str, Any] | None:
    """Resolve a capability to an enabled model without changing the main chat model."""
    configured_id = configured_capability_model_id(store, capability_id)
    candidate_ids = [preferred_model_id, configured_id]
    for model_id in candidate_ids:
        if not model_id:
            continue
        row = store.one("models", "id=?", (model_id,))
        if row and has_capability(row, capability_id):
            return row
    return next(
        (
            row
            for row in store.all("models", "1=1 ORDER BY name")
            if has_capability(row, capability_id)
        ),
        None,
    )


def set_capability_model(
    store: Any,
    capability_id: str,
    model_id: str,
) -> dict[str, Any] | None:
    """Persist a capability override; an empty model id restores automatic routing."""
    if model_id:
        model = store.one("models", "id=?", (model_id,))
        if not model or not has_capability(model, capability_id):
            raise ValueError("所选模型未声明该能力")
    key = capability_setting_key(capability_id)
    setting = store.one("settings", "key=?", (key,))
    if setting:
        store.update("settings", "key", key, {"value": model_id})
    else:
        store.insert("settings", {"key": key, "value": model_id})
    return route_model(store, capability_id)
