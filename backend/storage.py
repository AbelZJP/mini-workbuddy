from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL, root_path TEXT NOT NULL, description TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, title TEXT NOT NULL, status TEXT NOT NULL, permission_mode TEXT NOT NULL, model_id TEXT NOT NULL, current_state TEXT NOT NULL, selected_skill_ids TEXT DEFAULT '[]', selected_expert_ids TEXT DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, message_type TEXT DEFAULT 'text', metadata TEXT DEFAULT '{}', compressed INTEGER DEFAULT 0, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS models (id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, base_url TEXT DEFAULT '', api_key_env TEXT DEFAULT '', enabled INTEGER DEFAULT 1, config TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS skills (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', path TEXT NOT NULL, enabled INTEGER DEFAULT 1, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mcp_servers (id TEXT PRIMARY KEY, name TEXT NOT NULL, transport TEXT NOT NULL, command TEXT DEFAULT '', args TEXT DEFAULT '[]', url TEXT DEFAULT '', enabled INTEGER DEFAULT 0, allowed_tools TEXT DEFAULT '[]', env TEXT DEFAULT '{}', headers TEXT DEFAULT '{}', source_url TEXT DEFAULT '', updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE, category TEXT NOT NULL, content TEXT NOT NULL, source_task_id TEXT, confidence REAL DEFAULT 0.7, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
            CREATE TABLE IF NOT EXISTS summaries (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, summary TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, path TEXT NOT NULL, artifact_type TEXT DEFAULT 'file', operation TEXT DEFAULT 'created', previewable INTEGER DEFAULT 0, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experts (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', department TEXT DEFAULT '', catalog_path TEXT NOT NULL, installed_path TEXT DEFAULT '', installed INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, source TEXT DEFAULT 'agency-agents-zh', updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS canvas_projects (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, name TEXT NOT NULL, graph_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_canvas_projects_workspace_updated ON canvas_projects(workspace_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, status TEXT NOT NULL, current_step TEXT DEFAULT '', model_id TEXT DEFAULT '', permission_mode TEXT DEFAULT '', spec TEXT DEFAULT '{}', error TEXT DEFAULT '', cancel_requested INTEGER DEFAULT 0, started_at TEXT, finished_at TEXT, last_heartbeat TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS run_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE, sequence INTEGER NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(run_id, sequence));
            CREATE INDEX IF NOT EXISTS idx_agent_runs_task_created ON agent_runs(task_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence ON run_events(run_id, sequence);
            """)
            columns = {row[1] for row in db.execute('PRAGMA table_info(mcp_servers)').fetchall()}
            if 'headers' not in columns:
                db.execute("ALTER TABLE mcp_servers ADD COLUMN headers TEXT DEFAULT '{}'")
            if 'source_url' not in columns:
                db.execute("ALTER TABLE mcp_servers ADD COLUMN source_url TEXT DEFAULT ''")
            task_columns = {row[1] for row in db.execute('PRAGMA table_info(tasks)').fetchall()}
            if 'selected_skill_ids' not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN selected_skill_ids TEXT DEFAULT '[]'")
            if 'selected_expert_ids' not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN selected_expert_ids TEXT DEFAULT '[]'")

            run_columns = {row[1] for row in db.execute('PRAGMA table_info(agent_runs)').fetchall()}
            if 'spec' not in run_columns:
                db.execute("ALTER TABLE agent_runs ADD COLUMN spec TEXT DEFAULT '{}'")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def all(self, table: str, where: str = '', args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        query = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else '')
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, args).fetchall()]

    def one(self, table: str, where: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._row(db.execute(f"SELECT * FROM {table} WHERE {where}", args).fetchone())

    def insert(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        columns = ','.join(data)
        placeholders = ','.join('?' for _ in data)
        with self.connect() as db:
            db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(data.values()))
        return data

    def update(self, table: str, key: str, value: Any, data: dict[str, Any]) -> dict[str, Any] | None:
        assignments = ','.join(f'{column}=?' for column in data)
        with self.connect() as db:
            db.execute(f"UPDATE {table} SET {assignments} WHERE {key}=?", (*data.values(), value))
        return self.one(table, key + '=?', (value,))

    def delete(self, table: str, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(f"DELETE FROM {table} WHERE {key}=?", (value,))

    def add_message(self, task_id: str, role: str, content: str, created_at: str, metadata: dict[str, Any] | None = None, compressed: bool = False) -> dict[str, Any]:
        data = {'id': uuid.uuid4().hex, 'task_id': task_id, 'role': role, 'content': content, 'message_type': 'text', 'metadata': json.dumps(metadata or {}, ensure_ascii=False), 'compressed': int(compressed), 'created_at': created_at}
        return self.insert('messages', data)

    def messages(self, task_id: str, include_compressed: bool = False) -> list[dict[str, Any]]:
        where = 'task_id=?' + ('' if include_compressed else ' AND compressed=0')
        return self.all('messages', where + ' ORDER BY created_at, id', (task_id,))

    def json_config(self, row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        result = dict(row)
        for key in keys:
            if key in result and isinstance(result[key], str):
                try: result[key] = json.loads(result[key])
                except json.JSONDecodeError: pass
        return result

    def add_run_event(self, run_id: str, event_type: str, payload: dict[str, Any], created_at: str) -> dict[str, Any]:
        """Append an ordered, replayable event to a persisted Agent Run."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            sequence_row = db.execute(
                'SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM run_events WHERE run_id=?',
                (run_id,),
            ).fetchone()
            sequence = int(sequence_row['next_sequence'])
            db.execute(
                'INSERT INTO run_events (run_id, sequence, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)',
                (run_id, sequence, event_type, json.dumps(payload, ensure_ascii=False), created_at),
            )
        return {
            'run_id': run_id,
            'sequence': sequence,
            'event_id': f'{run_id}:{sequence}',
            'type': event_type,
            **payload,
        }

    def run_events(self, run_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                'SELECT run_id, sequence, event_type, payload, created_at FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?',
                (run_id, after, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row['payload'])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            result.append({
                'run_id': row['run_id'],
                'sequence': row['sequence'],
                'event_id': f"{row['run_id']}:{row['sequence']}",
                'type': row['event_type'],
                **payload,
            })
        return result
