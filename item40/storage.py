from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .domain import JobRequest, now


class Store:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, tool_id TEXT NOT NULL, source TEXT NOT NULL,
                options TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT '', transcript TEXT NOT NULL DEFAULT '',
                segments TEXT NOT NULL DEFAULT '[]', edited INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        for column, declaration in {"in_sources": "INTEGER NOT NULL DEFAULT 1",
                                    "output_path": "TEXT NOT NULL DEFAULT ''",
                                    "output_error": "TEXT NOT NULL DEFAULT ''"}.items():
            if column not in columns:
                self.connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {declaration}")
        self.connection.execute("PRAGMA user_version=2")
        self.connection.execute("UPDATE jobs SET status='interrupted', stage='Работа была прервана' "
                                "WHERE status='running'")
        self.connection.commit()

    def setting(self, key: str, default=None):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def add(self, request: JobRequest):
        with self.connection:
            self._insert(request)

    def _insert(self, request: JobRequest):
        stamp = now()
        self.connection.execute("""INSERT INTO jobs
                (id,tool_id,source,options,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)""",
                (request.id, request.tool_id, request.source, json.dumps(asdict(request)), "queued", stamp, stamp))

    def combine_sources(self, request: JobRequest, job_ids: list[str]):
        with self.connection:
            rows = [self.get(job_id) for job_id in job_ids]
            if not rows or any(not row or row["status"] == "running" for row in rows):
                raise ValueError("Один из файлов уже обрабатывается. Дождитесь завершения.")
            self._insert(request)
            for row in rows:
                if row["status"] == "queued" and not row["transcript"]:
                    self.connection.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
                else:
                    self.connection.execute("UPDATE jobs SET in_sources=0 WHERE id=?", (row["id"],))

    def reorder_sources(self, job_id, paths):
        row = self.get(job_id)
        if not row or row["status"] != "queued":
            raise ValueError("Порядок можно менять до запуска задачи.")
        options = json.loads(row["options"])
        options.update(source=paths[0], source_files=list(paths))
        with self.connection:
            self.connection.execute("UPDATE jobs SET source=?, options=?, updated_at=? WHERE id=?",
                                    (paths[0], json.dumps(options), now(), job_id))

    def update(self, job_id: str, **values):
        allowed = {"status", "progress", "stage", "transcript", "segments", "edited", "error",
                   "output_path", "output_error"}
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid job fields")
        if "segments" in values:
            values["segments"] = json.dumps(values["segments"], ensure_ascii=False)
        values["updated_at"] = now()
        with self.connection:
            self.connection.execute("UPDATE jobs SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                                    (*values.values(), job_id))

    def get(self, job_id: str):
        row = self.connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def configure_pending(self, model, language, device):
        with self.connection:
            for row in self.pending():
                options = json.loads(row["options"])
                options.update(model=model, language=language, device=device)
                self.connection.execute("UPDATE jobs SET options=?, updated_at=? WHERE id=? AND status='queued'",
                                        (json.dumps(options), now(), row["id"]))

    def jobs(self, limit=None):
        query = "SELECT * FROM jobs ORDER BY created_at DESC"
        if limit is not None:
            return [dict(row) for row in self.connection.execute(query + " LIMIT ?", (limit,))]
        return [dict(row) for row in self.connection.execute(query)]

    def pending(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM jobs WHERE status='queued' AND in_sources=1 ORDER BY created_at")]

    def source_jobs(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM jobs WHERE in_sources=1 ORDER BY created_at")]

    def hide_source(self, job_id):
        with self.connection:
            self.connection.execute("""UPDATE jobs SET in_sources=0, updated_at=?,
                status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END
                WHERE id=?""", (now(), job_id))

    def restore_source(self, job_id):
        with self.connection:
            self.connection.execute("UPDATE jobs SET in_sources=1 WHERE id=?", (job_id,))

    def close(self):
        self.connection.close()
