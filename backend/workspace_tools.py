from __future__ import annotations

import base64
import mimetypes
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any


MAX_READ_CHARS = 80_000
MAX_SEARCH_RESULTS = 100
MAX_MEDIA_BYTES = 12 * 1024 * 1024
BINARY_DOCUMENT_SUFFIXES = {'.doc', '.docx', '.pdf', '.ppt', '.pptx', '.xls', '.xlsx'}
SKIP_DIRECTORIES = {'.git', '.mini-workbuddy', 'node_modules', '__pycache__'}


class WorkspacePathError(ValueError):
    """Raised when a workspace tool receives an unsafe path."""


def resolve_workspace_path(workspace_root: str | Path, value: str, *, allow_root: bool = False) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    raw = str(value or '').strip()
    if '\x00' in raw:
        raise WorkspacePathError('文件路径包含非法字符。')
    candidate = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).expanduser().resolve()
    if not candidate.is_relative_to(root):
        raise WorkspacePathError('文件路径超出当前工作空间，已拒绝访问。')
    if not allow_root and candidate == root:
        raise WorkspacePathError('该操作不能直接作用于工作空间根目录。')
    return candidate


def _relative(root: str | Path, path: Path) -> str:
    return path.relative_to(Path(root).expanduser().resolve()).as_posix()


def _error(exc: Exception) -> dict[str, Any]:
    return {'ok': False, 'error': str(exc)}


def list_files(
    workspace_root: str | Path,
    path: str = '',
    recursive: bool = False,
    max_results: int = 200,
) -> dict[str, Any]:
    try:
        directory = resolve_workspace_path(workspace_root, path, allow_root=True)
        if not directory.is_dir():
            raise WorkspacePathError('目标路径不是目录。')
        limit = max(1, min(int(max_results), 500))
        entries: list[dict[str, Any]] = []
        if recursive:
            iterator = os.walk(directory, topdown=True, followlinks=False)
            for current, directories, filenames in iterator:
                directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES]
                for name in sorted(directories):
                    item = Path(current) / name
                    entries.append({'path': _relative(workspace_root, item), 'type': 'directory'})
                for name in sorted(filenames):
                    item = Path(current) / name
                    entries.append({'path': _relative(workspace_root, item), 'type': 'file', 'size': item.stat().st_size})
                if len(entries) >= limit:
                    break
        else:
            for item in sorted(directory.iterdir(), key=lambda candidate: (not candidate.is_dir(), candidate.name.lower())):
                if item.name in SKIP_DIRECTORIES:
                    continue
                entries.append({
                    'path': _relative(workspace_root, item),
                    'type': 'directory' if item.is_dir() else 'file',
                    **({'size': item.stat().st_size} if item.is_file() else {}),
                })
                if len(entries) >= limit:
                    break
        return {'ok': True, 'path': _relative(workspace_root, directory), 'entries': entries, 'truncated': len(entries) >= limit}
    except (OSError, ValueError) as exc:
        return _error(exc)


def read_text_file(
    workspace_root: str | Path,
    path: str,
    start: int = 0,
    max_chars: int = MAX_READ_CHARS,
) -> dict[str, Any]:
    try:
        target = resolve_workspace_path(workspace_root, path)
        if not target.is_file():
            raise WorkspacePathError('目标路径不是文件。')
        if target.suffix.lower() in BINARY_DOCUMENT_SUFFIXES:
            return {'ok': False, 'error': '该文件是办公文档，不能使用文本读取工具；请调用 parse_document。'}
        sample = target.read_bytes()[:4096]
        if b'\x00' in sample:
            return {'ok': False, 'error': '该文件可能是二进制文件，不能使用文本读取工具；请调用 parse_document 或对应的媒体工具。'}
        offset = max(0, int(start))
        limit = max(1, min(int(max_chars), MAX_READ_CHARS))
        text = target.read_text(encoding='utf-8', errors='replace')
        content = text[offset:offset + limit]
        return {
            'ok': True,
            'path': _relative(workspace_root, target),
            'content': content,
            'start': offset,
            'next_start': offset + len(content) if offset + len(content) < len(text) else None,
            'truncated': offset + len(content) < len(text),
        }
    except (OSError, ValueError) as exc:
        return _error(exc)


def read_multiple_files(workspace_root: str | Path, paths: list[str]) -> dict[str, Any]:
    results = [read_text_file(workspace_root, path) for path in paths[:20]]
    return {'ok': all(item.get('ok') for item in results), 'files': results}


