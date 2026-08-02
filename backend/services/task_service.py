from __future__ import annotations

import json
import re

from ..schemas import Task


def task_title_from_message(content: str) -> str:
    clean = re.sub(r"\s+", " ", content or "").strip()
    clean = clean.split("附件（已复制到当前工作空间）：", 1)[0].strip()
    if not clean:
        return "新任务"
    return f"{clean[:18]}…" if len(clean) > 18 else clean


def task_row(row: dict) -> Task:
    data = dict(row)
    for key in ("selected_skill_ids", "selected_expert_ids"):
        value = data.get(key, [])
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        data[key] = [str(item) for item in value] if isinstance(value, list) else []
    return Task(**data)
