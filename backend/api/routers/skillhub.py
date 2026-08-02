from __future__ import annotations

from fastapi import APIRouter
from ...core import *

router = APIRouter()


@router.get("/api/skillhub/categories")
async def list_skillhub_categories():
    return SKILLHUB_CATEGORIES


@router.get("/api/skillhub/rankings")
async def list_skillhub_rankings():
    return SKILLHUB_RANKINGS


@router.get("/api/skillhub/installed")
async def list_installed_skillhub():
    items = local_skill_cards()
    return {"content": items, "totalElements": len(items), "source": "local"}


@router.get("/api/skillhub/skills")
async def list_skillhub(
    q: str = "",
    category: str = "all",
    sort: str = "downloads",
    ranking: str = "",
    page: int = 0,
    size: int = 18,
    installed: bool = False,
):
    if installed:
        items = local_skill_cards()
        keyword = q.strip().lower()
        if keyword:
            items = [
                item
                for item in items
                if keyword in f"{item['name']} {item['description']}".lower()
            ]
        start = max(page, 0) * min(max(size, 1), 100)
        limit = min(max(size, 1), 100)
        return {
            "content": items[start : start + limit],
            "totalElements": len(items),
            "page": page,
            "size": limit,
            "source": "local",
        }
    try:
        content, total = await fetch_skillhub_skills(
            q.strip(), category, sort, page, size, ranking
        )
        return {
            "content": content,
            "totalElements": total,
            "page": page,
            "size": min(max(size, 1), 100),
            "categories": SKILLHUB_CATEGORIES,
            "rankings": SKILLHUB_RANKINGS,
            "source": "skillhub",
        }
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


async def install_skillhub(payload: SkillHubInstallRequest) -> dict[str, Any]:
    source = parse_skills_sh_source(payload.coordinate)
    if source and payload.version.strip():
        raise HTTPException(400, "skills.sh 技能暂不支持指定版本，请清空版本后重试")
    coordinate = (
        payload.coordinate.strip()
        if source
        else validate_skill_coordinate(payload.coordinate)
    )
    version = validate_skill_version(payload.version)
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    if source:
        repository, slug = source
        namespace = repository.rsplit("/", 1)[-1]
        normalized_coordinate = slug
    else:
        normalized_coordinate = coordinate.removeprefix("@")
        coordinate_parts = normalized_coordinate.split("/", 1)
        if len(coordinate_parts) == 2:
            namespace, slug = coordinate_parts
        elif "--" in normalized_coordinate:
            namespace, slug = normalized_coordinate.split("--", 1)
        else:
            namespace, slug = "global", normalized_coordinate
    coordinate_candidates = {
        normalized_coordinate,
        slug,
        normalized_coordinate.replace("/", "--"),
    }
    existing = next(
        (
            item
            for item in scan_skills(SKILLS_ROOT)
            if item["id"] in coordinate_candidates
            or item["name"] in coordinate_candidates
        ),
        None,
    )
    if existing:
        try:
            dependency_result = await asyncio.to_thread(
                ensure_skill_node_dependencies,
                existing["id"],
                existing["root_path"],
            )
        except TimeoutError as exc:
            raise HTTPException(504, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"Skill 依赖准备失败：{exc}") from exc
        return {
            "ok": True,
            "already_installed": True,
            "coordinate": coordinate,
            "message": f"技能已安装：{existing['name']}",
            "output": dependency_result.get("output", ""),
            "skills": local_skill_cards(),
        }
    try:
        output = (
            await asyncio.to_thread(run_skills_cli_install, repository, slug)
            if source
            else await asyncio.to_thread(run_skillhub_cli_install, coordinate, version)
        )
    except TimeoutError as exc:
        raise HTTPException(504, "技能安装超时，请检查网络后重试") from exc
    except Exception as exc:
        raise HTTPException(400, f"SkillHub 安装失败：{exc}") from exc
    discovered = scan_skills(SKILLS_ROOT)
    if not any(
        item["id"] in coordinate_candidates or item["name"] in coordinate_candidates
        for item in discovered
    ):
        raise HTTPException(
            400, "腾讯 SkillHub CLI 执行完成，但 skills 目录中没有发现对应的 SKILL.md"
        )
    dependency_outputs: list[str] = []
    for item in discovered:
        if item["id"] in coordinate_candidates or item["name"] in coordinate_candidates:
            try:
                dependency_result = await asyncio.to_thread(
                    ensure_skill_node_dependencies,
                    item["id"],
                    item["root_path"],
                )
            except TimeoutError as exc:
                raise HTTPException(504, str(exc)) from exc
            except Exception as exc:
                raise HTTPException(400, f"Skill 依赖准备失败：{exc}") from exc
            if dependency_result.get("output"):
                dependency_outputs.append(str(dependency_result["output"]))
    for item in discovered:
        if not store.one("skills", "id=?", (item["id"],)):
            store.insert("skills", skill_store_row(item))
    combined_output = "\n".join(part for part in [output, *dependency_outputs] if part)
    return {
        "ok": True,
        "coordinate": coordinate,
        "message": "技能安装成功",
        "output": combined_output,
        "skills": local_skill_cards(),
    }


@router.post("/api/skillhub/install")
async def install_skillhub_route(payload: SkillHubInstallRequest):
    return await install_skillhub(payload)


@router.post("/api/skillhub/add")
async def add_skillhub_route(payload: SkillHubInstallRequest):
    return await install_skillhub(payload)
