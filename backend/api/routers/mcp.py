from __future__ import annotations

from fastapi import APIRouter
from ...core import *

router = APIRouter()


@router.get("/api/mcp")
async def list_mcp():
    result = []
    for row in store.all("mcp_servers", "1=1 ORDER BY name"):
        item = store.json_config(row, ("args", "allowed_tools", "env", "headers"))
        item.pop("source_url", None)
        item["enabled"] = bool(row["enabled"])
        result.append(item)
    return result


@router.post("/api/mcp")
async def create_mcp(payload: MCPConfig):
    row = {
        **payload.model_dump(),
        "args": json.dumps(payload.args),
        "allowed_tools": json.dumps(payload.allowed_tools),
        "env": json.dumps(payload.env),
        "headers": json.dumps(payload.headers),
        "enabled": int(payload.enabled),
        "updated_at": now(),
    }
    store.insert("mcp_servers", row)
    return payload


@router.post("/api/mcp/test")
async def test_mcp_config(payload: MCPConfig):
    return await test_mcp(payload.model_dump())


@router.patch("/api/mcp/{server_id}")
async def update_mcp(server_id: str, payload: dict[str, Any]):
    current = store.one("mcp_servers", "id=?", (server_id,))
    if not current:
        raise HTTPException(404, "mcp server not found")
    allowed = {"name", "transport", "command", "url", "enabled"}
    data = {key: payload[key] for key in allowed if key in payload}
    for key in ("args", "allowed_tools", "env", "headers"):
        if key in payload:
            data[key] = json.dumps(payload[key])
    if "enabled" in data:
        data["enabled"] = int(bool(data["enabled"]))
    data["updated_at"] = now()
    row = store.update("mcp_servers", "id", server_id, data)
    return store.json_config(
        row or current, ("args", "allowed_tools", "env", "headers")
    ) | {"enabled": bool((row or current)["enabled"])}


@router.delete("/api/mcp/{server_id}")
async def delete_mcp(server_id: str):
    if not store.one("mcp_servers", "id=?", (server_id,)):
        raise HTTPException(404, "MCP 连接器不存在")
    store.delete("mcp_servers", "id", server_id)
    return {"ok": True}


@router.post("/api/mcp/{server_id}/test")
async def test_mcp_server(server_id: str):
    row = store.one("mcp_servers", "id=?", (server_id,))
    if not row:
        raise HTTPException(404, "mcp server not found")
    return await test_mcp(
        store.json_config(row, ("args", "allowed_tools", "env", "headers"))
    )
