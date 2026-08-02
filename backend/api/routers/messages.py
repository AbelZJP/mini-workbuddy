from __future__ import annotations

import os

from fastapi import APIRouter
from ...core import *
from ...expert_team import run_expert_team
from ...services.task_service import task_row, task_title_from_message

from .memory import compact_task
from .runs import *

router = APIRouter()


@router.post("/api/tasks/{task_id}/messages")
async def send_message(task_id: str, payload: MessageRequest, request: Request):
    task = store.one("tasks", "id=?", (task_id,))
    if not task:
        raise HTTPException(404, "task not found")
    if task["workspace_id"] != payload.workspace_id:
        raise HTTPException(409, "当前会话不属于所选工作空间，请先切换到该空间下的会话")
    workspace_for_request = store.one("workspaces", "id=?", (payload.workspace_id,))
    if not workspace_for_request:
        raise HTTPException(404, "工作空间不存在")
    previous_conversation = task_conversation_context(task_id)
    inferred_attachment = infer_referenced_attachment(
        task_id,
        payload.content,
        Path(workspace_for_request["root_path"]),
    )
    attachments = list(payload.attachments)
    known_paths = {str(item.get("path") or "") for item in attachments}
    if inferred_attachment and inferred_attachment["path"] not in known_paths:
        attachments.append(inferred_attachment)
    attachment_text, attachment_metadata = parse_attachments(
        Path(workspace_for_request["root_path"]),
        attachments,
    )
    runtime_content = payload.content
    if attachment_text:
        runtime_content += (
            "\n\n以下是本次任务附件的解析文本，仅用于回答当前问题；"
            "如果附件是扫描件或图片型文档，请说明需要 OCR 或视觉模型：\n"
            f"<attachments>\n{attachment_text}\n</attachments>"
        )
    store.update(
        "tasks",
        "id",
        task_id,
        {
            "permission_mode": payload.permission_mode,
            "model_id": payload.model_id,
            "updated_at": now(),
        },
    )
    store.add_message(
        task_id,
        "user",
        payload.content,
        now(),
        metadata={"attachments": attachment_metadata},
    )
    if task.get("title") == "新任务":
        generated_title = task_title_from_message(payload.content)
        if generated_title != "新任务":
            task = (
                store.update(
                    "tasks",
                    "id",
                    task_id,
                    {"title": generated_title, "updated_at": now()},
                )
                or task
            )
    if re.search(r"记住|请记得|我喜欢|我的偏好|我的习惯", payload.content):
        stamp = now()
        store.insert(
            "memories",
            {
                "id": uuid.uuid4().hex,
                "workspace_id": payload.workspace_id,
                "category": "user_preference",
                "content": payload.content,
                "source_task_id": task_id,
                "confidence": 0.85,
                "created_at": stamp,
                "updated_at": stamp,
                "deleted_at": None,
            },
        )
    task_capabilities = task_row(task)
    memories = relevant_memories(payload.workspace_id, payload.content)
    enabled_skill_ids = {row["id"] for row in store.all("skills", "enabled=1")}
    skill_rows = resolve_selected_skills(
        task_capabilities.selected_skill_ids,
        SKILLS_ROOT,
        workspace_for_request["root_path"],
        enabled_global_ids=enabled_skill_ids,
    )
    installed_experts = {
        row["id"]: row for row in store.all("experts", "installed=1 AND enabled=1")
    }
    expert_rows = [
        installed_experts[item]
        for item in task_capabilities.selected_expert_ids
        if item in installed_experts
    ]
    expert_sections = selected_expert_prompt_sections(
        task_capabilities.selected_expert_ids
    )
    expert_team_mode = (
        len(expert_sections) >= 2
        and os.getenv("AGENTSCOPE_LIVE", "0") == "1"
        and payload.model_id != "demo"
    )
    context = (
        ("相关记忆：" + "；".join(row["content"] for row in memories))
        if memories
        else "暂无相关长期记忆。"
    )
    if previous_conversation:
        context += (
            f"\n前序会话上下文（用于解析“这个文件”等指代）：\n{previous_conversation}"
        )
    if inferred_attachment:
        context += f"\n已根据前序会话解析出本轮指代文件：{inferred_attachment['path']}。请优先读取或分析该文件，不要重新遍历整个工作空间。"
    if skill_rows:
        context += f" 已选择 Skills：{', '.join(row['name'] for row in skill_rows)}。"
    if expert_rows:
        context += f" 已选择专家：{', '.join(row['name'] for row in expert_rows)}。"
    if len(store.messages(task_id)) >= 8:
        compact_task(task_id)
    previous_run_id = active_runs.get(task_id)
    if previous_run_id:
        previous_run = store.one("agent_runs", "id=?", (previous_run_id,))
        if previous_run and previous_run.get("status") not in TERMINAL_RUN_STATUSES:
            raise HTTPException(409, "当前任务已有正在执行的 Run，请等待完成或先停止它")
    run_id = uuid.uuid4().hex
    stamp = now()
    reference_file = ""
    if attachment_text and any(
        item.get("status") == "parsed" for item in attachment_metadata
    ):
        reference_relative = Path(
            ".mini-workbuddy", "run-inputs", f"{run_id}-reference.txt"
        )
        reference_target = (
            Path(workspace_for_request["root_path"]).expanduser().resolve()
            / reference_relative
        ).resolve()
        try:
            reference_target.parent.mkdir(parents=True, exist_ok=True)
            reference_target.write_text(attachment_text, encoding="utf-8")
            reference_file = reference_relative.as_posix()
        except OSError:
            # The parsed attachment is still injected into runtime_content;
            # failure to create the optional script input must not lose it.
            reference_file = ""
    run_spec = {
        "content": payload.content,
        "runtime_content": runtime_content,
        "workspace_id": payload.workspace_id,
        "permission_mode": payload.permission_mode,
        "model_id": payload.model_id,
        "attachments": attachments,
        "context": context,
        "selected_skill_ids": task_capabilities.selected_skill_ids,
        "selected_expert_ids": task_capabilities.selected_expert_ids,
        "expert_mode": "team" if expert_team_mode else "single",
        "reference_file": reference_file,
    }
    store.insert(
        "agent_runs",
        {
            "id": run_id,
            "task_id": task_id,
            "status": "queued",
            "current_step": "排队等待执行",
            "model_id": payload.model_id,
            "permission_mode": payload.permission_mode,
            "spec": json.dumps(run_spec, ensure_ascii=False),
            "error": "",
            "cancel_requested": 0,
            "started_at": None,
            "finished_at": None,
            "last_heartbeat": stamp,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    active_runs[task_id] = run_id
    cancel_event = asyncio.Event()
    cancel_events[task_id] = cancel_event
    approval_queues[task_id] = asyncio.Queue()

    async def events() -> AsyncIterator[str]:
        tool_logs: list[dict[str, Any]] = []

        def merge_tool_log(log: dict[str, Any]) -> dict[str, Any]:
            log_id = str(log.get("id") or log.get("name") or uuid.uuid4().hex)
            normalized = {**log, "id": log_id}
            for index, current in enumerate(tool_logs):
                if str(current.get("id")) == log_id:
                    tool_logs[index] = {**current, **normalized}
                    return tool_logs[index]
            tool_logs.append(normalized)
            return normalized

        try:
            for attachment in attachment_metadata:
                if attachment.get("status") not in {"parsed", "failed"}:
                    continue
                status = (
                    "completed" if attachment.get("status") == "parsed" else "failed"
                )
                output = (
                    f"后端已解析 {attachment.get('format', '文档')}，解析结果已注入本次任务上下文。"
                    if status == "completed"
                    else str(attachment.get("error") or "文档解析失败")
                )
                log = {
                    "id": f"document:{attachment.get('path', '')}",
                    "name": f"解析文档：{attachment.get('name', attachment.get('path', ''))}",
                    "kind": "tool",
                    "status": status,
                    "input": attachment.get("path", ""),
                    "output": output,
                }
                yield sse({"type": "tool.completed", "log": merge_tool_log(log)})
            model = store.one("models", "id=?", (payload.model_id,)) or store.one(
                "models", "id=?", ("demo",)
            )
            workspace = store.one("workspaces", "id=?", (payload.workspace_id,))
            mcp_rows = [
                store.json_config(row, ("args", "allowed_tools", "env", "headers"))
                for row in store.all("mcp_servers", "enabled=1")
            ]
            live_text: str | None = None
            failure = ""
            live_result: tuple[str, list[dict[str, Any]]] | None = None
            if model:
                store.update(
                    "tasks",
                    "id",
                    task_id,
                    {
                        "status": "running",
                        "current_state": "AgentScope 正在执行",
                        "updated_at": now(),
                    },
                )
                yield sse({"type": "task.started", "task_id": task_id})
                runtime_context = context
                runtime_expert_prompt = (
                    selected_expert_prompt(task_capabilities.selected_expert_ids)
                    if not expert_team_mode
                    else ""
                )
                if expert_team_mode:
                    for expert in expert_sections:
                        yield sse(
                            {
                                "type": "tool.started",
                                "log": merge_tool_log(
                                    {
                                        "id": f"expert:{expert['id']}",
                                        "name": f"专家分析：{expert['name']}",
                                        "kind": "expert",
                                        "status": "running",
                                        "input": payload.content,
                                        "output": "",
                                    }
                                ),
                            }
                        )
                    try:
                        expert_results = await asyncio.wait_for(
                            run_expert_team(
                                model,
                                runtime_content,
                                context,
                                expert_sections,
                            ),
                            timeout=min(agent_run_timeout_seconds(), 600),
                        )
                    except asyncio.TimeoutError:
                        expert_results = [
                            {
                                "id": expert["id"],
                                "name": expert["name"],
                                "status": "failed",
                                "output": "专家 Worker 执行超过 600 秒，已停止本轮专家分析。",
                            }
                            for expert in expert_sections
                        ]
                    result_sections = []
                    for result in expert_results:
                        log = merge_tool_log(
                            {
                                "id": f"expert:{result['id']}",
                                "name": f"专家分析：{result['name']}",
                                "kind": "expert",
                                "status": result["status"],
                                "input": payload.content,
                                "output": result["output"],
                            }
                        )
                        yield sse({"type": "tool.completed", "log": log})
                        result_sections.append(
                            f"## {result['name']}（{result['status']}）\n{result['output']}"
                        )
                    team_context = (
                        "\n\n本轮专家团已分别完成分析。你是最终协调 Agent，"
                        "请综合以下结果回答用户；不要重新输出专家 Prompt，也不要把彼此冲突的建议当成已确认事实。\n"
                        "<expert_team_results>\n"
                        + "\n\n".join(result_sections)
                        + "\n</expert_team_results>"
                    )
                    runtime_context += team_context[:24000]
                runtime_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                live_task = asyncio.create_task(
                    run_agentscope(
                        model,
                        runtime_content,
                        runtime_context,
                        build_skill_prompt(
                            ROOT / "skills",
                            {row["id"] for row in skill_rows},
                            workspace_root=workspace["root_path"]
                            if workspace
                            else None,
                        ),
                        runtime_expert_prompt,
                        mcp_rows,
                        workspace_root=workspace["root_path"] if workspace else "",
                        permission_mode=payload.permission_mode,
                        event_queue=runtime_events,
                        approval_queue=approval_queues[task_id],
                        skill_dirs=[
                            str(Path(row["root_path"]).resolve()) for row in skill_rows
                        ],
                        skill_script_roots={
                            row["id"]: str(Path(row["root_path"]).resolve())
                            for row in skill_rows
                        },
                        reference_file=reference_file,
                        capability_store=store,
                    )
                )
                timeout_seconds = agent_run_timeout_seconds()
                deadline = asyncio.get_running_loop().time() + timeout_seconds
                while not live_task.done():
                    if cancel_event.is_set():
                        live_task.cancel()
                        await asyncio.gather(live_task, return_exceptions=True)
                        store.update(
                            "tasks",
                            "id",
                            task_id,
                            {
                                "status": "cancelled",
                                "current_state": "已取消",
                                "updated_at": now(),
                            },
                        )
                        yield sse({"type": "task.cancelled", "task_id": task_id})
                        return
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        live_task.cancel()
                        await asyncio.gather(live_task, return_exceptions=True)
                        failure = f"AgentScope 执行超过 {timeout_seconds} 秒，已自动停止。后台 Run 已保留，可检查模型配置、网络和工具调用日志后重试。"
                        break
                    try:
                        runtime_event = await asyncio.wait_for(
                            runtime_events.get(), timeout=min(0.25, remaining)
                        )
                    except asyncio.TimeoutError:
                        continue
                    event_type = runtime_event.get("type", "tool.updated")
                    if event_type == "tool.approval_required":
                        store.update(
                            "tasks",
                            "id",
                            task_id,
                            {
                                "status": "waiting_for_approval",
                                "current_state": "等待你的授权",
                                "updated_at": now(),
                            },
                        )
                        yield sse(runtime_event)
                    elif event_type == "tool.external_required":
                        yield sse(runtime_event)
                    else:
                        log = merge_tool_log(runtime_event.get("log") or {})
                        yield sse({"type": event_type, "log": log})
                if live_task.done() and not failure:
                    live_result = await live_task
                    while not runtime_events.empty():
                        runtime_event = runtime_events.get_nowait()
                        event_type = runtime_event.get("type", "tool.updated")
                        if event_type in {
                            "tool.approval_required",
                            "tool.external_required",
                        }:
                            yield sse(runtime_event)
                        else:
                            log = merge_tool_log(runtime_event.get("log") or {})
                            yield sse({"type": event_type, "log": log})
                    if live_result:
                        live_text, runtime_logs = live_result
                        for runtime_log in runtime_logs:
                            merge_tool_log(runtime_log)
            else:
                live_text = None
            if live_text is None:
                if failure:
                    text = failure
                    store.update(
                        "tasks",
                        "id",
                        task_id,
                        {
                            "status": "failed",
                            "current_state": "执行失败",
                            "updated_at": now(),
                        },
                    )
                    yield sse({"type": "task.started", "task_id": task_id})
                    for token in text:
                        yield sse({"type": "assistant.delta", "content": token})
                    yield sse({"type": "task.failed", "task_id": task_id})
                    return
                async for event in demo_events(
                    task, runtime_content, context, cancel_event, tool_logs
                ):
                    yield event
                return
            for token in live_text:
                if cancel_event.is_set():
                    store.update(
                        "tasks",
                        "id",
                        task_id,
                        {
                            "status": "cancelled",
                            "current_state": "已取消",
                            "updated_at": now(),
                        },
                    )
                    yield sse({"type": "task.cancelled", "task_id": task_id})
                    return
                await asyncio.sleep(0.004)
                yield sse({"type": "assistant.delta", "content": token})
            store.add_message(
                task_id,
                "assistant",
                live_text,
                now(),
                metadata={"tool_logs": tool_logs},
            )
            store.update(
                "tasks",
                "id",
                task_id,
                {"status": "completed", "current_state": "已完成", "updated_at": now()},
            )
            register_task_artifacts(
                task_id, workspace_for_request["root_path"], tool_logs
            )
            yield sse({"type": "task.completed", "task_id": task_id})
        except Exception as exc:
            error_text = str(exc)
            if (
                "503" in error_text
                or "service_unavailable" in error_text.lower()
                or "too busy" in error_text.lower()
            ):
                error_text = "DeepSeek 当前返回 503（服务繁忙）。模型配置和工作空间文件工具已正常进入执行链，请稍后重试；如果持续出现，请在设置中切换备用模型。"
            elif (
                "image_url" in error_text
                or "图片" in error_text
                and "400" in error_text
            ):
                error_text = "当前模型不接受图片输入，因此无法直接查看这张图片。请在模型设置中勾选“支持图片理解”并使用视觉模型，或切换到支持图片的模型后重试。"
            elif (
                "Missing credentials" in error_text
                or "未读取到环境变量" in error_text
                or "没有配置 API Key" in error_text
            ):
                error_text = error_text.replace(
                    "Missing credentials. Please pass an `api_key`, `workload_identity`, `admin_api_key`, or set the `OPENAI_API_KEY` or `OPENAI_ADMIN_KEY` environment variable.",
                    "模型没有读取到 API Key。请检查模型配置中的 API Key 环境变量名称是否与项目 .env 完全一致，并重启后端后重试。",
                )
            store.update(
                "tasks",
                "id",
                task_id,
                {"status": "failed", "current_state": "执行失败", "updated_at": now()},
            )
            yield f"data: {json.dumps({'type': 'assistant.delta', 'content': f'执行失败：{error_text}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'task.failed', 'task_id': task_id}, ensure_ascii=False)}\n\n"
        finally:
            cancel_events.pop(task_id, None)
            approval_queues.pop(task_id, None)

    await publish_run_event(
        run_id, {"type": "run.started", "task_id": task_id, "run_id": run_id}
    )
    producer = asyncio.create_task(consume_run(run_id, events))
    run_tasks[run_id] = producer
    return StreamingResponse(
        run_event_stream(run_id, request=request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Run-Id": run_id},
    )


@router.post("/api/tasks/{task_id}/approvals/{approval_id:path}")
async def resolve_approval(task_id: str, approval_id: str, payload: ApprovalDecision):
    queue = approval_queues.get(task_id)
    if queue is None:
        raise HTTPException(409, "当前任务没有等待中的授权请求，可能已经结束或已取消")
    await queue.put({"approval_id": approval_id, "approved": payload.approved})
    store.update(
        "tasks",
        "id",
        task_id,
        {
            "status": "running",
            "current_state": "AgentScope 正在执行",
            "updated_at": now(),
        },
    )
    run_id = active_runs.get(task_id)
    if run_id:
        store.update(
            "agent_runs",
            "id",
            run_id,
            {
                "status": "running",
                "current_step": "AgentScope 正在执行",
                "updated_at": now(),
                "last_heartbeat": now(),
            },
        )
    return {"ok": True, "approved": payload.approved}


async def cancel_run(run_id: str) -> dict[str, Any]:
    run = store.one("agent_runs", "id=?", (run_id,))
    if not run:
        raise HTTPException(404, "Run 不存在")
    task_id = run["task_id"]
    if task_id in cancel_events:
        cancel_events[task_id].set()
    stamp = now()
    store.update(
        "agent_runs",
        "id",
        run_id,
        {
            "status": "cancelled",
            "current_step": "已取消",
            "cancel_requested": 1,
            "finished_at": stamp,
            "last_heartbeat": stamp,
            "updated_at": stamp,
        },
    )
    store.update(
        "tasks",
        "id",
        task_id,
        {"status": "cancelled", "current_state": "已取消", "updated_at": stamp},
    )
    await publish_run_event(
        run_id, {"type": "task.cancelled", "task_id": task_id, "message": "任务已停止"}
    )
    producer = run_tasks.get(run_id)
    if producer and not producer.done():
        producer.cancel()
    return public_run(store.one("agent_runs", "id=?", (run_id,)) or run)


@router.post("/api/runs/{run_id}/cancel")
async def cancel_run_endpoint(run_id: str):
    return await cancel_run(run_id)


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if not store.one("tasks", "id=?", (task_id,)):
        raise HTTPException(404, "task not found")
    run_id = active_runs.get(task_id)
    if run_id:
        await cancel_run(run_id)
    else:
        if task_id in cancel_events:
            cancel_events[task_id].set()
        row = store.update(
            "tasks",
            "id",
            task_id,
            {"status": "cancelled", "current_state": "已取消", "updated_at": now()},
        )
        return task_row(row)
    return task_row(store.one("tasks", "id=?", (task_id,)))
