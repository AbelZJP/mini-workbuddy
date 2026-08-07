from __future__ import annotations

import asyncio
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import capability_executor
from .capability_executor import _request_image, _request_video, _request_wanxiang_i2v, _seedream_reference_data_url, _wanxiang_first_frame_data_url, generate_image, generate_video
from .capability_registry import capability_rows, registry
from .core import model_row
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


def voice_clone_model(model_id: str = "minimax-voice") -> dict:
    return {
        "id": model_id,
        "name": "MiniMax 声音克隆",
        "model": "speech-2.8-hd",
        "provider": "minimax",
        "base_url": "https://api.minimax.io/v1",
        "api_key_env": "TEST_MINIMAX_KEY",
        "enabled": 1,
        "config": json.dumps(
            {
                "supports_voice_cloning": True,
                "capabilities": ["voice.clone"],
            }
        ),
    }


class CapabilityTests(unittest.TestCase):
    def test_minimax_requests_use_tls_1_2_context(self):
        """Allowing TLS 1.3 negotiation here reintroduces the observed EOF handshake failure."""
        context_factory = getattr(capability_executor, "_minimax_ssl_context", None)
        if context_factory is None:
            self.fail("MiniMax TLS 上下文尚未实现")
        context = context_factory()
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.maximum_version, ssl.TLSVersion.TLSv1_2)

    def test_model_row_exposes_voice_clone_capability(self):
        """Omitting this field would make a configured MiniMax model invisible to the canvas picker."""
        model = model_row(voice_clone_model())
        self.assertTrue(getattr(model, "supports_voice_cloning", False))

    def test_voice_clone_capability_uses_declared_voice_model(self):
        """Removing the voice capability flag must stop this model from being routed."""
        model = voice_clone_model()
        model["config"] = json.dumps({"supports_voice_cloning": True})
        store = FakeStore([model])
        routed = route_model(store, "voice.clone")
        self.assertIsNotNone(routed)
        self.assertEqual(routed["id"], "minimax-voice")
        self.assertEqual(
            next(item for item in capability_rows(store) if item["id"] == "voice.clone")["model_id"],
            "minimax-voice",
        )
        self.assertIsNotNone(registry.get("voice.clone"))

    def test_voice_clone_uploads_reference_and_saves_demo_audio(self):
        """A missing MiniMax upload, clone, download, or local write must fail this test."""
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

        generate_voice_clone = getattr(capability_executor, "generate_voice_clone", None)
        if generate_voice_clone is None:
            self.fail("声音克隆执行器尚未实现")
        responses = [
            FakeResponse(json.dumps({"file": {"file_id": 12345}, "base_resp": {"status_code": 0}}).encode()),
            FakeResponse(json.dumps({"demo_audio": "https://result.example/demo.mp3", "base_resp": {"status_code": 0}}).encode()),
            FakeResponse(b"mp3-data", "audio/mpeg"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "uploads" / "voice.wav"
            reference.parent.mkdir()
            reference.write_bytes(b"wav-data")
            with patch.dict("os.environ", {"TEST_MINIMAX_KEY": "sk-test"}, clear=False):
                with patch("backend.capability_executor.urllib.request.urlopen", side_effect=responses) as urlopen:
                    result = asyncio.run(
                        generate_voice_clone(
                            FakeStore([voice_clone_model()]),
                            directory,
                            "uploads/voice.wav",
                            "你好，欢迎使用声音克隆。",
                            output_filename="canvas-voice.mp3",
                        )
                    )
            self.assertTrue(result["ok"])
            self.assertEqual(result["artifact_path"], "outputs/canvas-voice.mp3")
            self.assertEqual((Path(directory) / "outputs" / "canvas-voice.mp3").read_bytes(), b"mp3-data")
        upload_request = urlopen.call_args_list[0].args[0]
        clone_request = urlopen.call_args_list[1].args[0]
        clone_payload = json.loads(clone_request.data.decode())
        self.assertEqual(upload_request.full_url, "https://api.minimax.io/v1/files/upload")
        self.assertIn(b'purpose"\r\n\r\nvoice_clone', upload_request.data)
        self.assertEqual(clone_request.full_url, "https://api.minimax.io/v1/voice_clone")
        self.assertEqual(clone_payload["file_id"], 12345)
        self.assertEqual(clone_payload["text"], "你好，欢迎使用声音克隆。")
        self.assertEqual(clone_payload["model"], "speech-2.8-hd")
        self.assertEqual(urlopen.call_args_list[2].args[0].full_url, "https://result.example/demo.mp3")

    def test_voice_clone_rejects_reference_outside_workspace(self):
        """Accepting an absolute external audio path would expose arbitrary local files."""
        encode_reference = getattr(capability_executor, "_voice_clone_reference_path", None)
        if encode_reference is None:
            self.fail("声音克隆参考音频校验尚未实现")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Exception, "当前工作空间"):
                encode_reference(directory, "/tmp/not-allowed.wav")

    def test_seedream_reference_images_use_ark_image_field(self):
        class FakeResponse:
            def __init__(self, body: bytes):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body

        model = {
            "id": "seedream",
            "name": "豆包 Seedream 5.0",
            "model": "doubao-seedream-5-0-260128",
            "provider": "openai_compatible",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key_env": "TEST_IMAGE_KEY",
            "config": "{}",
        }
        with patch.dict("os.environ", {"TEST_IMAGE_KEY": "sk-test"}, clear=False):
            with patch(
                "backend.capability_executor.urllib.request.urlopen",
                return_value=FakeResponse(json.dumps({"data": [{"b64_json": "cG5n"}]}).encode()),
            ) as urlopen:
                result = _request_image(
                    model,
                    "参考图中的人物形象生成海报",
                    "2048x2048",
                    ["data:image/png;base64,cmVmZXJlbmNl"],
                )
        self.assertEqual(result, b"png")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://ark.cn-beijing.volces.com/api/v3/images/generations")
        self.assertEqual(
            json.loads(request.data.decode())["image"],
            ["data:image/png;base64,cmVmZXJlbmNl"],
        )

    def test_seedream_reference_image_requires_workspace_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "uploads" / "reference.png"
            image.parent.mkdir()
            image.write_bytes(b"reference")
            self.assertEqual(
                _seedream_reference_data_url(directory, "uploads/reference.png"),
                "data:image/png;base64,cmVmZXJlbmNl",
            )
            with self.assertRaisesRegex(Exception, "当前工作空间"):
                _seedream_reference_data_url(directory, "/tmp/reference.png")

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

    def test_wanxiang_r2v_anchors_character_image_and_disables_prompt_rewrite(self):
        """Replacing r2v media with filenames or omitting OSS resolution must fail this contract."""
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

        request_r2v = getattr(capability_executor, "_request_wanxiang_r2v", None)
        if request_r2v is None:
            self.fail("wan2.7-r2v 参考生视频请求尚未实现")
        model = {
            "id": "wan-r2v",
            "name": "万相参考生视频",
            "model": "wan2.7-r2v",
            "provider": "dashscope",
            "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com",
            "api_key_env": "TEST_VIDEO_KEY",
            "config": json.dumps({"video_poll_interval_seconds": 1}),
        }
        responses = [
            FakeResponse(json.dumps({"output": {"task_id": "task-r2v", "task_status": "PENDING"}}).encode()),
            FakeResponse(json.dumps({"output": {"task_id": "task-r2v", "task_status": "SUCCEEDED", "video_url": "https://result.example/r2v.mp4"}}).encode()),
            FakeResponse(b"mp4", "video/mp4"),
        ]
        with patch.dict("os.environ", {"TEST_VIDEO_KEY": "sk-test"}, clear=False):
            with patch("backend.capability_executor.urllib.request.urlopen", side_effect=responses) as urlopen:
                result = request_r2v(
                    model,
                    "让图1中的模特复刻视频1的舞蹈动作",
                    "16:9",
                    "10s",
                    "720p",
                    [
                        {"type": "reference_image", "url": "oss://dashscope-instant/test/model.webp"},
                        {"type": "reference_video", "url": "oss://dashscope-instant/test/dance.mp4"},
                    ],
                )

        self.assertEqual(result, b"mp4")
        create_request = urlopen.call_args_list[0].args[0]
        payload = json.loads(create_request.data.decode())
        self.assertEqual(payload["model"], "wan2.7-r2v")
        self.assertEqual(payload["input"]["media"], [
            {"type": "first_frame", "url": "oss://dashscope-instant/test/model.webp"},
            {"type": "reference_image", "url": "oss://dashscope-instant/test/model.webp"},
            {"type": "reference_video", "url": "oss://dashscope-instant/test/dance.mp4"},
        ])
        self.assertEqual(payload["parameters"]["duration"], 10)
        self.assertFalse(payload["parameters"]["prompt_extend"])
        self.assertIn("图1中的人物是视频全程唯一人物", payload["input"]["prompt"])
        self.assertIn("视频1仅用作动作", payload["input"]["prompt"])
        self.assertEqual(create_request.get_header("X-dashscope-async"), "enable")
        self.assertEqual(create_request.get_header("X-dashscope-ossresourceresolve"), "enable")

    def test_r2v_rejects_15_seconds_before_uploading_reference_media(self):
        """Uploading media before enforcing the provider duration limit wastes external requests."""
        model = {
            "id": "wan-r2v",
            "name": "万相参考生视频",
            "model": "wan2.7-r2v",
            "provider": "dashscope",
            "api_key_env": "TEST_VIDEO_KEY",
            "enabled": 1,
            "config": json.dumps({"supports_video_generation": True, "capabilities": ["video.generate"]}),
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch("backend.capability_executor._wanxiang_r2v_media", side_effect=capability_executor.CapabilityExecutionError("不应上传素材")):
                result = asyncio.run(generate_video(
                    FakeStore([model]),
                    directory,
                    "让图1复刻视频1的动作",
                    duration="15s",
                    reference_image_paths=["uploads/model.webp"],
                    reference_video_paths=["uploads/dance.mp4"],
                ))
        self.assertFalse(result["ok"])
        self.assertIn("2 至 10 秒", result["message"])

    def test_non_r2v_model_rejects_connected_image_and_video_references(self):
        """Silently ignoring both references would recreate the original prompt-only bug."""
        with tempfile.TemporaryDirectory() as directory:
            with patch("backend.capability_executor._request_video", return_value=b"mp4"):
                result = asyncio.run(generate_video(
                    FakeStore([video_model()]),
                    directory,
                    "让人物跳舞",
                    reference_image_paths=["uploads/model.webp"],
                    reference_video_paths=["uploads/dance.mp4"],
                ))
        self.assertFalse(result["ok"])
        self.assertIn("wan2.7-r2v", result["message"])

    def test_r2v_audio_remux_keeps_generated_video_length_when_source_audio_is_shorter(self):
        """Audio remux must keep video length for either shorter or longer source tracks."""
        remux = getattr(capability_executor, "_replace_video_audio", None)
        if remux is None:
            self.fail("参考视频原音轨保留尚未实现")
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[0] == "/tmp/ffmpeg":
                Path(command[-1]).write_bytes(b"remuxed")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if "-select_streams" in command:
                return type("Result", (), {"returncode": 0, "stdout": "0\n", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": json.dumps({"format": {"duration": "10.0"}}), "stderr": ""})()

        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "generated.mp4"
            reference = Path(directory) / "reference.mp4"
            generated.write_bytes(b"generated")
            reference.write_bytes(b"reference")
            with patch("backend.capability_executor.shutil.which", side_effect=["/tmp/ffmpeg", "/tmp/ffprobe"]), patch("backend.capability_executor.subprocess.run", side_effect=fake_run):
                remux(generated, reference)
            self.assertEqual(generated.read_bytes(), b"remuxed")
        ffmpeg_command = next(command for command in calls if command[0] == "/tmp/ffmpeg")
        self.assertNotIn("-shortest", ffmpeg_command)
        self.assertIn("-t", ffmpeg_command)
        if "-t" in ffmpeg_command:
            self.assertEqual(ffmpeg_command[ffmpeg_command.index("-t") + 1], "10.0")

    def test_r2v_rejects_reference_video_longer_than_provider_limit_before_upload(self):
        """A 31-second reference video must not advance to temporary OSS upload."""
        validate_reference = getattr(capability_executor, "_r2v_reference_file", None)
        if validate_reference is None:
            self.fail("万相参考素材校验尚未实现")
        metadata = json.dumps({"streams": [{"width": 1280, "height": 720}], "format": {"duration": "31.0"}})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "reference.mp4"
            source.write_bytes(b"reference")
            with patch("backend.capability_executor.shutil.which", return_value="/tmp/ffprobe"), patch("backend.capability_executor.subprocess.run", return_value=type("Result", (), {"returncode": 0, "stdout": metadata, "stderr": ""})()):
                with self.assertRaisesRegex(capability_executor.CapabilityExecutionError, "1 至 30 秒"):
                    validate_reference(directory, "reference.mp4", "reference_video")

    def test_r2v_validates_every_reference_before_any_temporary_upload(self):
        """A bad later video must not cause an earlier valid image to be uploaded first."""
        media_builder = getattr(capability_executor, "_wanxiang_r2v_media", None)
        if media_builder is None:
            self.fail("万相参考媒体上传尚未实现")
        model = {"model": "wan2.7-r2v"}
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "model.webp"
            video = Path(directory) / "too-long.mp4"
            image.write_bytes(b"image")
            video.write_bytes(b"video")

            def validate_metadata(_path, media_kind):
                if media_kind == "reference_video":
                    raise capability_executor.CapabilityExecutionError("万相参考视频时长必须在 1 至 30 秒之间")

            with patch("backend.capability_executor._validate_r2v_media_metadata", side_effect=validate_metadata), patch("backend.capability_executor._upload_dashscope_temporary_file") as upload:
                with self.assertRaisesRegex(capability_executor.CapabilityExecutionError, "1 至 30 秒"):
                    media_builder(model, directory, ["model.webp"], ["too-long.mp4"])
            upload.assert_not_called()

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
