from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_skill(path: Path) -> dict[str, str]:
    text = path.read_text(encoding='utf-8')
    frontmatter: dict[str, str] = {}
    if text.startswith('---'):
        match = re.match(r'^---\s*\n(.*?)\n---', text, re.S)
        if match:
            for line in match.group(1).splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    frontmatter[key.strip()] = value.strip().strip('"\'')
    return {'name': frontmatter.get('name', path.parent.name), 'description': frontmatter.get('description', ''), 'content': text}


def scan_skills(root: Path, scope: str = 'app_global') -> list[dict[str, Any]]:
    result = []
    if not root.exists():
        return result
    for skill_file in sorted(root.rglob('SKILL.md')):
        if not skill_file.is_file():
            continue
        relative_parts = skill_file.parent.relative_to(root).parts
        if not relative_parts:
            continue
        # Tencent SkillHub stores namespaced skills as
        # skills/<namespace>/<slug>/SKILL.md. The CLI may materialize the
        # namespace directory with a leading '@', while its coordinates and
        # command arguments omit it; normalize both forms to one id.
        canonical_parts = tuple(
            part.removeprefix('@') if index == 0 else part
            for index, part in enumerate(relative_parts)
        )
        skill_id = '--'.join(canonical_parts)
        meta = parse_skill(skill_file)
        result.append({
            'id': skill_id,
            'name': meta['name'],
            'description': meta['description'],
            'path': str(skill_file),
            'root_path': str(skill_file.parent),
            'scope': scope,
            'slug': canonical_parts[-1],
            'namespace': '/'.join(canonical_parts[:-1]),
        })
    return result


def scan_skill_sources(app_root: Path, workspace_root: Path | str | None = None) -> list[dict[str, Any]]:
    """Discover skills without conflating skill storage and task files.

    Application skills are installed once under ``app_root`` and are
    available to every workspace. Workspace skills are optional and follow
    the conventions used by Codex and Claude Code.
    """
    roots: list[tuple[Path, str]] = []
    if workspace_root:
        workspace = Path(workspace_root).expanduser().resolve()
        roots.extend((workspace / relative, 'workspace') for relative in ('.agents/skills', '.claude/skills'))
    roots.append((Path(app_root).expanduser().resolve(), 'app_global'))

    discovered: dict[str, dict[str, Any]] = {}
    for root, scope in roots:
        for item in scan_skills(root, scope=scope):
            # A workspace skill intentionally shadows an application skill
            # with the same id. No files are copied between the two scopes.
            discovered.setdefault(item['id'], item)
    return list(discovered.values())


def resolve_selected_skills(
    selected_ids: list[str] | set[str],
    app_root: Path,
    workspace_root: Path | str | None = None,
    enabled_global_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve selected skill IDs to their canonical on-disk directories."""
    enabled_global_ids = enabled_global_ids if enabled_global_ids is not None else set()
    discovered = {item['id']: item for item in scan_skill_sources(app_root, workspace_root)}
    result: list[dict[str, Any]] = []
    for skill_id in selected_ids:
        item = discovered.get(skill_id)
        if not item:
            continue
        if item['scope'] == 'app_global' and skill_id not in enabled_global_ids:
            continue
        result.append(item)
    return result


def build_skill_prompt(
    root: Path,
    enabled: set[str],
    workspace_root: Path | str | None = None,
) -> str:
    """Build a path-free summary; AgentScope loads full content via Skill."""
    sections = []
    for item in scan_skill_sources(root, workspace_root):
        if item['id'] in enabled:
            sections.append(
                f"- {item['name']}: {item['description']} "
                f"（来源：{'工作空间' if item['scope'] == 'workspace' else '应用全局'}；"
                '完整说明由 AgentScope 的 Skill 工具按需加载）'
            )
    return '\n'.join(sections)
