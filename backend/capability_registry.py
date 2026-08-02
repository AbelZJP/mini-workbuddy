from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_router import (
    configured_capability_model_id,
    model_capabilities,
    route_model,
)


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    name: str
    description: str
    model_capability: str
    output_type: str


class CapabilityRegistry:
    """Stable capability contracts shared by built-ins, Skills and MCP adapters."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}

    def register(self, definition: CapabilityDefinition) -> None:
        self._definitions[definition.id] = definition

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        return self._definitions.get(capability_id)

    def all(self) -> list[CapabilityDefinition]:
        return list(self._definitions.values())


registry = CapabilityRegistry()
registry.register(
    CapabilityDefinition(
        id="image.generate",
        name="图片生成",
        description="根据文字提示生成图片并保存到当前工作空间。",
        model_capability="image.generate",
        output_type="image",
    )
)
registry.register(
    CapabilityDefinition(
        id="video.generate",
        name="视频生成",
        description="根据文字提示生成视频并保存到当前工作空间。",
        model_capability="video.generate",
        output_type="video",
    )
)


def capability_rows(store: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for definition in registry.all():
        model = route_model(store, definition.model_capability)
        result.append(
            {
                "id": definition.id,
                "name": definition.name,
                "description": definition.description,
                "model_capability": definition.model_capability,
                "output_type": definition.output_type,
                "available": bool(model),
                "model_id": model.get("id") if model else "",
                "model_name": model.get("name") if model else "",
                "configured_model_id": configured_capability_model_id(
                    store, definition.model_capability
                ),
            }
        )
    return result


def capability_model_options(store: Any, capability_id: str) -> list[dict[str, Any]]:
    definition = registry.get(capability_id)
    if not definition:
        return []
    return [
        {"id": row["id"], "name": row["name"], "model": row["model"]}
        for row in store.all("models", "1=1 ORDER BY name")
        if definition.model_capability in model_capabilities(row)
        and bool(row.get("enabled", 1))
    ]
