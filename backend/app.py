from .main import app
from .core import store
from .api.routers import runs as _runs


def task_conversation_context(task_id: str) -> str:
    _runs.store = store
    return _runs.task_conversation_context(task_id)


def infer_referenced_attachment(task_id: str, content: str, workspace_root):
    _runs.store = store
    return _runs.infer_referenced_attachment(task_id, content, workspace_root)

__all__ = ['app', 'store', 'task_conversation_context', 'infer_referenced_attachment']
