from __future__ import annotations

import json
import os
import re

from ..core import store


TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


def agent_run_timeout_seconds() -> int:
    try:
        return max(60, int(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "1800")))
    except ValueError:
        return 1800


def relevant_memories(workspace_id: str, content: str) -> list[dict]:
    tokens = [token for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", content.lower())]
    rows = store.all(
        "memories",
        "workspace_id=? AND deleted_at IS NULL ORDER BY updated_at DESC",
        (workspace_id,),
    )
    return [
        row
        for row in rows
        if not tokens or any(token in row["content"].lower() for token in tokens)
    ][:5]


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def public_run(row: dict) -> dict:
    result = {key: value for key, value in row.items() if key != "spec"}
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    return result
