from __future__ import annotations

import json
import asyncio
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

from ...core import ROOT, now, store, uuid
from ...capability_executor import generate_image, generate_video
from ...model_router import model_config
from ...schemas import (
    CanvasPolishRequest,
    CanvasGraph,
    CanvasContextResponse,
    CanvasGenerateRequest,
    CanvasProject,
    CreateCanvasProject,
    UpdateCanvasProject,
)

router = APIRouter()
ALLOWED_NODE_TYPES = {"text", "image-upload", "ai-image", "video-upload", "ai-video", "note"}


def _polish_text(model: dict[str, Any], content: str) -> str:
    load_dotenv(ROOT / ".env", override=True)
    api_key_env = str(model.get("api_key_env") or "")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    if not api_key:
        raise HTTPException(400, "所选模型没有可用的 API Key")
    config = model_config(model)
    base_url = str(model.get("base_url") or config.get("base_url") or "https://api.openai.com/v1")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": model.get("model"),
            "messages": [
                {"role": "system", "content": "你是中文文字润化助手。保留原意，优化表达、结构和画面感，只输出润化后的正文，不要解释。"},
                {"role": "user", "content": content},
            ],
            "temperature": 0.5,
        }).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:600]
        raise HTTPException(502, f"文字润化请求失败（HTTP {exc.code}）：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(502, f"文字润化请求失败：{exc}") from exc
    try:
        result = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "模型没有返回可用的润化文本") from exc
    if not isinstance(result, str) or not result.strip():
        raise HTTPException(502, "模型返回的润化文本为空")
    return result.strip()


def _validate_graph(graph: CanvasGraph) -> None:
    if len(graph.nodes) > 300 or len(graph.edges) > 1000:
        raise HTTPException(400, "画布规模超过限制")
    node_ids: set[str] = set()
    for node in graph.nodes:
        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        position = node.get("position")
        if not node_id or node_id in node_ids:
            raise HTTPException(400, "画布节点 ID 无效或重复")
        if node_type not in ALLOWED_NODE_TYPES:
            raise HTTPException(400, "画布包含不支持的节点类型")
        if not isinstance(position, dict) or not isinstance(position.get("x"), (int, float)) or not isinstance(position.get("y"), (int, float)):
            raise HTTPException(400, "画布节点位置无效")
        node_ids.add(node_id)

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    seen_edges: set[tuple[str, str]] = set()
    for edge in graph.edges:
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        pair = (source, target)
        if source not in node_ids or target not in node_ids or source == target or pair in seen_edges:
            raise HTTPException(400, "画布连线无效、重复或形成自连接")
        seen_edges.add(pair)
        adjacency[source].append(target)

    def visit(current: str, path: set[str]) -> bool:
        if current in path:
            return True
        return any(visit(next_node, path | {current}) for next_node in adjacency[current])

    if any(visit(node_id, set()) for node_id in node_ids):
        raise HTTPException(400, "画布连线不能形成环路")


