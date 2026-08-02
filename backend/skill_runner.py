from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

from .document_parser import DocumentParseError, parse_document


ALLOWED_SCRIPT_SUFFIXES = {'.js', '.py'}
MAX_SCRIPT_TIMEOUT_SECONDS = 600
SKILL_SCRIPT_MODES = {'artifact', 'check'}


def _reference_anchors(path: Path) -> list[str]:
    text = path.read_text(encoding='utf-8', errors='ignore')
    anchors: list[str] = []
    for raw_line in text.replace('\r\n', '\n').splitlines():
        line = str(raw_line).strip()
        if not line or line.startswith(('附件文件：', '文件格式：', '文件内容：', '[第 ', '[工作表：')):
            continue
        line = re.sub(r'^(?:#{1,6}\s+|[-*•]\s*)', '', line).strip()
        if len(line) < 4:
            continue
        anchor = line[:80]
        if anchor not in anchors:
            anchors.append(anchor)
        if len(anchors) >= 8:
            break
    return anchors


def _validate_reference_content(reference: Path, artifact: Path) -> dict[str, Any]:
    """Verify that a generated presentation contains source-document anchors."""
    try:
        parsed = parse_document(artifact)
    except DocumentParseError as exc:
        return {'passed': False, 'message': f'无法重新解析生成的 PPT：{exc}'}
    output = re.sub(r'\s+', '', str(parsed.get('text') or ''))
    anchors = _reference_anchors(reference)
    matched = [anchor for anchor in anchors if re.sub(r'\s+', '', anchor) in output]
    required = max(1, min(3, len(anchors))) if anchors else 0
    return {
        'passed': bool(anchors) and len(matched) >= required,
        'required': required,
        'matched': len(matched),
        'anchors': anchors,
        'matched_anchors': matched,
    }


def _safe_slug(value: str) -> str:
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', value).strip('-._')
    return slug or 'skill-output'


