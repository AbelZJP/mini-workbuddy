from __future__ import annotations

from fastapi import APIRouter
from ...core import *
from ...services.task_service import task_row, task_title_from_message

router = APIRouter()


@router.get("/api/workspaces/{workspace_id}/tasks", response_model=list[Task])
async def list_tasks(workspace_id: str):
    return [
        task_row(row)
        for row in store.all(
            "tasks", "workspace_id=? ORDER BY updated_at DESC", (workspace_id,)
        )
    ]


@router.post("/api/tasks", response_model=Task)
async def create_task(payload: CreateTask):
    if not store.one("workspaces", "id=?", (payload.workspace_id,)):
        raise HTTPException(404, "workspace not found")
    task_id = uuid.uuid4().hex[:10]
    stamp = now()
    row = {
        "id": task_id,
        "workspace_id": payload.workspace_id,
        "title": payload.title,
        "status": "queued",
        "permission_mode": payload.permission_mode,
        "model_id": payload.model_id,
        "current_state": "等待输入",
        "created_at": stamp,
        "updated_at": stamp,
    }
    store.insert("tasks", row)
    return task_row(row)


@router.get("/api/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str):
    row = store.one("tasks", "id=?", (task_id,))
    if not row:
        raise HTTPException(404, "task not found")
    return task_row(row)


@router.patch("/api/tasks/{task_id}/capabilities", response_model=Task)
async def update_task_capabilities(task_id: str, payload: TaskCapabilities):
    task = store.one("tasks", "id=?", (task_id,))
    if not task:
        raise HTTPException(404, "任务不存在")
    skill_ids = list(
        dict.fromkeys(
            item.strip() for item in payload.selected_skill_ids if item.strip()
        )
    )
    expert_ids = list(
        dict.fromkeys(
            item.strip() for item in payload.selected_expert_ids if item.strip()
        )
    )
    workspace = store.one("workspaces", "id=?", (task["workspace_id"],))
    enabled_skills = {row["id"] for row in store.all("skills", "enabled=1")}
    available_skills = {
        row["id"]: row
        for row in scan_skill_sources(
            SKILLS_ROOT, workspace["root_path"] if workspace else None
        )
    }
    installed_experts = {
        row["id"] for row in store.all("experts", "installed=1 AND enabled=1")
    }
    invalid_skills = [
        item
        for item in skill_ids
        if item not in available_skills
        or (
            available_skills[item]["scope"] == "app_global"
            and item not in enabled_skills
        )
    ]
    invalid_experts = [item for item in expert_ids if item not in installed_experts]
    if invalid_skills:
        raise HTTPException(400, "所选技能未安装或已停用，请刷新后重试")
    if invalid_experts:
        raise HTTPException(400, "所选专家未安装或已停用，请刷新后重试")
    updated = store.update(
        "tasks",
        "id",
        task_id,
        {
            "selected_skill_ids": json.dumps(skill_ids, ensure_ascii=False),
            "selected_expert_ids": json.dumps(expert_ids, ensure_ascii=False),
            "updated_at": now(),
        },
    )
    return task_row(updated or task)


@router.get("/api/tasks/{task_id}/messages")
async def get_messages(task_id: str):
    if not store.one("tasks", "id=?", (task_id,)):
        raise HTTPException(404, "task not found")
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "type": row["message_type"],
            "metadata": json.loads(row["metadata"] or "{}"),
        }
        for row in store.messages(task_id, include_compressed=True)
    ]


@router.get("/api/models", response_model=list[ModelConfig])
async def list_models():
    return [model_row(row) for row in store.all("models", "1=1 ORDER BY name")]


@router.post("/api/models", response_model=ModelConfig)
async def create_model(payload: ModelConfig):
    row = {
        key: value
        for key, value in payload.model_dump().items()
        if key not in {"supports_vision", "supports_image_generation", "supports_video_generation", "video_endpoint", "video_status_endpoint", "video_content_endpoint", "is_default"}
    }
    row.update(
        {
            "enabled": int(payload.enabled),
            "config": json.dumps(
                {
                    "supports_vision": payload.supports_vision,
                    "supports_image_generation": payload.supports_image_generation,
                    "supports_video_generation": payload.supports_video_generation,
                    "video_endpoint": payload.video_endpoint,
                    "video_status_endpoint": payload.video_status_endpoint,
                    "video_content_endpoint": payload.video_content_endpoint,
                    "capabilities": (
                        ["vision.input"] if payload.supports_vision else []
                    )
                    + (["image.generate"] if payload.supports_image_generation else [])
                    + (["video.generate"] if payload.supports_video_generation else []),
                }
            ),
        }
    )
    store.insert("models", row)
    return payload


@router.patch("/api/models/{model_id}", response_model=ModelConfig)
async def update_model(model_id: str, payload: ModelConfig):
    row = {
        key: value
        for key, value in payload.model_dump().items()
        if key not in {"supports_vision", "supports_image_generation", "supports_video_generation", "video_endpoint", "video_status_endpoint", "video_content_endpoint", "is_default"}
    }
    row.update(
        {
            "enabled": int(payload.enabled),
            "config": json.dumps(
                {
                    "supports_vision": payload.supports_vision,
                    "supports_image_generation": payload.supports_image_generation,
                    "supports_video_generation": payload.supports_video_generation,
                    "video_endpoint": payload.video_endpoint,
                    "video_status_endpoint": payload.video_status_endpoint,
                    "video_content_endpoint": payload.video_content_endpoint,
                    "capabilities": (
                        ["vision.input"] if payload.supports_vision else []
                    )
                    + (["image.generate"] if payload.supports_image_generation else [])
                    + (["video.generate"] if payload.supports_video_generation else []),
                }
            ),
        }
    )
    result = store.update("models", "id", model_id, row)
    if not result:
        store.insert("models", row)
    return payload


@router.post("/api/models/{model_id}/default")
async def make_default_model(model_id: str):
    model = store.one("models", "id=?", (model_id,))
    if not model:
        raise HTTPException(404, "模型不存在")
    set_default_model(model_id)
    return model_row(model)


@router.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    if model_id == "demo":
        raise HTTPException(400, "演示模型不能删除")
    was_default = default_model_id() == model_id
    store.delete("models", "id", model_id)
    if was_default:
        set_default_model(default_model_id())
    return {"ok": True}
