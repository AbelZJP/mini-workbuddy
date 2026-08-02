from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from .workspace_tools import (
    create_directory,
    edit_file,
    list_files,
    move_file,
    read_text_file,
    resolve_workspace_path,
    search_files,
    write_file,
)


class WorkspaceToolsTest(unittest.TestCase):
    def test_read_write_edit_search_and_move(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertTrue(create_directory(root, 'docs')['ok'])
            self.assertTrue(write_file(root, 'docs/notes.md', '项目计划\n第一阶段\n')['ok'])
            self.assertEqual(read_text_file(root, 'docs/notes.md')['content'], '项目计划\n第一阶段\n')
            self.assertTrue(edit_file(root, 'docs/notes.md', '第一阶段', '第二阶段')['ok'])
            search = search_files(root, '第二阶段')
            self.assertEqual(search['matches'][0]['path'], 'docs/notes.md')
            self.assertTrue(move_file(root, 'docs/notes.md', 'docs/archive.md')['ok'])
            self.assertEqual(list_files(root, 'docs')['entries'][0]['path'], 'docs/archive.md')

    def test_workspace_boundary_and_symlink_escape(self) -> None:
        with TemporaryDirectory() as temp, TemporaryDirectory() as outside:
            root = Path(temp)
            outside_path = Path(outside) / 'secret.txt'
            outside_path.write_text('secret', encoding='utf-8')
            with self.assertRaises(ValueError):
                resolve_workspace_path(root, '../secret.txt')
            link = root / 'link'
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                link = None
            if link is not None:
                with self.assertRaises(ValueError):
                    resolve_workspace_path(root, 'link/secret.txt')

    def test_office_binary_is_not_read_as_text(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'deck.pptx').write_bytes(b'PK\x03\x04')
            result = read_text_file(root, 'deck.pptx')
            self.assertFalse(result['ok'])
            self.assertIn('parse_document', result['error'])


if __name__ == '__main__':
    unittest.main()
