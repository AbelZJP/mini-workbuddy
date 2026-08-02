from __future__ import annotations

from ..schemas import Workspace


def workspace_row(row: dict) -> Workspace:
    return Workspace(**row)
