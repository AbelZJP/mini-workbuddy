from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .capability_executor import generate_image, generate_video
from .capability_registry import capability_rows
from .model_router import route_model, set_capability_model


class FakeStore:
    def __init__(self, models: list[dict]):
        self.models = models
        self.settings: dict[str, str] = {}

    def one(self, table: str, where: str, args: tuple):
        if table == "models":
            return next((row for row in self.models if row["id"] == args[0]), None)
        if table == "settings":
            value = self.settings.get(args[0])
            return {"key": args[0], "value": value} if value is not None else None
        return None

    def all(self, table: str, where: str = ""):
        return self.models if table == "models" else []

    def insert(self, table: str, data: dict):
        if table == "settings":
            self.settings[data["key"]] = data["value"]
        return data

    def update(self, table: str, key: str, value: str, data: dict):
        if table == "settings":
            self.settings[value] = data["value"]
        return {"key": value, **data}


def image_model(model_id: str = "image") -> dict:
    return {
        "id": model_id,
        "name": "图片模型",
        "model": "image-model",
        "provider": "openai_images",
        "api_key_env": "TEST_IMAGE_KEY",
        "enabled": 1,
        "config": json.dumps(
            {
                "supports_image_generation": True,
                "capabilities": ["image.generate"],
            }
        ),
    }


def video_model(model_id: str = "video") -> dict:
    return {
        "id": model_id,
        "name": "视频模型",
        "model": "video-model",
        "provider": "openai_video",
        "api_key_env": "TEST_VIDEO_KEY",
        "enabled": 1,
        "config": json.dumps(
            {
                "supports_video_generation": True,
                "capabilities": ["video.generate"],
            }
        ),
    }


class CapabilityTests(unittest.TestCase):
    def test_capability_routes_to_declared_model_and_persists_override(self):
        store = FakeStore([image_model()])
        self.assertEqual(route_model(store, "image.generate")["id"], "image")
        set_capability_model(store, "image.generate", "image")
        rows = capability_rows(store)
        self.assertEqual(rows[0]["configured_model_id"], "image")
        self.assertEqual(rows[0]["model_id"], "image")

    def test_image_generation_writes_workspace_artifact(self):
        store = FakeStore([image_model()])
        with tempfile.TemporaryDirectory() as directory:
            with patch("backend.capability_executor._request_image", return_value=b"png"):
                result = asyncio.run(
                    generate_image(
                        store,
                        directory,
                        "一只戴眼镜的猫",
                        output_filename="cat.png",
                    )
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["artifact_path"], "outputs/cat.png")
            self.assertEqual(
                (Path(directory) / result["artifact_path"]).read_bytes(), b"png"
            )

    def test_image_generation_without_model_returns_controlled_failure(self):
        result = asyncio.run(generate_image(FakeStore([]), tempfile.mkdtemp(), "一只猫"))
        self.assertFalse(result["ok"])
        self.assertFalse(result["retryable"])

    def test_video_generation_writes_workspace_artifact(self):
        store = FakeStore([video_model()])
        with tempfile.TemporaryDirectory() as directory:
            with patch("backend.capability_executor._request_video", return_value=b"mp4"):
                result = asyncio.run(
                    generate_video(
                        store,
                        directory,
                        "一只猫在海边奔跑",
                        output_filename="cat.mp4",
                    )
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["artifact_path"], "outputs/cat.mp4")
            self.assertEqual(
                (Path(directory) / result["artifact_path"]).read_bytes(), b"mp4"
            )

    def test_video_generation_without_model_returns_controlled_failure(self):
        result = asyncio.run(generate_video(FakeStore([]), tempfile.mkdtemp(), "一只猫"))
        self.assertFalse(result["ok"])
        self.assertFalse(result["retryable"])


if __name__ == "__main__":
    unittest.main()