def _workspace_path(workspace_root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (workspace_root / candidate).resolve()
    if not resolved.is_relative_to(workspace_root):
        raise ValueError('输出路径必须位于当前工作空间内')
    return resolved


def _validate_script_args(args: list[str], workspace: Path) -> None:
    """Reject argument paths that could escape the current workspace."""
    for raw_value in args:
        value = str(raw_value)
        if value.startswith('~'):
            raise ValueError('Skill 脚本参数不能包含工作空间外的绝对路径')
        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        elif value.startswith(('../', '..\\')):
            resolved = (workspace / candidate).resolve()
        else:
            continue
        if not resolved.is_relative_to(workspace):
            raise ValueError('Skill 脚本参数不能包含工作空间外的绝对路径')


def _normalize_artifact_args(args: list[str], target: Path, workspace: Path) -> list[str]:
    """Keep artifact commands argv-based and replace their managed output option."""
    _validate_script_args(args, workspace)
    normalized: list[str] = []
    index = 0
    while index < len(args):
        value = str(args[index])
        if value in {'--output', '-o'}:
            index += 2
            continue
        normalized.append(value)
        index += 1
    normalized.extend(['--output', str(target)])
    return normalized


async def execute_skill_script(
    *,
    skill_id: str,
    script: str,
    args: list[str] | None,
    output_path: str,
    timeout_seconds: int,
    workspace_root: str,
    skill_roots: dict[str, str],
    reference_path: str = '',
    mode: str = 'artifact',
    allow_workspace_script: bool = False,
) -> dict[str, Any]:
    """Execute one explicitly selected Skill script without invoking a shell.

    ``artifact`` manages one workspace output file for legacy generators.
    ``check`` passes arguments through for validators, thumbnailers and other
    Skill scripts whose output contract is not ``--output <file>``.
    """
    if mode not in SKILL_SCRIPT_MODES:
        raise ValueError('Skill 脚本 mode 只能是 artifact 或 check')
    skill_root_raw = skill_roots.get(skill_id)
    if not skill_root_raw:
        raise ValueError('只能执行当前任务已选择的 Skill')
    skill_root = Path(skill_root_raw).expanduser().resolve()
    workspace = Path(workspace_root).expanduser().resolve()
    if not skill_root.is_dir() or not (skill_root / 'SKILL.md').is_file():
        raise ValueError('Skill 目录不存在或缺少 SKILL.md')

    if not workspace.is_dir():
        raise ValueError('当前工作空间不存在')

    script_value = str(script).strip()
    if not script_value or Path(script_value).is_absolute():
        raise ValueError('script 必须是相对路径，不能传入绝对路径')
    skill_script_path = (skill_root / script_value).resolve()
    workspace_script_path = (workspace / script_value).resolve()
    script_scope = 'skill'
    if skill_script_path.is_relative_to(skill_root) and skill_script_path.is_file():
        script_path = skill_script_path
    elif workspace_script_path.is_relative_to(workspace) and workspace_script_path.is_file():
        if not allow_workspace_script:
            raise ValueError('工作空间内的脚本需要“允许执行命令”或“完全自主”权限')
        script_path = workspace_script_path
        script_scope = 'workspace'
    else:
        raise ValueError(
            f'找不到脚本：{script}。请传入 Skill 目录或当前工作空间内的 .js/.py 相对路径。'
        )
    if script_path.suffix.lower() not in ALLOWED_SCRIPT_SUFFIXES:
        raise ValueError(
            f'脚本不是允许的 .js/.py 文件：{script}。'
            '请传入相对路径，例如 scripts/add_slide.py 或 generate.js。'
        )

    reference_file = ''
    if reference_path.strip():
        reference = _workspace_path(workspace, reference_path)
        if not reference.is_file():
            raise ValueError('参考文档解析结果不存在，无法生成基于参考文档的 PPT')
        reference_file = str(reference)

    raw_args = [str(item) for item in (args or [])]
    target: Path | None = None
    if mode == 'artifact':
        relative_output = output_path.strip() or f'outputs/{_safe_slug(skill_id)}.pptx'
        target = _workspace_path(workspace, relative_output)
        target.parent.mkdir(parents=True, exist_ok=True)
        command_args = _normalize_artifact_args(raw_args, target, workspace)
    else:
        if output_path.strip():
            raise ValueError('check 模式不接受 output_path，请把脚本参数直接传入 args')
        _validate_script_args(raw_args, workspace)
        command_args = raw_args
    if script_path.suffix.lower() == '.js':
        command = ['node', str(script_path), *command_args]
    else:
        command = [sys.executable, str(script_path), *command_args]

    try:
        timeout = max(1, min(int(timeout_seconds), MAX_SCRIPT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = 300
    environment = os.environ.copy()
    environment['MINI_WORKBUDDY_WORKSPACE'] = str(workspace)
    node_paths = [str(path) for path in (
        skill_root / 'node_modules',
        workspace / 'node_modules',
    ) if path.is_dir()]
    if node_paths:
        existing_node_path = environment.get('NODE_PATH', '')
        environment['NODE_PATH'] = os.pathsep.join(node_paths + ([existing_node_path] if existing_node_path else []))
    if target:
        environment['MINI_WORKBUDDY_OUTPUT'] = str(target)
    else:
        environment.pop('MINI_WORKBUDDY_OUTPUT', None)
    if reference_file:
        # The Skill script receives the parsed reference through an explicit
        # trusted environment contract, avoiding large document content in argv.
        environment['MINI_WORKBUDDY_REFERENCE_FILE'] = reference_file
    else:
        environment.pop('MINI_WORKBUDDY_REFERENCE_FILE', None)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(skill_root if script_scope == 'skill' and mode == 'artifact' else workspace),
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {
            'ok': False,
            'retryable': False,
            'message': f'Skill 脚本执行超过 {timeout} 秒，已停止。',
            'script': script,
            'exit_code': -1,
        }

    stdout_text = stdout.decode('utf-8', errors='replace')[-12000:]
    stderr_text = stderr.decode('utf-8', errors='replace')[-12000:]
    if process.returncode != 0:
        return {
            'ok': False,
            'retryable': False,
            'message': 'Skill 脚本执行失败。',
            'script': script,
            'exit_code': process.returncode,
            'stdout': stdout_text,
            'stderr': stderr_text,
        }
    if mode == 'check':
        return {
            'ok': True,
            'message': 'Skill 检查脚本执行完成。',
            'script': script,
            'exit_code': process.returncode,
            'stdout': stdout_text,
            'stderr': stderr_text,
            'script_mode': mode,
            'script_scope': script_scope,
        }
    assert target is not None
    if not target.is_file():
        return {
            'ok': False,
            'retryable': False,
            'message': 'Skill 脚本执行完成，但没有在工作空间中发现声明的输出文件。',
            'script': script,
            'exit_code': process.returncode,
            'stdout': stdout_text,
            'stderr': stderr_text,
        }
    validation: dict[str, Any] | None = None
    if reference_file and target.suffix.lower() in {'.ppt', '.pptx'}:
        reference_path_obj = Path(reference_file)
        validation = _validate_reference_content(reference_path_obj, target)
        if not validation.get('passed'):
            return {
                'ok': False,
                'retryable': False,
                'message': '生成的 PPT 未通过参考文档内容校验，未确认产物内容与参考文档一致。',
                'script': script,
                'exit_code': process.returncode,
                'stdout': stdout_text,
                'stderr': stderr_text,
                'content_validation': validation,
            }
    return {
        'ok': True,
        'message': 'Skill 脚本执行完成。',
        'script': script,
        'exit_code': process.returncode,
        'stdout': stdout_text,
        'stderr': stderr_text,
        'script_mode': mode,
        'script_scope': script_scope,
        'artifact_path': target.relative_to(workspace).as_posix(),
        'artifact_type': target.suffix.lower().lstrip('.') or 'file',
        'artifact_operation': 'created',
        **({'content_validation': validation} if validation else {}),
    }
