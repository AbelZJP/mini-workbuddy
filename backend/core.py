from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import shutil
import sys
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request as URLRequest, urlopen

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from .agent_runtime import run_agentscope
from .document_parser import parse_attachments
from .experts import EXPERT_REPOSITORY, install_expert, sync_catalog, uninstall_expert
from .mcp_manager import test_mcp
from .skill_dependencies import ensure_skill_node_dependencies
from .skills import (
    build_skill_prompt,
    resolve_selected_skills,
    scan_skill_sources,
    scan_skills,
)
from .repositories.storage_repository import StorageRepository
from .schemas import (
    ApprovalDecision,
    CreateTask,
    CreateWorkspace,
    MCPConfig,
    MemoryRequest,
    MessageRequest,
    ModelConfig,
    SkillHubInstallRequest,
    Task,
    TaskCapabilities,
    Workspace,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / ".mini-workbuddy"
load_dotenv(ROOT / ".env", override=True)
store = StorageRepository(DATA / "workbuddy.sqlite3")
cancel_events: dict[str, asyncio.Event] = {}
approval_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
run_tasks: dict[str, asyncio.Task[Any]] = {}
run_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
active_runs: dict[str, str] = {}


SKILLS_ROOT = ROOT / "skills"
EXPERTS_ROOT = DATA / "experts"
SKILLHUB_API_BASE = "https://api.skillhub.cn"
SKILLHUB_CLI_INSTALL_URL = (
    "https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/install.sh"
)
SKILLHUB_CATEGORIES = [
    {"id": "all", "name": "全部"},
    {"id": "office-efficiency", "name": "办公效率"},
    {"id": "content-creation", "name": "内容创作"},
    {"id": "dev-programming", "name": "开发编程"},
    {"id": "data-analysis", "name": "数据分析"},
    {"id": "design-media", "name": "设计多媒体"},
    {"id": "ai-agent", "name": "AI Agent"},
    {"id": "knowledge-management", "name": "知识管理"},
    {"id": "business-ops", "name": "商业运营"},
    {"id": "education", "name": "教育学系"},
    {"id": "professional", "name": "行业专业"},
    {"id": "it-ops-security", "name": "IT运维与安全"},
    {"id": "life-service", "name": "生活服务"},
]
SKILLHUB_CATEGORY_ALIASES = {
    "office": "office-efficiency",
    "content": "content-creation",
    "development": "dev-programming",
    "data": "data-analysis",
    "design": "design-media",
    "agent": "ai-agent",
    "knowledge": "knowledge-management",
    "business_ops": "business-ops",
    "industry": "professional",
    "it_ops": "it-ops-security",
    "life": "life-service",
}
SKILLHUB_RANKINGS = [
    {
        "id": "trending",
        "name": "近期飙升",
        "description": "按最近更新时间和新发布活跃度发现技能",
    },
    {"id": "featured", "name": "推荐精选", "description": "按评分和社区质量发现技能"},
    {"id": "downloads", "name": "下载量", "description": "按累计下载量排序"},
    {"id": "favorites", "name": "收藏量", "description": "按社区星标收藏量排序"},
]
SKILLHUB_RANKING_SORTS = {
    "trending": "updated_at",
    "featured": "curated_score",
    "downloads": "downloads",
    "favorites": "stars",
}


def skill_store_row(item: dict[str, Any]) -> dict[str, Any]:
    """Keep runtime-only source metadata out of the legacy skills table."""
    return {
        "id": item["id"],
        "name": item["name"],
        "description": item.get("description", ""),
        "path": item["path"],
        "enabled": int(bool(item.get("enabled", True))),
        "updated_at": now(),
    }


def local_skill_cards() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "slug": item.get("slug", item["id"]),
            "namespace": item.get("namespace") or "local",
            "name": item["name"],
            "description": item["description"],
            "labels": [],
            "downloads": 0,
            "rating": 0,
            "starCount": 0,
            "latestVersion": "",
            "installed": True,
            "source": "local",
        }
        for item in scan_skills(SKILLS_ROOT)
    ]


