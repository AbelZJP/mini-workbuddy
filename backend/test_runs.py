from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .storage import Store


class RunPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp_dir.name) / 'run.sqlite3')
        self.store.insert('workspaces', {
            'id': 'workspace', 'name': '测试空间', 'root_path': self.temp_dir.name,
            'description': '', 'created_at': '2026-01-01', 'updated_at': '2026-01-01',
        })
        self.store.insert('tasks', {
            'id': 'task', 'workspace_id': 'workspace', 'title': '测试任务',
            'status': 'queued', 'permission_mode': 'readonly', 'model_id': 'demo',
            'current_state': '等待输入', 'selected_skill_ids': '[]',
            'selected_expert_ids': '[]', 'created_at': '2026-01-01', 'updated_at': '2026-01-01',
        })
        self.store.insert('agent_runs', {
            'id': 'run', 'task_id': 'task', 'status': 'queued', 'current_step': '排队',
            'model_id': 'demo', 'permission_mode': 'readonly', 'spec': '{}', 'error': '',
            'cancel_requested': 0, 'started_at': None, 'finished_at': None,
            'last_heartbeat': '2026-01-01', 'created_at': '2026-01-01', 'updated_at': '2026-01-01',
        })

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_events_are_ordered_and_replayable_after_cursor(self) -> None:
        first = self.store.add_run_event('run', 'run.started', {'type': 'run.started'}, '2026-01-01')
        second = self.store.add_run_event('run', 'assistant.delta', {'type': 'assistant.delta', 'content': '你好'}, '2026-01-01')
        third = self.store.add_run_event('run', 'task.completed', {'type': 'task.completed'}, '2026-01-01')

        self.assertEqual([first['sequence'], second['sequence'], third['sequence']], [1, 2, 3])
        self.assertEqual([item['type'] for item in self.store.run_events('run', after=1)], ['assistant.delta', 'task.completed'])

        reopened = Store(Path(self.temp_dir.name) / 'run.sqlite3')
        self.assertEqual(reopened.run_events('run', after=2)[0]['event_id'], 'run:3')


if __name__ == '__main__':
    unittest.main()
