from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import HTTPException

from .api.routers import canvas
from .api.routers.canvas import (
    _image_size,
    _image_reference_paths,
    _graph_from_row,
    _project_row,
    _resolve_node_context,
    _validate_graph,
    _video_first_frame_path,
)
from .schemas import CanvasGenerateRequest, CanvasGraph, CreateCanvasProject
from .storage import Store


class CanvasPersistenceTests(unittest.TestCase):
    def test_graph_accepts_voice_clone_node(self) -> None:
        """Rejecting this node type would make a newly added canvas node impossible to save."""
        graph = CanvasGraph(
            nodes=[
                {
                    "id": "voice",
                    "type": "voice-clone",
                    "position": {"x": 0, "y": 0},
                    "data": {"config": {"filePath": "uploads/reference.wav"}},
                }
            ]
        )
        try:
            _validate_graph(graph)
        except HTTPException as exc:
            self.fail(f"声音克隆节点不应被图校验拒绝：{exc.detail}")

    def test_voice_clone_node_generates_and_persists_audio_output(self) -> None:
        """Dropping the node's reference audio or output metadata would break playback after reload."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "canvas.sqlite3")
            store.insert("workspaces", {
                "id": "workspace",
                "name": "测试空间",
                "root_path": temp_dir,
                "description": "",
                "created_at": "2026-08-07",
                "updated_at": "2026-08-07",
            })
            graph = CanvasGraph(nodes=[{
                "id": "voice",
                "type": "voice-clone",
                "position": {"x": 0, "y": 0},
                "data": {"config": {"filePath": "uploads/reference.wav", "model": "minimax"}},
            }])
            store.insert("canvas_projects", {
                "id": "project",
                "workspace_id": "workspace",
                "name": "测试画布",
                "graph_json": json.dumps(graph.model_dump(), ensure_ascii=False),
                "created_at": "2026-08-07",
                "updated_at": "2026-08-07",
            })
            call: dict[str, str] = {}

            async def fake_generate_voice_clone(_store, workspace_root, reference_audio_path, text, **kwargs):
                call.update({
                    "workspace_root": workspace_root,
                    "reference_audio_path": reference_audio_path,
                    "text": text,
                    "model_id": kwargs["preferred_model_id"],
                })
                return {"ok": True, "artifact_path": "outputs/voice.mp3", "model_id": "minimax"}

            with patch.object(canvas, "store", store), patch.object(canvas, "generate_voice_clone", side_effect=fake_generate_voice_clone):
                try:
                    result = asyncio.run(canvas.generate_canvas_node(
                        "project", "voice", CanvasGenerateRequest(prompt="你好，欢迎使用声音克隆。", model_id="minimax"),
                    ))
                except HTTPException as exc:
                    self.fail(f"声音克隆节点不应被生成接口拒绝：{exc.detail}")
            self.assertEqual(call, {
                "workspace_root": temp_dir,
                "reference_audio_path": "uploads/reference.wav",
                "text": "你好，欢迎使用声音克隆。",
                "model_id": "minimax",
            })
            self.assertEqual(result["content_type"], "audio/mpeg")
            saved = _graph_from_row(store.one("canvas_projects", "id=?", ("project",)))
            config = saved.nodes[0]["data"]["config"]
            self.assertEqual(config["outputPath"], "outputs/voice.mp3")
            self.assertEqual(config["outputContentType"], "audio/mpeg")

    def test_image_ratio_maps_to_supported_2k_dimensions(self) -> None:
        self.assertEqual(_image_size("1:1"), "2048x2048")
        self.assertEqual(_image_size("4:3"), "2304x1728")
        self.assertEqual(_image_size("3:4"), "1728x2304")
        self.assertEqual(_image_size("16:9"), "2560x1440")
        self.assertEqual(_image_size("9:16"), "1440x2560")
        self.assertEqual(_image_size("unknown"), "2048x2048")

    def test_store_creates_independent_canvas_projects_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "canvas.sqlite3")
            with store.connect() as db:
                columns = {
                    row[1]
                    for row in db.execute("PRAGMA table_info(canvas_projects)").fetchall()
                }
            self.assertEqual(
                columns,
                {"id", "workspace_id", "name", "graph_json", "created_at", "updated_at"},
            )

    def test_initial_canvas_project_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "canvas.sqlite3")
            store.insert("workspaces", {
                "id": "workspace",
                "name": "测试空间",
                "root_path": temp_dir,
                "description": "",
                "created_at": "2026-08-03",
                "updated_at": "2026-08-03",
            })
            payload = CreateCanvasProject(workspace_id="workspace")
            with patch.object(canvas, "store", store):
                first = asyncio.run(canvas.ensure_initial_canvas_project(payload))
                second = asyncio.run(canvas.ensure_initial_canvas_project(payload))
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(len(store.all("canvas_projects", "workspace_id=?", ("workspace",))), 1)

    def test_canvas_project_list_can_include_all_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "canvas.sqlite3")
            for workspace_id in ("first", "second"):
                store.insert("workspaces", {
                    "id": workspace_id,
                    "name": workspace_id,
                    "root_path": temp_dir,
                    "description": "",
                    "created_at": "2026-08-03",
                    "updated_at": "2026-08-03",
                })
                store.insert("canvas_projects", {
                    "id": f"project-{workspace_id}",
                    "workspace_id": workspace_id,
                    "name": workspace_id,
                    "graph_json": "{}",
                    "created_at": f"2026-08-03T00:00:0{1 if workspace_id == 'first' else 2}",
                    "updated_at": "2026-08-03",
                })
            with patch.object(canvas, "store", store):
                projects = asyncio.run(canvas.list_canvas_projects(workspace_id=None))
            self.assertEqual([project["workspace_id"] for project in projects], ["second", "first"])

    def test_graph_is_returned_as_json_safe_project_data(self) -> None:
        graph = CanvasGraph(
            nodes=[
                {
                    "id": "text-1",
                    "type": "text",
                    "position": {"x": 10, "y": 20},
                    "data": {"config": {"content": "一段提示词"}},
                }
            ],
            edges=[],
        )
        _validate_graph(graph)
        project = _project_row(
            {
                "id": "project-1",
                "workspace_id": "workspace-1",
                "name": "测试画布",
                "graph_json": json.dumps(graph.model_dump(), ensure_ascii=False),
                "created_at": "2026-08-02",
                "updated_at": "2026-08-02",
            }
        )
        self.assertEqual(project["graph"]["nodes"][0]["data"]["config"]["content"], "一段提示词")

    def test_graph_rejects_cycles(self) -> None:
        graph = CanvasGraph(
            nodes=[
                {"id": "a", "type": "text", "position": {"x": 0, "y": 0}},
                {"id": "b", "type": "note", "position": {"x": 1, "y": 1}},
            ],
            edges=[{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
        )
        with self.assertRaises(HTTPException):
            _validate_graph(graph)

    def test_direct_and_global_scopes_resolve_differently(self) -> None:
        graph = CanvasGraph(
            nodes=[
                {
                    "id": "direct",
                    "type": "text",
                    "position": {"x": 0, "y": 0},
                    "data": {"title": "直接来源", "config": {"content": "直接内容", "scope": "direct"}},
                },
                {
                    "id": "global",
                    "type": "note",
                    "position": {"x": 1, "y": 1},
                    "data": {"title": "全局来源", "config": {"content": "全局内容", "scope": "global"}},
                },
                {
                    "id": "target",
                    "type": "ai-image",
                    "position": {"x": 2, "y": 2},
                    "data": {"config": {}},
                },
                {
                    "id": "other",
                    "type": "ai-video",
                    "position": {"x": 3, "y": 3},
                    "data": {"config": {}},
                },
            ],
            edges=[{"source": "direct", "target": "target"}],
        )
        target_context = _resolve_node_context(graph, "target")
        other_context = _resolve_node_context(graph, "other")
        self.assertEqual(
            {item["source_node_id"] for item in target_context["references"]},
            {"direct", "global"},
        )
        self.assertEqual(
            {item["source_node_id"] for item in other_context["references"]},
            {"global"},
        )

    def test_video_uses_direct_ai_image_output_as_first_frame(self) -> None:
        graph = CanvasGraph(
            nodes=[
                {
                    "id": "image",
                    "type": "ai-image",
                    "position": {"x": 0, "y": 0},
                    "data": {"config": {"outputPath": "outputs/first-frame.png"}},
                },
                {
                    "id": "video",
                    "type": "ai-video",
                    "position": {"x": 1, "y": 1},
                    "data": {"config": {}},
                },
            ],
            edges=[{"source": "image", "target": "video"}],
        )
        self.assertEqual(_video_first_frame_path(graph, "video"), "outputs/first-frame.png")

    def test_r2v_reference_paths_include_direct_uploaded_image_and_video(self) -> None:
        """Dropping either direct upload would turn r2v back into prompt-only generation."""
        resolver = getattr(canvas, "_video_reference_paths", None)
        if resolver is None:
            self.fail("wan2.7-r2v 参考媒体解析尚未实现")
        graph = CanvasGraph(
            nodes=[
                {
                    "id": "person",
                    "type": "image-upload",
                    "position": {"x": 0, "y": 0},
                    "data": {"config": {"filePath": "uploads/model.webp"}},
                },
                {
                    "id": "dance",
                    "type": "video-upload",
                    "position": {"x": 0, "y": 100},
                    "data": {"config": {"filePath": "uploads/dance.mp4"}},
                },
                {
                    "id": "video",
                    "type": "ai-video",
                    "position": {"x": 400, "y": 0},
                    "data": {"config": {}},
                },
            ],
            edges=[
                {"source": "person", "target": "video"},
                {"source": "dance", "target": "video"},
            ],
        )
        self.assertEqual(
            resolver(graph, "video"),
            {
                "image_paths": ["uploads/model.webp"],
                "video_paths": ["uploads/dance.mp4"],
            },
        )

    def test_image_references_include_direct_upload_and_global_ai_image(self) -> None:
        graph = CanvasGraph(
            nodes=[
                {
                    "id": "upload",
                    "type": "image-upload",
                    "position": {"x": 0, "y": 0},
                    "data": {"config": {"filePath": "uploads/reference.png"}},
                },
                {
                    "id": "generated",
                    "type": "ai-image",
                    "position": {"x": 1, "y": 1},
                    "data": {"config": {"scope": "global", "outputPath": "outputs/style.png"}},
                },
                {
                    "id": "target",
                    "type": "ai-image",
                    "position": {"x": 2, "y": 2},
                    "data": {"config": {}},
                },
            ],
            edges=[{"source": "upload", "target": "target"}],
        )
        self.assertEqual(
            _image_reference_paths(graph, "target"),
            ["uploads/reference.png", "outputs/style.png"],
        )


if __name__ == "__main__":
    unittest.main()
