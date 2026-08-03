from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .capability_executor import _request_video, _request_wanxiang_i2v, _wanxiang_first_frame_data_url, generate_image, generate_video
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
    def test_wanxiang_i2v_uses_first_frame_media_protocol(self):
        class FakeResponse:
            def __init__(self, body: bytes, content_type: str = "application/json"):
                self.body = body
                self.headers = {"Content-Type": content_type}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body

        model = {
            "id": "wanxiang",
            "name": "万相 2.7 图生视频",
            "model": "wan2.7-i2v-2026-04-25",
            "provider": "dashscope",
            "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com",
            "api_key_env": "TEST_VIDEO_KEY",
            "config": json.dumps({"video_poll_interval_seconds": 1}),
        }
        responses = [
            FakeResponse(json.dumps({"output": {"task_id": "task-123", "task_status": "PENDING"}}).encode()),
            FakeResponse(json.dumps({"output": {"task_id": "task-123", "task_status": "SUCCEEDED", "video_url": "https://result.example/video.mp4"}}).encode()),
            FakeResponse(b"mp4", "video/mp4"),
        ]
        with patch.dict("os.environ", {"TEST_VIDEO_KEY": "sk-test"}, clear=False):
            with patch("backend.capability_executor.urllib.request.urlopen", side_effect=responses) as urlopen:
                result = _request_wanxiang_i2v(
                    model,
                    "让角色缓慢转头",
                    "5s",
                    "1080p",
                    "data:image/png;base64,aGVsbG8=",
                )

        self.assertEqual(result, b"mp4")
        create_request = urlopen.call_args_list[0].args[0]
        payload = json.loads(create_request.data.decode())
        self.assertEqual(create_request.get_header("X-dashscope-async"), "enable")
        self.assertEqual(payload["input"]["media"], [{"type": "first_frame", "url": "data:image/png;base64,aGVsbG8="}])
        self.assertEqual(payload["parameters"]["resolution"], "1080P")
        self.assertEqual(payload["parameters"]["duration"], 5)
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-123")
        result_request = urlopen.call_args_list[2].args[0]
        self.assertEqual(result_request.full_url, "https://result.example/video.mp4")
        self.assertIsNone(result_request.get_header("Authorization"))

    def test_wanxiang_first_frame_is_encoded_as_data_url(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "outputs" / "frame.png"
            image.parent.mkdir()
            image.write_bytes(b"frame")
            data_url = _wanxiang_first_frame_data_url(directory, "outputs/frame.png")
        self.assertEqual(data_url, "data:image/png;base64,ZnJhbWU=")

    def test_dashscope_video_uses_async_contract_and_nested_result(self):
        class FakeResponse:
            def __init__(self, body: bytes, content_type: str = "application/json"):
                self.body = body
                self.headers = {"Content-Type": content_type}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body

        model = {
            "id": "kling",
            "name": "可灵视频",
            "model": "kling/kling-v3-video-generation",
            "provider": "openai_compatible",
            "base_url": "https://llm-test.cn-beijing.maas.aliyuncs.com",
            "api_key_env": "TEST_VIDEO_KEY",
            "config": json.dumps(
                {
                    "video_poll_interval_seconds": 1,
                }
            ),
        }
        responses = [
            FakeResponse(
                json.dumps({"output": {"task_id": "task-123", "task_status": "PENDING"}}).encode()
            ),
            FakeResponse(
                json.dumps(
                    {
                        "output": {
                            "task_id": "task-123",
                            "task_status": "SUCCEEDED",
                            "video_url": "https://result.example/video.mp4",
                        }
                    }
                ).encode()
            ),
            FakeResponse(b"mp4", "video/mp4"),
        ]
        with patch.dict("os.environ", {"TEST_VIDEO_KEY": "sk-test"}, clear=False):
            with patch("backend.capability_executor.urllib.request.urlopen", side_effect=responses) as urlopen:
                result = _request_video(model, "小猫在月光下奔跑", "16:9", "5s", "1080p", "无声")

        self.assertEqual(result, b"mp4")
        create_request = urlopen.call_args_list[0].args[0]
        self.assertEqual(create_request.get_header("X-dashscope-async"), "enable")
        payload = json.loads(create_request.data.decode())
        self.assertEqual(payload["input"]["prompt"], "小猫在月光下奔跑")
        self.assertEqual(payload["parameters"]["duration"], 5)
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, "https://llm-test.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-123")
        self.assertIsNone(urlopen.call_args_list[1].args[0].get_header("X-dashscope-async"))
        self.assertEqual(urlopen.call_args_list[2].args[0].full_url, "https://result.example/video.mp4")

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
