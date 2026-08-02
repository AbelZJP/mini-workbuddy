from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agentscope.skill import LocalSkillLoader

from .skills import build_skill_prompt, resolve_selected_skills, scan_skill_sources


def write_skill(root: Path, name: str, description: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / 'SKILL.md').write_text(
        f'---\nname: {name}\ndescription: {description}\n---\n\n{description}\n',
        encoding='utf-8',
    )
    return skill_dir


class SkillScopeTests(unittest.TestCase):
    def test_global_skill_resolves_in_a_new_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_skills = root / 'app' / 'skills'
            workspace = root / 'new-workspace'
            global_dir = write_skill(app_skills, 'report-writer', '生成结构化报告')
            workspace.mkdir()

            selected = resolve_selected_skills(
                ['report-writer'],
                app_skills,
                workspace,
                enabled_global_ids={'report-writer'},
            )

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]['scope'], 'app_global')
            self.assertEqual(Path(selected[0]['root_path']).resolve(), global_dir.resolve())
            self.assertFalse((workspace / 'SKILL.md').exists())
            self.assertNotIn(str(app_skills), build_skill_prompt(app_skills, {'report-writer'}, workspace))

    def test_workspace_skill_shadows_same_global_id_without_copying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_skills = root / 'app' / 'skills'
            workspace = root / 'project'
            global_dir = write_skill(app_skills, 'report-writer', '全局报告规范')
            workspace_dir = write_skill(workspace / '.agents' / 'skills', 'report-writer', '项目报告规范')

            discovered = scan_skill_sources(app_skills, workspace)
            selected = resolve_selected_skills(
                ['report-writer'],
                app_skills,
                workspace,
                enabled_global_ids={'report-writer'},
            )

            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0]['scope'], 'workspace')
            self.assertEqual(Path(selected[0]['root_path']).resolve(), workspace_dir.resolve())
            self.assertNotEqual(Path(selected[0]['root_path']).resolve(), global_dir.resolve())

    def test_agentscope_loader_reads_global_skill_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = write_skill(root / 'app' / 'skills', 'office-helper', '处理办公文档')

            skills = asyncio.run(LocalSkillLoader(str(skill_dir)).list_skills())

            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].name, 'office-helper')
            self.assertEqual(skills[0].markdown.strip(), '处理办公文档')


if __name__ == '__main__':
    unittest.main()
