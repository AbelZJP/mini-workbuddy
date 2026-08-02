from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from .expert_team import run_expert_team


class ExpertTeamTests(unittest.TestCase):
    def test_selected_experts_run_as_independent_workers(self):
        experts = [
            {"id": "research", "name": "研究专家", "prompt": "只做研究"},
            {"id": "writer", "name": "文案专家", "prompt": "只做文案"},
        ]
        received: list[str] = []

        async def fake_run_agentscope(*args, **kwargs):
            received.append(kwargs["expert_prompt"])
            return (f"完成：{kwargs['expert_prompt']}", [])

        with patch(
            "backend.expert_team.run_agentscope", side_effect=fake_run_agentscope
        ):
            results = asyncio.run(
                run_expert_team({"id": "model"}, "写一份方案", "上下文", experts)
            )

        self.assertEqual(received, ["只做研究", "只做文案"])
        self.assertEqual(
            [item["status"] for item in results], ["completed", "completed"]
        )
        self.assertNotIn("只做文案", received[0])

    def test_worker_failure_is_returned_without_aborting_other_workers(self):
        experts = [
            {"id": "ok", "name": "正常专家", "prompt": "正常"},
            {"id": "bad", "name": "失败专家", "prompt": "失败"},
        ]

        async def fake_run_agentscope(*args, **kwargs):
            if kwargs["expert_prompt"] == "失败":
                raise RuntimeError("worker failed")
            return ("正常结果", [])

        with patch(
            "backend.expert_team.run_agentscope", side_effect=fake_run_agentscope
        ):
            results = asyncio.run(
                run_expert_team({"id": "model"}, "任务", "上下文", experts)
            )

        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[1]["status"], "failed")
        self.assertIn("worker failed", results[1]["output"])


if __name__ == "__main__":
    unittest.main()