def normalize_skillhub_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (
            payload.get("content") or payload.get("items") or payload.get("data") or []
        )
        if isinstance(items, dict):
            items = (
                items.get("skills") or items.get("content") or items.get("items") or []
            )
    else:
        items = []
    result = []
    installed_ids = {item["id"] for item in scan_skills(SKILLS_ROOT)}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        raw_namespace = raw.get("namespace")
        namespace = str(
            (raw_namespace.get("handle") or raw_namespace.get("displayName"))
            if isinstance(raw_namespace, dict)
            else (raw_namespace or raw.get("owner") or "global")
        )
        slug = str(raw.get("slug") or raw.get("id") or "").strip()
        if not slug:
            continue
        headline = raw.get("headlineVersion") or raw.get("publishedVersion") or {}
        raw_labels = raw.get("labels") or raw.get("tags") or []
        if isinstance(raw_labels, dict):
            raw_labels = list(raw_labels.keys())
        labels = [
            str(label.get("name") or label.get("key"))
            if isinstance(label, dict)
            else str(label)
            for label in raw_labels
        ]
        labels.extend(
            str(item.get("name") or item.get("key"))
            for item in (raw.get("subCategories") or [])
            if isinstance(item, dict)
        )
        result.append(
            {
                "id": str(raw.get("id") or f"{namespace}--{slug}"),
                "slug": slug,
                "namespace": namespace,
                "name": raw.get("name") or raw.get("displayName") or slug,
                "description": raw.get("description_zh")
                or raw.get("description")
                or raw.get("summary")
                or "",
                "labels": labels,
                "downloads": raw.get("downloads") or raw.get("downloadCount") or 0,
                "rating": raw.get("rating") or raw.get("ratingAvg") or 0,
                "starCount": raw.get("starCount") or raw.get("stars") or 0,
                "latestVersion": raw.get("latestVersion")
                or raw.get("version")
                or headline.get("version")
                or "",
                "updatedAt": raw.get("updatedAt") or raw.get("updated_at") or "",
                "installed": slug in installed_ids
                or f"{namespace}--{slug}" in installed_ids,
                "source": "skillhub",
            }
        )
    return result


def fetch_skillhub_json(url: str) -> Any:
    request = URLRequest(
        url, headers={"Accept": "application/json", "User-Agent": "mini-workbuddy/0.2"}
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def run_skillhub_cli_install(coordinate: str, version: str) -> str:
    """通过腾讯 SkillHub 官方 CLI 安装到本项目的 skills 目录。"""
    cli = (
        (os.getenv("SKILLHUB_CLI") or "").strip()
        or shutil.which("skillhub")
        or str(Path.home() / ".local/bin/skillhub")
    )
    if version:
        raise RuntimeError(
            "腾讯 SkillHub CLI 当前安装命令只支持安装最新版本，请清空版本后重试"
        )
    normalized_coordinate = coordinate.removeprefix("@")
    coordinate_parts = normalized_coordinate.split("/", 1)
    if len(coordinate_parts) == 2:
        namespace, slug = coordinate_parts
    elif "--" in normalized_coordinate:
        namespace, slug = normalized_coordinate.split("--", 1)
    else:
        namespace, slug = "global", normalized_coordinate
    command = [cli, "install", slug, "--dir", str(SKILLS_ROOT), "--json"]
    if namespace != "global":
        command.extend(["--namespace", namespace])
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            input="",
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "未找到腾讯 SkillHub CLI。请先执行：\n"
            f"curl -fsSL {SKILLHUB_CLI_INSTALL_URL} | bash -s -- --cli-only\n"
            "安装完成后重启 mini-workbuddy。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("腾讯 SkillHub CLI 安装超时，请检查网络或登录状态") from exc

    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    if completed.returncode != 0:
        detail = output[-4000:] if output else "CLI 未返回具体错误信息"
        raise RuntimeError(
            f"腾讯 SkillHub CLI 安装失败（退出码 {completed.returncode}）：\n{detail}"
        )
    return output[-4000:] if output else "腾讯 SkillHub CLI 安装完成"


def parse_skills_sh_source(value: str) -> tuple[str, str] | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "skills.sh",
        "www.skills.sh",
    }:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or not all(
        re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts
    ):
        raise HTTPException(
            400, "skills.sh 链接格式应为：https://www.skills.sh/{作者}/{仓库}/{技能名}"
        )
    owner, repository, skill_name = parts
    return f"https://github.com/{owner}/{repository}", skill_name


