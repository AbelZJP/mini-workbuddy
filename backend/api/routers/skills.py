from __future__ import annotations

from fastapi import APIRouter
from ...core import *

router = APIRouter()


@router.get("/api/skills")
async def list_skills(workspace_id: str | None = None):
    workspace_root: str | None = None
    if workspace_id:
        workspace = store.one("workspaces", "id=?", (workspace_id,))
        if not workspace:
            raise HTTPException(404, "工作空间不存在")
        workspace_root = workspace["root_path"]
    discovered = {
        item["id"]: item for item in scan_skill_sources(SKILLS_ROOT, workspace_root)
    }
    for item in discovered.values():
        if item["scope"] == "workspace":
            item["enabled"] = True
            continue
        existing = store.one("skills", "id=?", (item["id"],))
        if existing:
            item["enabled"] = bool(existing["enabled"])
        else:
            store.insert("skills", skill_store_row(item))
            item["enabled"] = True
    return list(discovered.values())


@router.get("/api/skills/{skill_id}")
async def get_skill(skill_id: str):
    row = store.one("skills", "id=?", (skill_id,))
    if not row:
        raise HTTPException(404, "skill not found")
    path = Path(row["path"])
    return {
        **row,
        "enabled": bool(row["enabled"]),
        "content": path.read_text(encoding="utf-8") if path.exists() else "",
    }


@router.patch("/api/skills/{skill_id}")
async def update_skill(skill_id: str, payload: dict[str, Any]):
    row = store.update(
        "skills",
        "id",
        skill_id,
        {"enabled": int(bool(payload.get("enabled", True))), "updated_at": now()},
    )
    if not row:
        raise HTTPException(404, "skill not found")
    return {**row, "enabled": bool(row["enabled"])}


@router.delete("/api/skills/{skill_id}")
async def delete_skill(skill_id: str):
    discovered = next(
        (item for item in scan_skills(SKILLS_ROOT) if item["id"] == skill_id), None
    )
    stored = store.one("skills", "id=?", (skill_id,))
    if not discovered and not stored:
        raise HTTPException(404, "技能不存在")
    if discovered:
        skills_root = SKILLS_ROOT.resolve()
        skill_file = Path(discovered["path"]).resolve()
        skill_dir = skill_file.parent
        if (
            skill_file.name != "SKILL.md"
            or skill_dir == skills_root
            or not skill_dir.is_relative_to(skills_root)
        ):
            raise HTTPException(400, "技能目录不在项目 skills 目录内，拒绝删除")
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
    store.delete("skills", "id", skill_id)
    return {"ok": True, "id": skill_id}
