from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...capability_registry import capability_model_options, capability_rows, registry
from ...core import store
from ...model_router import set_capability_model

router = APIRouter()


@router.get("/api/capabilities")
async def list_capabilities():
    return {
        "items": capability_rows(store),
        "registry": [
            {"id": item.id, "name": item.name, "description": item.description}
            for item in registry.all()
        ],
    }


@router.get("/api/capabilities/{capability_id}/models")
async def list_capability_models(capability_id: str):
    if not registry.get(capability_id):
        raise HTTPException(404, "能力不存在")
    return capability_model_options(store, capability_id)


@router.patch("/api/capabilities/{capability_id}")
async def update_capability(capability_id: str, payload: dict[str, str]):
    if not registry.get(capability_id):
        raise HTTPException(404, "能力不存在")
    try:
        model = set_capability_model(
            store, capability_id, str(payload.get("model_id") or "")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "capability_id": capability_id,
        "model_id": model.get("id") if model else "",
    }