def run_skills_cli_install(repository: str, skill_name: str) -> str:
    """使用 skills.sh 官方 CLI 将指定 GitHub Skill 复制到项目 skills/。"""
    npx = (os.getenv("SKILLS_CLI_NPX") or "").strip() or shutil.which("npx")
    if not npx:
        raise RuntimeError("未找到 npx，无法安装 skills.sh 技能。请先安装 Node.js。")
    command = [
        npx,
        "--yes",
        "skills",
        "add",
        repository,
        "--skill",
        skill_name,
        "--agent",
        "openclaw",
        "--copy",
        "--yes",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            input="",
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
            env={**os.environ, "NO_COLOR": "1", "DISABLE_TELEMETRY": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("skills.sh 安装超时，请检查网络后重试") from exc
    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    if completed.returncode != 0:
        raise RuntimeError(output or "skills CLI 返回失败")
    return output[-4000:] if output else "skills.sh 技能安装完成"


async def fetch_skillhub_skills(
    query: str, category: str, sort: str, page: int, size: int, ranking: str = ""
) -> tuple[list[dict[str, Any]], int]:
    requested_size = min(max(size, 1), 100)
    category = SKILLHUB_CATEGORY_ALIASES.get(category, category)
    remote_sort = SKILLHUB_RANKING_SORTS.get(ranking) or sort or "score"
    sort_by = {
        "rating": "score",
        "relevance": "score",
        "updated": "updated_at",
        "downloads": "downloads",
    }.get(remote_sort, remote_sort)
    params = {
        "page": max(page, 0) + 1,
        "pageSize": requested_size,
        "sortBy": sort_by,
        "order": "asc" if sort_by == "name" else "desc",
    }
    if query:
        params["keyword"] = query
    if category and category != "all":
        params["category"] = category
    endpoint = f"{SKILLHUB_API_BASE}/api/skills?{urlencode(params)}"
    try:
        payload = await asyncio.to_thread(fetch_skillhub_json, endpoint)
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise RuntimeError(str(payload.get("message") or "SkillHub API 返回错误"))
        items = normalize_skillhub_items(payload)
        metadata = (
            payload.get("data")
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
            else payload
        )
        reported_total = metadata.get("total") if isinstance(metadata, dict) else None
        total = int(reported_total) if reported_total is not None else len(items)
        return items[:requested_size], total
    except Exception as exc:
        raise RuntimeError(f"SkillHub 暂时无法连接：{exc}") from exc


def validate_skill_coordinate(coordinate: str) -> str:
    value = coordinate.strip()
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        query_slug = parse_qs(parsed.query).get("slug", [""])[-1]
        value = query_slug or parsed.path.rstrip("/").split("/")[-1]
    if not re.fullmatch(
        r"@?[\w\u4e00-\u9fff.-]+(?:/[\w\u4e00-\u9fff.-]+|--[\w\u4e00-\u9fff.-]+)?",
        value,
    ):
        raise HTTPException(
            400, "技能标识无效，请填写 SkillHub 技能名、命名空间/技能名或技能详情链接"
        )
    return value


def validate_skill_version(version: str) -> str:
    value = version.strip()
    if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", value):
        raise HTTPException(400, "技能版本号无效")
    return value


def selected_expert_prompt_sections(expert_ids: list[str]) -> list[dict[str, str]]:
    """Load selected expert prompts as independent sections for single/team modes."""
    if not expert_ids:
        return []
    installed_root = (EXPERTS_ROOT / "installed").resolve()
    rows = {row["id"]: row for row in store.all("experts", "installed=1 AND enabled=1")}
    sections: list[dict[str, str]] = []
    for expert_id in expert_ids:
        row = rows.get(expert_id)
        if not row:
            continue
        path = Path(
            row.get("installed_path") or installed_root / row["catalog_path"]
        ).resolve()
        if not path.is_relative_to(installed_root) or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore").strip()
        if content:
            sections.append(
                {"id": str(expert_id), "name": str(row["name"]), "prompt": content}
            )
    return sections


def selected_expert_prompt(expert_ids: list[str]) -> str:
    """Keep the legacy single-Agent prompt format for one-expert tasks."""
    return "\n\n".join(
        f"## 专家：{section['name']}\n{section['prompt']}"
        for section in selected_expert_prompt_sections(expert_ids)
    )


def register_task_artifacts(
    task_id: str, workspace_root: str, tool_logs: list[dict[str, Any]]
) -> None:
    """Persist files explicitly reported by a Skill script as task artifacts."""
    root = Path(workspace_root).expanduser().resolve()
    for log in tool_logs:
        relative = str(log.get("artifact_path") or "").replace("\\", "/").strip()
        if not relative:
            continue
        try:
            candidate = (root / relative).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                continue
            normalized = candidate.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if store.one("artifacts", "task_id=? AND path=?", (task_id, normalized)):
            continue
        store.insert(
            "artifacts",
            {
                "id": uuid.uuid4().hex,
                "task_id": task_id,
                "path": normalized,
                "artifact_type": str(
                    log.get("artifact_type") or candidate.suffix.lstrip(".") or "file"
                ),
                "operation": str(log.get("artifact_operation") or "created"),
                "previewable": int(
                    candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
                ),
                "created_at": now(),
            },
        )


def model_row(row: dict[str, Any]) -> ModelConfig:
    config = {}
    try:
        config = json.loads(row.get("config") or "{}")
    except json.JSONDecodeError:
        pass
    return ModelConfig(
        id=row["id"],
        name=row["name"],
        provider=row["provider"],
        model=row["model"],
        base_url=row.get("base_url", ""),
        api_key_env=row.get("api_key_env", ""),
        enabled=bool(row["enabled"]),
        supports_vision=bool(config.get("supports_vision", False)),
        supports_image_generation=bool(
            config.get("supports_image_generation", False)
            or "image.generate" in (config.get("capabilities") or [])
        ),
        supports_video_generation=bool(
            config.get("supports_video_generation", False)
            or "video.generate" in (config.get("capabilities") or [])
        ),
        video_endpoint=str(config.get("video_endpoint") or ""),
        video_status_endpoint=str(config.get("video_status_endpoint") or ""),
        video_content_endpoint=str(config.get("video_content_endpoint") or ""),
        is_default=row["id"] == default_model_id(),
    )


def default_model_id() -> str:
    setting = store.one("settings", "key=?", ("default_model_id",))
    if setting and store.one("models", "id=?", (setting["value"],)):
        return setting["value"]
    fallback = (
        store.one("models", "id=?", ("demo",))
        or (store.all("models", "1=1 ORDER BY name") or [None])[0]
    )
    return fallback["id"] if fallback else "demo"


def set_default_model(model_id: str) -> None:
    if store.one("settings", "key=?", ("default_model_id",)):
        store.update("settings", "key", "default_model_id", {"value": model_id})
    else:
        store.insert("settings", {"key": "default_model_id", "value": model_id})


def seed() -> None:
    if not store.all("workspaces"):
        stamp = now()
        store.insert(
            "workspaces",
            {
                "id": "default",
                "name": "默认工作空间",
                "root_path": str(ROOT),
                "description": "mini-workbuddy 默认工作空间",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
    if not store.all("models"):
        store.insert(
            "models",
            {
                "id": "demo",
                "name": "演示模型",
                "provider": "openai_compatible",
                "model": "demo-stream",
                "base_url": "",
                "api_key_env": "",
                "enabled": 1,
                "config": "{}",
            },
        )
    if not store.one("settings", "key=?", ("default_model_id",)):
        set_default_model(default_model_id())
    if not store.all("tasks"):
        stamp = now()
        store.insert(
            "tasks",
            {
                "id": "welcome",
                "workspace_id": "default",
                "title": "认识 mini-workbuddy",
                "status": "completed",
                "permission_mode": "workspace",
                "model_id": "demo",
                "current_state": "已完成",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        store.add_message(
            "welcome",
            "assistant",
            "你好，我是 mini-workbuddy。选择一个工作空间，告诉我你想完成什么。",
            stamp,
        )
    for skill in scan_skills(ROOT / "skills"):
        if not store.one("skills", "id=?", (skill["id"],)):
            store.insert("skills", skill_store_row(skill))


def recover_incomplete_runs() -> None:
    """A single-process worker cannot safely resume a half-finished tool call after restart."""
    stamp = now()
    rows = store.all(
        "agent_runs", "status IN ('queued', 'running', 'waiting_for_approval')"
    )
    for run in rows:
        message = "后端已重启，未完成的后台 Run 已停止；请重新发送任务。"
        store.update(
            "agent_runs",
            "id",
            run["id"],
            {
                "status": "failed",
                "current_step": "后端重启后停止",
                "error": message,
                "finished_at": stamp,
                "last_heartbeat": stamp,
                "updated_at": stamp,
            },
        )
        store.update(
            "tasks",
            "id",
            run["task_id"],
            {
                "status": "failed",
                "current_state": "后端重启后停止",
                "updated_at": stamp,
            },
        )
        if not store.run_events(run["id"], after=0):
            store.add_run_event(
                run["id"],
                "task.failed",
                {"type": "task.failed", "task_id": run["task_id"], "message": message},
                stamp,
            )


seed()
recover_incomplete_runs()
