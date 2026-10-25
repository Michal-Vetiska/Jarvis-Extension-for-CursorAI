"""SQLite persistence layer."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from jarvis.db.schema import SCHEMA_SQL
from jarvis.paths import db_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Project:
    id: int
    alias: str
    path: str


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    # --- projects ---

    def register_project(self, alias: str, path: str) -> Project:
        resolved = str(Path(path).expanduser().resolve())
        if not Path(resolved).is_dir():
            raise FileNotFoundError(f"Projektová složka neexistuje: {resolved}")
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO projects(alias, path, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    path=excluded.path,
                    updated_at=excluded.updated_at
                """,
                (alias.strip(), resolved, _utc_now()),
            )
            row = conn.execute(
                "SELECT id, alias, path FROM projects WHERE alias = ? COLLATE NOCASE",
                (alias.strip(),),
            ).fetchone()
        return Project(id=row["id"], alias=row["alias"], path=row["path"])

    def get_project(self, alias: str) -> Project | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, alias, path FROM projects WHERE alias = ? COLLATE NOCASE",
                (alias.strip(),),
            ).fetchone()
        if not row:
            return None
        return Project(id=row["id"], alias=row["alias"], path=row["path"])

    def list_projects(self) -> list[Project]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id, alias, path FROM projects ORDER BY alias COLLATE NOCASE"
            ).fetchall()
        return [Project(id=r["id"], alias=r["alias"], path=r["path"]) for r in rows]

    def resolve_project_path(self, alias: str) -> str:
        project = self.get_project(alias)
        if not project:
            raise KeyError(f"Neznámý projektový alias: {alias}")
        if not Path(project.path).is_dir():
            raise FileNotFoundError(f"Cesta projektu {alias} neexistuje: {project.path}")
        return project.path

    # --- approved commands ---

    def approve_command(self, project_id: int, kind: str, command: str, cwd: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO approved_commands(project_id, kind, command, cwd)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(project_id, kind, command) DO UPDATE SET
                    cwd=excluded.cwd,
                    approved_at=datetime('now')
                """,
                (project_id, kind, command, cwd),
            )

    def is_command_approved(self, project_id: int, kind: str, command: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM approved_commands
                WHERE project_id=? AND kind=? AND command=?
                """,
                (project_id, kind, command),
            ).fetchone()
        return row is not None

    def get_approved_command(self, project_id: int, kind: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT command FROM approved_commands
                WHERE project_id=? AND kind=?
                ORDER BY approved_at DESC LIMIT 1
                """,
                (project_id, kind),
            ).fetchone()
        return row["command"] if row else None

    # --- conversation ---

    def add_message(self, role: str, content: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO conversation(role, content) VALUES(?, ?)",
                (role, content),
            )

    def recent_messages(self, limit: int = 50) -> list[dict[str, str]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at FROM conversation
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            for r in reversed(rows)
        ]

    # --- tasks ---

    def upsert_task(
        self,
        task_id: str,
        title: str,
        status: str,
        project_alias: str | None = None,
        current_step: str | None = None,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks(id, title, status, project_alias, current_step, payload_json, result_json, error, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    status=excluded.status,
                    project_alias=excluded.project_alias,
                    current_step=excluded.current_step,
                    payload_json=excluded.payload_json,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    title,
                    status,
                    project_alias,
                    current_step,
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    error,
                    _utc_now(),
                ),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        return dict(row)

    def latest_task(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def add_task_step(
        self,
        task_id: str,
        name: str,
        status: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        log_text: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> int:
        now = _utc_now()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_steps(
                    task_id, name, status, inputs_json, outputs_json, error, started_at, finished_at, log_text
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    name,
                    status,
                    json.dumps(inputs or {}, ensure_ascii=False),
                    json.dumps(outputs or {}, ensure_ascii=False),
                    error,
                    now if started else None,
                    now if finished else None,
                    log_text,
                ),
            )
            return int(cur.lastrowid)

    def update_task_step(
        self,
        step_id: int,
        status: str,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        log_text: str | None = None,
        finished: bool = False,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE task_steps
                SET status=?,
                    outputs_json=COALESCE(?, outputs_json),
                    error=?,
                    log_text=COALESCE(?, log_text),
                    finished_at=CASE WHEN ? THEN ? ELSE finished_at END
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(outputs, ensure_ascii=False) if outputs is not None else None,
                    error,
                    log_text,
                    1 if finished else 0,
                    _utc_now(),
                    step_id,
                ),
            )

    def list_task_steps(self, task_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_steps WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- servers ---

    def upsert_server(
        self,
        project_alias: str,
        command: str,
        cwd: str,
        status: str,
        pid: int | None = None,
        url: str | None = None,
        port: int | None = None,
        server_id: int | None = None,
    ) -> int:
        with self.connection() as conn:
            if server_id is None:
                cur = conn.execute(
                    """
                    INSERT INTO servers(project_alias, pid, command, cwd, url, port, status)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_alias, pid, command, cwd, url, port, status),
                )
                return int(cur.lastrowid)
            conn.execute(
                """
                UPDATE servers
                SET pid=?, command=?, cwd=?, url=?, port=?, status=?,
                    stopped_at=CASE WHEN ? IN ('stopped','failed') THEN datetime('now') ELSE stopped_at END
                WHERE id=?
                """,
                (pid, command, cwd, url, port, status, status, server_id),
            )
            return server_id

    def active_servers(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM servers WHERE status IN ('starting','running') ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_server_for_project(self, project_alias: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM servers
                WHERE project_alias=? COLLATE NOCASE AND status IN ('starting','running')
                ORDER BY id DESC LIMIT 1
                """,
                (project_alias,),
            ).fetchone()
        return dict(row) if row else None

    # --- settings ---

    def set_setting(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default
