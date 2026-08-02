from __future__ import annotations

from fastapi import APIRouter
from ...core import *
from ...services.run_service import (
    agent_run_timeout_seconds,
    public_run,
    relevant_memories,
    sse,
)
from .memory import compact_task

router = APIRouter()


@router.post("/api/tasks/{task_id}/compact")
async def compact(task_id: str):
    if not store.one("tasks", "id=?", (task_id,)):
        raise HTTPException(404, "task not found")
    return compact_task(task_id)


TERMINAL_RUN_EVENTS = {"task.completed", "task.failed", "task.cancelled"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


def parse_sse_payload(chunk: str) -> dict[str, Any] | None:
    line = next(
        (item for item in chunk.splitlines() if item.startswith("data: ")), None
    )
    if not line:
        return None
    try:
        value = json.loads(line[6:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def publish_run_event(
    run_id: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Persist an event before broadcasting it, so reconnects never rely on memory only."""
    run = store.one("agent_runs", "id=?", (run_id,))
    if not run:
        return None
    event_type = str(payload.get("type") or "run.updated")
    event = store.add_run_event(run_id, event_type, payload, now())
    status_data: dict[str, Any] = {"last_heartbeat": now(), "updated_at": now()}
    if event_type == "task.started":
        status_data.update(
            {
                "status": "running",
                "current_step": "AgentScope 正在执行",
                "started_at": now(),
            }
        )
    elif event_type == "tool.approval_required":
        status_data.update(
            {"status": "waiting_for_approval", "current_step": "等待你的授权"}
        )
    elif event_type == "task.completed":
        status_data.update(
            {"status": "completed", "current_step": "已完成", "finished_at": now()}
        )
    elif event_type == "task.failed":
        status_data.update(
            {
                "status": "failed",
                "current_step": "执行失败",
                "error": str(payload.get("message") or ""),
                "finished_at": now(),
            }
        )
    elif event_type == "task.cancelled":
        status_data.update(
            {"status": "cancelled", "current_step": "已取消", "finished_at": now()}
        )
    elif event_type.startswith("tool."):
        log = payload.get("log") or {}
        status_data["current_step"] = str(log.get("name") or "正在调用工具")
    store.update("agent_runs", "id", run_id, status_data)
    for subscriber in list(run_subscribers.get(run_id, set())):
        subscriber.put_nowait(event)
    return event


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    row = store.one("agent_runs", "id=?", (run_id,))
    if not row:
        raise HTTPException(404, "Run 不存在")
    return public_run(row)


@router.get("/api/tasks/{task_id}/runs/latest")
async def get_latest_run(task_id: str):
    if not store.one("tasks", "id=?", (task_id,)):
        raise HTTPException(404, "task not found")
    row = store.one("agent_runs", "task_id=? ORDER BY created_at DESC", (task_id,))
    return public_run(row) if row else None


@router.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str, request: Request, after: int = 0):
    if not store.one("agent_runs", "id=?", (run_id,)):
        raise HTTPException(404, "Run 不存在")
    return StreamingResponse(
        run_event_stream(run_id, after=max(0, after), request=request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Run-Id": run_id},
    )


async def run_event_stream(
    run_id: str, after: int = 0, request: Request | None = None
) -> AsyncIterator[str]:
    if not store.one("agent_runs", "id=?", (run_id,)):
        return
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    run_subscribers.setdefault(run_id, set()).add(queue)
    cursor = max(0, after)
    try:
        while True:
            if request is not None and await request.is_disconnected():
                return
            replay = store.run_events(run_id, after=cursor)
            if replay:
                for event in replay:
                    cursor = max(cursor, int(event["sequence"]))
                    yield sse(event)
                    if event.get("type") in TERMINAL_RUN_EVENTS:
                        return
                continue
            run = store.one("agent_runs", "id=?", (run_id,))
            if not run:
                return
            if run.get("status") in TERMINAL_RUN_STATUSES:
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            sequence = int(event.get("sequence") or 0)
            if sequence <= cursor:
                continue
            cursor = sequence
            yield sse(event)
            if event.get("type") in TERMINAL_RUN_EVENTS:
                return
    finally:
        subscribers = run_subscribers.get(run_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                run_subscribers.pop(run_id, None)


async def consume_run(run_id: str, event_source: Any) -> None:
    terminal_seen = False
    try:
        async for chunk in event_source():
            payload = parse_sse_payload(chunk)
            if not payload:
                continue
            await publish_run_event(run_id, payload)
            terminal_seen = terminal_seen or payload.get("type") in TERMINAL_RUN_EVENTS
        if not terminal_seen:
            await publish_run_event(
                run_id,
                {
                    "type": "task.failed",
                    "task_id": store.one("agent_runs", "id=?", (run_id,))["task_id"],
                    "message": "执行器在返回最终状态前退出了",
                },
            )
    except asyncio.CancelledError:
        raise
    finally:
        run_tasks.pop(run_id, None)
        run = store.one("agent_runs", "id=?", (run_id,))
        if run:
            active_runs.pop(run["task_id"], None)


FILE_REFERENCE_PATTERN = re.compile(
    r"(?P<path>[A-Za-z0-9_\-./\\\u4e00-\u9fff()]+\.(?:docx|doc|pptx|ppt|pdf|xlsx))",
    re.IGNORECASE,
)
FILE_REFERENCE_WORDS = (
    "这个文件",
    "该文件",
    "此文件",
    "刚才提到",
    "刚才那个",
    "上面那个",
    "它的内容",
)


def task_conversation_context(task_id: str) -> str:
    """Build a bounded context window for a newly-created AgentScope Agent."""
    rows = store.messages(task_id, include_compressed=True)
    parts: list[str] = []
    summaries = store.all("summaries", "task_id=? ORDER BY created_at DESC", (task_id,))
    if summaries:
        try:
            summary = json.loads(summaries[0]["summary"])
        except (TypeError, json.JSONDecodeError):
            summary = summaries[0]["summary"]
        parts.append(f"最近一次会话压缩摘要：{json.dumps(summary, ensure_ascii=False)}")
    for row in rows[-8:]:
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        label = "用户" if row.get("role") == "user" else "助手"
        parts.append(f"{label}：{content[:3500]}")
        try:
            metadata = json.loads(row.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        for log in metadata.get("tool_logs", [])[-3:]:
            output = str(log.get("output") or "").strip()
            if output:
                parts.append(f"工具结果（{log.get('name', '工具')}）：{output[:1800]}")
    return "\n".join(parts)[-22_000:]


def infer_referenced_attachment(
    task_id: str, content: str, workspace_root: Path
) -> dict[str, str] | None:
    """Resolve an explicit document path or a follow-up like '分析这个文件'."""
    root = workspace_root.expanduser().resolve()
    direct_candidates = FILE_REFERENCE_PATTERN.findall(content)
    if direct_candidates:
        for raw_path in reversed(direct_candidates):
            possible_paths = [raw_path]
            for marker in ("根据", "参考", "查看", "分析", "读取", "打开", "请"):
                marker_index = raw_path.rfind(marker)
                if marker_index >= 0:
                    possible_paths.append(raw_path[marker_index + len(marker) :])
            for possible_path in possible_paths:
                relative_path = possible_path.replace("\\", "/").strip(
                    ".,;:，。；：）)】]"
                )
                candidate = (root / relative_path).resolve()
                if candidate.is_relative_to(root) and candidate.is_file():
                    return {
                        "path": candidate.relative_to(root).as_posix(),
                        "name": candidate.name,
                    }
    if not any(word in content for word in FILE_REFERENCE_WORDS):
        return None
    rows = store.messages(task_id, include_compressed=True)
    for row in reversed(rows[-12:]):
        candidates = FILE_REFERENCE_PATTERN.findall(str(row.get("content") or ""))
        try:
            metadata = json.loads(row.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        for log in metadata.get("tool_logs", []):
            candidates.extend(
                FILE_REFERENCE_PATTERN.findall(str(log.get("output") or ""))
            )
        for raw_path in reversed(candidates):
            relative_path = raw_path.replace("\\", "/").strip(".,;:，。；：）)】]")
            candidate = (root / relative_path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return {
                    "path": candidate.relative_to(root).as_posix(),
                    "name": candidate.name,
                }
    return None


async def demo_events(
    task: dict[str, Any],
    content: str,
    context: str,
    cancel_event: asyncio.Event | None = None,
    tool_logs: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    stamp = now()
    store.update(
        "tasks",
        "id",
        task["id"],
        {"status": "running", "current_state": "正在理解任务", "updated_at": stamp},
    )
    yield sse({"type": "task.started", "task_id": task["id"]})
    await asyncio.sleep(0.15)
    text = f"我已收到你的任务：{content}\n\n当前工作空间上下文已加载。{context}\n\n这是演示执行器；配置模型并设置 AGENTSCOPE_LIVE=1 后会调用 AgentScope。"
    for token in text:
        if cancel_event and cancel_event.is_set():
            store.update(
                "tasks",
                "id",
                task["id"],
                {"status": "cancelled", "current_state": "已取消", "updated_at": now()},
            )
            yield sse({"type": "task.cancelled", "task_id": task["id"]})
            return
        await asyncio.sleep(0.006)
        yield sse({"type": "assistant.delta", "content": token})
    store.add_message(
        task["id"], "assistant", text, now(), metadata={"tool_logs": tool_logs or []}
    )
    store.update(
        "tasks",
        "id",
        task["id"],
        {"status": "completed", "current_state": "已完成", "updated_at": now()},
    )
    yield sse({"type": "task.completed", "task_id": task["id"]})
