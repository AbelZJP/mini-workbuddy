from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from .skill_dependencies import ensure_skill_node_dependencies


class SkillDependencyTests(unittest.TestCase):
    def test_pptx_dependencies_are_installed_beside_skill_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill_root = Path(temp) / 'pptx'
            skill_root.mkdir()
            (skill_root / 'SKILL.md').write_text('# pptx', encoding='utf-8')
            fake_npm = Path(temp) / 'npm'
            fake_npm.write_text(
                '#!/usr/bin/env python3\n'
                'from pathlib import Path\n'
                'Path("node_modules").mkdir()\n'
                'Path("package-lock.json").write_text("{}\\n")\n'
                'print("fake npm ok")\n',
                encoding='utf-8',
            )
            fake_npm.chmod(fake_npm.stat().st_mode | stat.S_IXUSR)

            result = ensure_skill_node_dependencies('pptx', skill_root, str(fake_npm))

            package = json.loads((skill_root / 'package.json').read_text(encoding='utf-8'))
            self.assertTrue(result['installed'])
            self.assertEqual(package['dependencies']['pptxgenjs'], '^4.0.1')
            self.assertTrue((skill_root / 'package-lock.json').is_file())
            self.assertTrue((skill_root / 'node_modules').is_dir())
            self.assertFalse((skill_root.parent / 'package.json').exists())

    def test_skill_without_declared_runtime_dependencies_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill_root = Path(temp) / 'plain'
            skill_root.mkdir()
            (skill_root / 'SKILL.md').write_text('# plain', encoding='utf-8')

            result = ensure_skill_node_dependencies('plain', skill_root, os.getenv('SKILL_NPM'))

            self.assertTrue(result['skipped'])
            self.assertFalse((skill_root / 'package.json').exists())


if __name__ == '__main__':
    unittest.main()