def _graph_from_row(row: dict[str, Any]) -> CanvasGraph:
    try:
        value = json.loads(row.get("graph_json") or "{}")
        return CanvasGraph.model_validate(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return CanvasGraph()


def _project_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "graph": _graph_from_row(row).model_dump(),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _node_reference_content(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    for key in ("content", "prompt", "filePath", "fileName"):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_node_context(graph: CanvasGraph, node_id: str) -> dict[str, Any]:
    nodes = {str(node.get("id")): node for node in graph.nodes}
    if node_id not in nodes:
        raise HTTPException(404, "目标节点不存在")
    direct_sources = {
        str(edge.get("source"))
        for edge in graph.edges
        if str(edge.get("target")) == node_id
    }
    references: list[dict[str, str]] = []
    for source_id, node in nodes.items():
        if source_id == node_id:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        scope = str(config.get("scope") or "direct")
        applies = scope == "global" or (scope == "direct" and source_id in direct_sources)
        content = _node_reference_content(node)
        if applies and content:
            title = str(data.get("title") or node.get("type") or "节点")
            references.append({
                "source_node_id": source_id,
                "scope": scope if scope in {"direct", "global"} else "direct",
                "title": title,
                "content": content,
            })
    context = "\n\n".join(
        f"[{item['title']} · {item['scope']}]\n{item['content']}"
        for item in references
    )
    return {"node_id": node_id, "references": references, "context": context}


@router.get("/api/canvas/projects", response_model=list[CanvasProject])
async def list_canvas_projects(workspace_id: str = Query(min_length=1)):
    if not store.one("workspaces", "id=?", (workspace_id,)):
        raise HTTPException(404, "工作空间不存在")
    rows = store.all("canvas_projects", "workspace_id=? ORDER BY updated_at DESC", (workspace_id,))
    return [_project_row(row) for row in rows]


@router.post("/api/canvas/projects", response_model=CanvasProject)
async def create_canvas_project(payload: CreateCanvasProject):
    if not store.one("workspaces", "id=?", (payload.workspace_id,)):
        raise HTTPException(404, "工作空间不存在")
    _validate_graph(payload.graph)
    stamp = now()
    row = {
        "id": uuid.uuid4().hex[:12],
        "workspace_id": payload.workspace_id,
        "name": payload.name.strip() or "未命名项目",
        "graph_json": json.dumps(payload.graph.model_dump(), ensure_ascii=False),
        "created_at": stamp,
        "updated_at": stamp,
    }
    store.insert("canvas_projects", row)
    return _project_row(row)


@router.get("/api/canvas/projects/{project_id}", response_model=CanvasProject)
async def get_canvas_project(project_id: str):
    row = store.one("canvas_projects", "id=?", (project_id,))
    if not row:
        raise HTTPException(404, "画布项目不存在")
    return _project_row(row)


@router.get(
    "/api/canvas/projects/{project_id}/nodes/{node_id}/context",
    response_model=CanvasContextResponse,
)
async def get_canvas_node_context(project_id: str, node_id: str):
    row = store.one("canvas_projects", "id=?", (project_id,))
    if not row:
        raise HTTPException(404, "画布项目不存在")
    return _resolve_node_context(_graph_from_row(row), node_id)


@router.patch("/api/canvas/projects/{project_id}", response_model=CanvasProject)
async def update_canvas_project(project_id: str, payload: UpdateCanvasProject):
    current = store.one("canvas_projects", "id=?", (project_id,))
    if not current:
        raise HTTPException(404, "画布项目不存在")
    graph = payload.graph or _graph_from_row(current)
    _validate_graph(graph)
    name = payload.name.strip() if payload.name is not None else current["name"]
    updated = store.update(
        "canvas_projects",
        "id",
        project_id,
        {
            "name": name or "未命名项目",
            "graph_json": json.dumps(graph.model_dump(), ensure_ascii=False),
            "updated_at": now(),
        },
    )
    return _project_row(updated or current)


def _image_size(ratio: str) -> str:
    return {
        "1:1": "2048x2048",
        "4:3": "2304x1728",
        "3:4": "1728x2304",
        "16:9": "2560x1440",
        "9:16": "1440x2560",
    }.get(ratio, "2048x2048")


@router.post("/api/canvas/projects/{project_id}/nodes/{node_id}/generate")
async def generate_canvas_node(
    project_id: str,
    node_id: str,
    payload: CanvasGenerateRequest,
):
    current = store.one("canvas_projects", "id=?", (project_id,))
    if not current:
        raise HTTPException(404, "画布项目不存在")
    workspace = store.one("workspaces", "id=?", (current["workspace_id"],))
    if not workspace:
        raise HTTPException(404, "工作空间不存在")
    graph = _graph_from_row(current)
    node = next((item for item in graph.nodes if str(item.get("id")) == node_id), None)
    if not node:
        raise HTTPException(404, "目标节点不存在")
    node_type = str(node.get("type") or "")
    if node_type not in {"ai-image", "ai-video"}:
        raise HTTPException(400, "只有 AI 图片和 AI 视频节点可以生成产物")
    context = _resolve_node_context(graph, node_id)["context"]
    prompt = payload.prompt.strip()
    if context:
        prompt = f"{prompt}\n\n参考上下文：\n{context}"
    output_filename = f"canvas-{node_type}-{uuid.uuid4().hex[:12]}"
    if node_type == "ai-image":
        result = await generate_image(
            store,
            workspace["root_path"],
            prompt,
            size=_image_size(payload.ratio),
            output_filename=output_filename + ".png",
            preferred_model_id=payload.model_id,
        )
        content_type = "image/png"
    else:
        result = await generate_video(
            store,
            workspace["root_path"],
            prompt,
            ratio=payload.ratio,
            duration=payload.duration,
            resolution=payload.resolution,
            audio=payload.audio,
            output_filename=output_filename + ".mp4",
            preferred_model_id=payload.model_id,
        )
        content_type = "video/mp4"
    if not result.get("ok"):
        raise HTTPException(502, str(result.get("message") or "媒体生成失败"))
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    config = {
        **config,
        "prompt": payload.prompt.strip(),
        "model": payload.model_id or str(result.get("model_id") or config.get("model") or ""),
        "ratio": payload.ratio,
        "duration": payload.duration,
        "resolution": payload.resolution,
        "audio": payload.audio,
        "outputPath": result["artifact_path"],
        "outputFileName": Path(result["artifact_path"]).name,
        "outputContentType": content_type,
    }
    node["data"] = {**data, "config": config, "status": "success"}
    graph_payload = graph.model_dump()
    updated = store.update(
        "canvas_projects",
        "id",
        project_id,
        {
            "graph_json": json.dumps(graph_payload, ensure_ascii=False),
            "updated_at": now(),
        },
    )
    return {
        **result,
        "node_id": node_id,
        "content_type": content_type,
        "project": _project_row(updated or current),
    }


@router.delete("/api/canvas/projects/{project_id}")
async def delete_canvas_project(project_id: str):
    if not store.one("canvas_projects", "id=?", (project_id,)):
        raise HTTPException(404, "画布项目不存在")
    store.delete("canvas_projects", "id", project_id)
    return {"ok": True}


@router.post("/api/canvas/polish")
async def polish_canvas_text(payload: CanvasPolishRequest):
    model = store.one("models", "id=? AND enabled=1", (payload.model_id,)) if payload.model_id else None
    if not model:
        model = next(iter(store.all("models", "enabled=1 ORDER BY name")), None)
    if not model:
        raise HTTPException(400, "没有可用的文本模型，请先在设置中配置模型")
    content = await asyncio.to_thread(_polish_text, model, payload.content.strip())
    return {"content": content, "model_id": model["id"]}
