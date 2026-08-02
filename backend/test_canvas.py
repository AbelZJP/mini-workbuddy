from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from .api.routers.canvas import (
    _image_size,
    _project_row,
    _resolve_node_context,
    _validate_graph,
)
from .schemas import CanvasGraph
from .storage import Store


class CanvasPersistenceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
