from __future__ import annotations

from fastapi import APIRouter
from ...core import *

router = APIRouter()


def expert_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "installed": bool(row.get("installed")),
        "enabled": bool(row.get("enabled")),
    }


@router.get("/api/experts")
async def list_experts(query: str = "", department: str = "", installed: bool = False):
    rows = [
        expert_row(row) for row in store.all("experts", "1=1 ORDER BY department, name")
    ]
    keyword = query.strip().lower()
    if keyword:
        rows = [
            row
            for row in rows
            if keyword
            in f"{row['name']} {row['description']} {row['department']}".lower()
        ]
    if department:
        rows = [row for row in rows if row["department"] == department]
    if installed:
        rows = [row for row in rows if row["installed"]]
    departments = sorted(
        {row["department"] for row in store.all("experts") if row.get("department")}
    )
    return {
        "items": rows,
        "departments": departments,
        "synced": (EXPERTS_ROOT / "catalog").exists(),
        "repository": EXPERT_REPOSITORY,
    }


@router.post("/api/experts/sync")
async def sync_experts():
    try:
        rows = await asyncio.to_thread(sync_catalog, store, EXPERTS_ROOT)
    except Exception as exc:
        raise HTTPException(502, f"专家库同步失败：{exc}") from exc
    return {
        "items": [expert_row(row) for row in rows],
        "total": len(rows),
        "repository": EXPERT_REPOSITORY,
    }


@router.get("/api/experts/{expert_id}")
async def get_expert(expert_id: str):
    row = store.one("experts", "id=?", (expert_id,))
    if not row:
        raise HTTPException(404, "专家不存在")
    catalog = (EXPERTS_ROOT / "catalog").resolve()
    path = (catalog / row["catalog_path"]).resolve()
    if not path.is_relative_to(catalog):
        raise HTTPException(400, "专家文件路径不合法")
    return {
        **expert_row(row),
        "content": path.read_text(encoding="utf-8", errors="ignore")
        if path.exists()
        else "",
    }


@router.post("/api/experts/{expert_id}/install")
async def install_expert_route(expert_id: str):
    try:
        return expert_row(install_expert(store, EXPERTS_ROOT, expert_id))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/api/experts/{expert_id}")
async def uninstall_expert_route(expert_id: str):
    try:
        return expert_row(uninstall_expert(store, EXPERTS_ROOT, expert_id))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