def search_files(
    workspace_root: str | Path,
    query: str,
    path: str = '',
    max_results: int = 50,
) -> dict[str, Any]:
    if not str(query).strip():
        return {'ok': False, 'error': '搜索关键词不能为空。'}
    try:
        directory = resolve_workspace_path(workspace_root, path, allow_root=True)
        if not directory.is_dir():
            raise WorkspacePathError('搜索范围不是目录。')
        limit = max(1, min(int(max_results), MAX_SEARCH_RESULTS))
        matches: list[dict[str, Any]] = []
        needle = str(query).casefold()
        for current, directories, filenames in os.walk(directory, topdown=True, followlinks=False):
            directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES]
            for name in filenames:
                target = Path(current) / name
                try:
                    sample = target.read_bytes()[:4096]
                    if b'\x00' in sample:
                        continue
                    text = target.read_text(encoding='utf-8', errors='ignore')
                except OSError:
                    continue
                lines = []
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if needle in line.casefold():
                        lines.append({'line': line_number, 'text': line[:500]})
                        if len(lines) >= 5:
                            break
                if lines:
                    matches.append({'path': _relative(workspace_root, target), 'matches': lines})
                if len(matches) >= limit:
                    return {'ok': True, 'query': query, 'matches': matches, 'truncated': True}
        return {'ok': True, 'query': query, 'matches': matches, 'truncated': False}
    except (OSError, ValueError) as exc:
        return _error(exc)


def get_file_info(workspace_root: str | Path, path: str) -> dict[str, Any]:
    try:
        target = resolve_workspace_path(workspace_root, path)
        stat = target.stat()
        return {
            'ok': True,
            'path': _relative(workspace_root, target),
            'type': 'directory' if target.is_dir() else 'file',
            'size': stat.st_size,
            'modified_at': stat.st_mtime,
        }
    except (OSError, ValueError) as exc:
        return _error(exc)


def create_directory(workspace_root: str | Path, path: str) -> dict[str, Any]:
    try:
        target = resolve_workspace_path(workspace_root, path)
        target.mkdir(parents=True, exist_ok=True)
        return {'ok': True, 'path': _relative(workspace_root, target), 'created': True}
    except (OSError, ValueError) as exc:
        return _error(exc)


def write_file(
    workspace_root: str | Path,
    path: str,
    content: str,
    overwrite: bool = True,
) -> dict[str, Any]:
    try:
        target = resolve_workspace_path(workspace_root, path)
        if target.exists() and not overwrite:
            raise WorkspacePathError('目标文件已存在，未覆盖。')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=target.parent, prefix=f'.{target.name}.', suffix='.tmp', delete=False,
            ) as temporary:
                temporary.write(str(content))
                temporary_path = Path(temporary.name)
            temporary_path.replace(target)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
        return {'ok': True, 'path': _relative(workspace_root, target), 'bytes': target.stat().st_size}
    except (OSError, ValueError) as exc:
        return _error(exc)


def edit_file(
    workspace_root: str | Path,
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    try:
        target = resolve_workspace_path(workspace_root, path)
        original = target.read_text(encoding='utf-8')
        count = original.count(old_text)
        if count == 0:
            raise WorkspacePathError('未找到要替换的原文，文件未修改。')
        if count > 1 and not replace_all:
            raise WorkspacePathError(f'原文匹配到 {count} 处，请提供更长的上下文或明确 replace_all=true。')
        updated = original.replace(old_text, new_text, -1 if replace_all else 1)
        return write_file(workspace_root, path, updated, overwrite=True)
    except (OSError, ValueError) as exc:
        return _error(exc)


def move_file(workspace_root: str | Path, source: str, destination: str) -> dict[str, Any]:
    try:
        source_path = resolve_workspace_path(workspace_root, source)
        destination_path = resolve_workspace_path(workspace_root, destination)
        if source_path == destination_path:
            raise WorkspacePathError('源路径和目标路径不能相同。')
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        return {
            'ok': True,
            'source': _relative(workspace_root, source_path),
            'destination': _relative(workspace_root, destination_path),
        }
    except (OSError, ValueError) as exc:
        return _error(exc)


def read_media_file(workspace_root: str | Path, path: str) -> Any:
    """Return an AgentScope DataBlock for a vision-capable model."""
    target = resolve_workspace_path(workspace_root, path)
    if not target.is_file():
        raise WorkspacePathError('目标路径不是媒体文件。')
    if target.stat().st_size > MAX_MEDIA_BYTES:
        raise WorkspacePathError('图片文件过大，当前限制为 12MB。')
    media_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
    if not media_type.startswith('image/'):
        raise WorkspacePathError('当前文件不是支持的图片格式。')
    from agentscope.message import Base64Source, DataBlock

    return DataBlock(
        source=Base64Source(
            data=base64.b64encode(target.read_bytes()).decode('ascii'),
            media_type=media_type,
        ),
        name=_relative(workspace_root, target),
    )
