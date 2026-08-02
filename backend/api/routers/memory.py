from __future__ import annotations

from fastapi import APIRouter
from ...core import *

router = APIRouter()


@router.get("/api/memory")
async def list_memory(workspace_id: str | None = None):
    rows = store.all(
        "memories",
        "deleted_at IS NULL"
        + (" AND workspace_id=?" if workspace_id else "")
        + " ORDER BY updated_at DESC",
        (workspace_id,) if workspace_id else (),
    )
    return rows


@router.post("/api/memory")
async def create_memory(payload: MemoryRequest):
    stamp = now()
    row = {
        "id": uuid.uuid4().hex,
        **payload.model_dump(),
        "created_at": stamp,
        "updated_at": stamp,
        "deleted_at": None,
    }
    store.insert("memories", row)
    return row


@router.patch("/api/memory/{memory_id}")
async def update_memory(memory_id: str, payload: dict[str, Any]):
    row = store.update(
        "memories",
        "id",
        memory_id,
        {
            "content": payload.get("content", ""),
            "category": payload.get("category", "preference"),
            "updated_at": now(),
        },
    )
    if not row:
        raise HTTPException(404, "memory not found")
    return row


@router.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: str):
    store.update("memories", "id", memory_id, {"deleted_at": now()})
    return {"ok": True}


def compact_task(task_id: str) -> dict[str, Any]:
    rows = store.messages(task_id, include_compressed=True)
    if len(rows) < 6:
        return {"compressed": False, "reason": "消息数量未达到压缩阈值"}
    recent = rows[-4:]
    old = rows[:-4]
    users = [row["content"] for row in old if row["role"] == "user"][-3:]
    assistants = [row["content"] for row in old if row["role"] == "assistant"][-3:]
    summary = {
        "task_overview": users[0] if users else "",
        "current_state": "已保留最近 4 条消息",
        "important_discoveries": assistants[-1][:800] if assistants else "",
        "decisions": [],
        "next_steps": ["继续当前任务"],
        "context_to_preserve": users[-2:],
    }
    summary_id = uuid.uuid4().hex
    store.insert(
        "summaries",
        {
            "id": summary_id,
            "task_id": task_id,
            "summary": json.dumps(summary, ensure_ascii=False),
            "created_at": now(),
        },
    )
    with store.connect() as db:
        db.execute(
            f"UPDATE messages SET compressed=1 WHERE task_id=? AND id IN ({','.join('?' for _ in old)})",
            (task_id, *(row["id"] for row in old)),
        )
    return {"compressed": True, "summary": summary}
