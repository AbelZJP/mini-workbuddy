from __future__ import annotations

import io
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .storage import Store


EXPERT_REPOSITORY = 'https://github.com/jnMetaCode/agency-agents-zh'
EXPERT_ARCHIVE_URL = 'https://codeload.github.com/jnMetaCode/agency-agents-zh/zip/refs/heads/main'
_SKIPPED_ROOT_FILES = {'readme.md', 'agent-list.md', 'catalog.md', 'contributing.md', 'upstream.md'}
_DEPARTMENTS = {
    'academic': '学术', 'design': '设计', 'engineering': '工程', 'finance': '金融',
    'game-development': '游戏开发', 'gis': 'GIS', 'hr': '人力资源', 'integrations': '集成',
    'legal': '法务', 'marketing': '营销', 'paid-media': '付费媒体', 'product': '产品',
    'project-management': '项目管理', 'sales': '销售', 'security': '安全',
    'spatial-computing': '空间计算', 'specialized': '专项', 'strategy': '战略',
    'supply-chain': '供应链', 'support': '支持', 'testing': '测试',
}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _clean_markdown(text: str) -> str:
    return re.sub(r'[*`_#>|\[\]]', '', text).strip()


def _metadata(path: Path, catalog_root: Path) -> dict[str, str]:
    content = path.read_text(encoding='utf-8', errors='ignore')
    relative = path.relative_to(catalog_root)
    top_level = relative.parts[0] if len(relative.parts) > 1 else 'specialized'
    heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    name = _clean_markdown(heading.group(1)) if heading else path.stem.replace('-', ' ')
    front_matter = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    metadata = front_matter.group(1) if front_matter else ''
    description_match = re.search(r'^description:\s*["\']?(.+?)["\']?\s*$', metadata, re.MULTILINE)
    if description_match:
        description = _clean_markdown(description_match.group(1))
    else:
        body = content[front_matter.end():] if front_matter else content
        lines = [_clean_markdown(line) for line in body.splitlines()]
        description = next((line for line in lines if line and line != name and not line.startswith('##')), '')
    expert_id = re.sub(r'[^a-z0-9-]+', '-', f'{top_level}-{path.stem}'.lower()).strip('-')
    return {
        'id': expert_id,
        'name': name[:120],
        'description': description[:360],
        'department': _DEPARTMENTS.get(top_level, top_level),
        'catalog_path': relative.as_posix(),
    }


def scan_experts(catalog_root: Path) -> list[dict[str, str]]:
    if not catalog_root.exists():
        return []
    experts: list[dict[str, str]] = []
    for path in sorted(catalog_root.rglob('*.md')):
        relative = path.relative_to(catalog_root)
        if len(relative.parts) < 2 or relative.name.lower() in _SKIPPED_ROOT_FILES:
            continue
        if relative.parts[0].startswith('.') or relative.parts[0] in {'assets', 'examples', 'scripts'}:
            continue
        experts.append(_metadata(path, catalog_root))
    return experts


def sync_catalog(store: Store, experts_root: Path) -> list[dict[str, Any]]:
    """Download the public repository and atomically replace only its cache."""
    archive = urlopen(EXPERT_ARCHIVE_URL, timeout=30).read()
    stage = experts_root / 'catalog.next'
    catalog = experts_root / 'catalog'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for item in bundle.infolist():
                member = Path(item.filename)
                if item.is_dir() or member.suffix.lower() != '.md' or len(member.parts) < 3:
                    continue
                relative = Path(*member.parts[1:])
                if relative.is_absolute() or '..' in relative.parts:
                    continue
                target = stage / relative
                if not _inside(target, stage):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(item))
        experts = scan_experts(stage)
        if not experts:
            raise RuntimeError('专家库压缩包中没有发现可用的 Markdown 角色文件。')
        if catalog.exists():
            shutil.rmtree(catalog)
        stage.rename(catalog)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise

    existing = {row['id']: row for row in store.all('experts')}
    active_ids = set()
    stamp = datetime.now(timezone.utc).isoformat()
    for expert in experts:
        active_ids.add(expert['id'])
        old = existing.get(expert['id'])
        data = {
            **expert,
            'installed_path': old.get('installed_path', '') if old else '',
            'installed': old.get('installed', 0) if old else 0,
            'enabled': old.get('enabled', 1) if old else 1,
            'source': 'agency-agents-zh',
            'updated_at': stamp,
        }
        if old:
            store.update('experts', 'id', expert['id'], data)
        else:
            store.insert('experts', data)
    for expert_id, row in existing.items():
        if expert_id not in active_ids and not row.get('installed'):
            store.delete('experts', 'id', expert_id)
    return store.all('experts', '1=1 ORDER BY department, name')


def install_expert(store: Store, experts_root: Path, expert_id: str) -> dict[str, Any]:
    expert = store.one('experts', 'id=?', (expert_id,))
    if not expert:
        raise KeyError('专家不存在，请先同步专家库。')
    catalog = experts_root / 'catalog'
    source = catalog / expert['catalog_path']
    if not source.exists() or not _inside(source, catalog):
        raise FileNotFoundError('专家原始文件不存在，请重新同步专家库。')
    target = experts_root / 'installed' / expert['catalog_path']
    if not _inside(target, experts_root / 'installed'):
        raise ValueError('专家安装路径不合法。')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return store.update('experts', 'id', expert_id, {'installed': 1, 'installed_path': str(target), 'updated_at': datetime.now(timezone.utc).isoformat()}) or expert


def uninstall_expert(store: Store, experts_root: Path, expert_id: str) -> dict[str, Any]:
    expert = store.one('experts', 'id=?', (expert_id,))
    if not expert:
        raise KeyError('专家不存在。')
    installed_root = experts_root / 'installed'
    target = Path(expert.get('installed_path') or installed_root / expert['catalog_path'])
    if target.exists() and _inside(target, installed_root) and target.is_file():
        target.unlink()
    return store.update('experts', 'id', expert_id, {'installed': 0, 'installed_path': '', 'updated_at': datetime.now(timezone.utc).isoformat()}) or expert
