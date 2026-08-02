from __future__ import annotations

import asyncio
from typing import Any

from .agent_runtime import run_agentscope


async def run_expert_team(
    model_config: Any,
    content: str,
    context: str,
    experts: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Run selected experts as independent workers and return bounded results."""

    async def run_worker(expert: dict[str, str]) -> dict[str, str]:
        try:
            result = await run_agentscope(
                model_config,
                content,
                context=context,
                expert_prompt=expert["prompt"],
                worker_mode=True,
            )
            if result is None:
                return {
                    "id": expert["id"],
                    "name": expert["name"],
                    "status": "skipped",
                    "output": "当前未启用真实 AgentScope，专家 Worker 未执行。",
                }
            text, _ = result
            return {
                "id": expert["id"],
                "name": expert["name"],
                "status": "completed",
                "output": text[:6000],
            }
        except Exception as exc:
            return {
                "id": expert["id"],
                "name": expert["name"],
                "status": "failed",
                "output": f"专家 Worker 执行失败：{exc}",
            }

    return list(await asyncio.gather(*(run_worker(expert) for expert in experts)))
