from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .app import infer_referenced_attachment, task_conversation_context


class _StoreStub:
    def __init__(self, rows):
        self.rows = rows

    def messages(self, task_id, include_compressed=False):
        return self.rows

    def all(self, table, where='', args=()):
        return []


class ConversationContextTest(unittest.TestCase):
    def test_explicit_document_path_resolves_without_pronoun(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / '参考资料.docx'
            target.write_bytes(b'placeholder')
            with patch('backend.app.store', _StoreStub([])):
                result = infer_referenced_attachment(
                    'task-1', '请根据参考资料.docx 生成一份 PPT', root,
                )
            self.assertEqual(result, {'path': target.name, 'name': target.name})

    def test_follow_up_resolves_latest_file_reference(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / '827940040e00437e980d61584b2a5e6b.docx'
            target.write_bytes(b'placeholder')
            store = _StoreStub([
                {'role': 'assistant', 'content': '已找到文件：827940040e00437e980d61584b2a5e6b.docx', 'metadata': '{}'},
                {'role': 'user', 'content': '可以，你分析一下这个文件内容', 'metadata': '{}'},
            ])
            with patch('backend.app.store', store):
                result = infer_referenced_attachment(
                    'task-1', '可以，你分析一下这个文件内容', root,
                )
                context = task_conversation_context('task-1')
            self.assertEqual(result, {'path': target.name, 'name': target.name})
            self.assertIn('827940040e00437e980d61584b2a5e6b.docx', context)


if __name__ == '__main__':
    unittest.main()
