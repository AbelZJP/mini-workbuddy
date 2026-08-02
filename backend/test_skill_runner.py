from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from .skill_runner import execute_skill_script


class SkillRunnerTests(unittest.TestCase):
    skill_id = 'user_3b34947d--ppt-generator-skill'
    skill_root = Path(__file__).resolve().parent.parent / 'skills/@user_3b34947d/ppt-generator-skill'

    def test_ppt_skill_script_writes_artifact_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = asyncio.run(execute_skill_script(
                skill_id=self.skill_id,
                script='scripts/generate.js',
                args=['--title', '自动化测试 PPT', '--lang', 'zh'],
                output_path='outputs/test.pptx',
                timeout_seconds=60,
                workspace_root=temp,
                skill_roots={self.skill_id: str(self.skill_root)},
            ))
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['artifact_path'], 'outputs/test.pptx')
            self.assertGreater(Path(temp, 'outputs/test.pptx').stat().st_size, 1000)

    def test_ppt_skill_consumes_reference_document_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            reference = Path(temp) / 'reference.txt'
            reference.write_text(
                '# 客户服务升级方案\n\n'
                '## 当前问题\n'
                '- 首次响应时间过长\n'
                '- 人工转接率偏高\n\n'
                '## 改进计划\n'
                '- 引入智能分流\n'
                '- 建立质量复盘机制\n',
                encoding='utf-8',
            )
            result = asyncio.run(execute_skill_script(
                skill_id=self.skill_id,
                script='scripts/generate.js',
                args=['--title', '客户服务升级方案', '--lang', 'zh'],
                output_path='outputs/reference.pptx',
                timeout_seconds=60,
                workspace_root=temp,
                skill_roots={self.skill_id: str(self.skill_root)},
                reference_path='reference.txt',
            ))
            self.assertTrue(result['ok'], result)
            self.assertTrue(result['content_validation']['passed'], result)
            from .document_parser import parse_document
            parsed = parse_document(Path(temp, 'outputs/reference.pptx'))
            self.assertIn('首次响应时间过长', parsed['text'])
            self.assertIn('建立质量复盘机制', parsed['text'])
            self.assertNotIn('这是第一个核心要点', parsed['text'])

    def test_script_and_output_cannot_escape_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                asyncio.run(execute_skill_script(
                    skill_id=self.skill_id,
                    script='../outside.js',
                    args=[],
                    output_path='outputs/test.pptx',
                    timeout_seconds=60,
                    workspace_root=temp,
                    skill_roots={self.skill_id: str(self.skill_root)},
                ))
            with self.assertRaises(ValueError):
                asyncio.run(execute_skill_script(
                    skill_id=self.skill_id,
                    script='scripts/generate.js',
                    args=[],
                    output_path='../outside.pptx',
                    timeout_seconds=60,
                    workspace_root=temp,
                    skill_roots={self.skill_id: str(self.skill_root)},
                ))

    def test_script_timeout_returns_controlled_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill_root = Path(temp) / 'skill'
            skill_root.mkdir()
            (skill_root / 'SKILL.md').write_text('# test', encoding='utf-8')
            (skill_root / 'sleep.py').write_text(
                'import time\ntime.sleep(2)\n',
                encoding='utf-8',
            )
            result = asyncio.run(execute_skill_script(
                skill_id='sleep-skill',
                script='sleep.py',
                args=[],
                output_path='outputs/test.pptx',
                timeout_seconds=1,
                workspace_root=temp,
                skill_roots={'sleep-skill': str(skill_root)},
            ))
            self.assertFalse(result['ok'])
            self.assertIn('超过', result['message'])

    def test_check_mode_passes_script_specific_arguments_without_output_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill_root = Path(temp) / 'skill'
            skill_root.mkdir()
            (skill_root / 'SKILL.md').write_text('# test', encoding='utf-8')
            (skill_root / 'inspect.py').write_text(
                'import sys\nprint("ARGS=" + "|".join(sys.argv[1:]))\n',
                encoding='utf-8',
            )
            result = asyncio.run(execute_skill_script(
                skill_id='inspect-skill',
                script='inspect.py',
                args=['input.pptx', 'thumbs', '--cols', '4'],
                output_path='',
                timeout_seconds=60,
                workspace_root=temp,
                skill_roots={'inspect-skill': str(skill_root)},
                mode='check',
            ))
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['script_mode'], 'check')
            self.assertIn('ARGS=input.pptx|thumbs|--cols|4', result['stdout'])
            self.assertNotIn('--output', result['stdout'])

    def test_workspace_generated_script_requires_command_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / 'workspace'
            skill_root = Path(temp) / 'skill'
            workspace.mkdir()
            skill_root.mkdir()
            (skill_root / 'SKILL.md').write_text('# test', encoding='utf-8')
            (workspace / 'generate.py').write_text(
                'from pathlib import Path\n'
                'import sys\n'
                'output = Path(sys.argv[sys.argv.index("--output") + 1])\n'
                'output.write_text("workspace script", encoding="utf-8")\n',
                encoding='utf-8',
            )
            kwargs = {
                'skill_id': 'generated-skill',
                'script': 'generate.py',
                'args': [],
                'output_path': 'outputs/generated.txt',
                'timeout_seconds': 60,
                'workspace_root': str(workspace),
                'skill_roots': {'generated-skill': str(skill_root)},
            }
            with self.assertRaisesRegex(ValueError, '允许执行命令'):
                asyncio.run(execute_skill_script(**kwargs))

            result = asyncio.run(execute_skill_script(
                **kwargs,
                allow_workspace_script=True,
            ))
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['script_scope'], 'workspace')
            self.assertEqual(Path(workspace, 'outputs/generated.txt').read_text(encoding='utf-8'), 'workspace script')

    def test_workspace_generated_node_script_can_use_selected_skill_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / 'workspace'
            workspace.mkdir()
            generated = workspace / 'generate.js'
            shutil.copy2(self.skill_root / 'scripts/generate.js', generated)
            result = asyncio.run(execute_skill_script(
                skill_id=self.skill_id,
                script='generate.js',
                args=['--title', '工作空间脚本 PPT', '--lang', 'zh'],
                output_path='outputs/workspace-generated.pptx',
                timeout_seconds=60,
                workspace_root=str(workspace),
                skill_roots={self.skill_id: str(self.skill_root)},
                allow_workspace_script=True,
            ))
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['script_scope'], 'workspace')
            self.assertGreater(Path(workspace, 'outputs/workspace-generated.pptx').stat().st_size, 1000)


if __name__ == '__main__':
    unittest.main()
