from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


BUILTIN_NODE_DEPENDENCIES: dict[str, dict[str, str]] = {
    'pptx': {'pptxgenjs': '^4.0.1'},
}


def _skill_key(skill_id: str, skill_root: Path) -> str:
    return (skill_id.rsplit('--', 1)[-1] or skill_root.name).lower()


def ensure_skill_node_dependencies(
    skill_id: str,
    skill_root: str | Path,
    npm_path: str | None = None,
) -> dict[str, Any]:
    """Install a Skill's Node dependencies beside its SKILL.md.

    Skills without a package manifest are left untouched unless the app has a
    small built-in dependency declaration for that Skill (currently pptx).
    npm scripts are disabled because Skill dependencies are untrusted code.
    """
    root = Path(skill_root).expanduser().resolve()
    if not root.is_dir() or not (root / 'SKILL.md').is_file():
        raise ValueError('Skill 目录不存在或缺少 SKILL.md')

    package_path = root / 'package.json'
    builtin_dependencies = BUILTIN_NODE_DEPENDENCIES.get(_skill_key(skill_id, root), {})
    package: dict[str, Any] = {}
    if package_path.is_file():
        try:
            parsed = json.loads(package_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'Skill package.json 无法读取：{package_path}') from exc
        if not isinstance(parsed, dict):
            raise ValueError(f'Skill package.json 格式无效：{package_path}')
        package = parsed

    dependencies = package.get('dependencies')
    if not isinstance(dependencies, dict):
        dependencies = {}
    if not dependencies and builtin_dependencies:
        dependencies = dict(builtin_dependencies)
        package = {
            'name': f'mini-workbuddy-skill-{_skill_key(skill_id, root)}',
            'private': True,
            'dependencies': dependencies,
        }
    if not dependencies:
        return {'installed': False, 'skipped': True, 'package_path': str(package_path)}

    npm = (npm_path or os.getenv('SKILL_NPM') or '').strip() or shutil.which('npm')
    if not npm:
        raise RuntimeError('Skill 需要 Node.js 依赖，但当前环境未找到 npm。请先安装 Node.js。')
    if not package_path.is_file():
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    try:
        completed = subprocess.run(
            [npm, 'install', '--ignore-scripts', '--no-audit', '--no-fund'],
            cwd=str(root),
            input='',
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
            env={**os.environ, 'NPM_CONFIG_FUND': 'false', 'NPM_CONFIG_AUDIT': 'false'},
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('Skill Node 依赖安装超时，请检查网络后重试') from exc
    output = '\n'.join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
    if completed.returncode != 0:
        raise RuntimeError(f'Skill Node 依赖安装失败（退出码 {completed.returncode}）：\n{output[-4000:]}')
    return {
        'installed': True,
        'skipped': False,
        'package_path': str(package_path),
        'node_modules_path': str(root / 'node_modules'),
        'output': output[-4000:] if output else 'Skill Node 依赖安装完成',
    }
