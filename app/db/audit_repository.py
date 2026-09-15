"""Append-only operational audit trail for API mutations."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class AuditRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_path TEXT NOT NULL,
                    status_code INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at ON audit_events(occurred_at DESC);
                """
            )

    def log(self, request_id: str, actor: str, action: str, resource_path: str, status_code: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    datetime.now(UTC).isoformat(),
                    request_id,
                    actor,
                    action,
                    resource_path,
                    status_code,
                ),
            )

    def list_events(self, limit: int, offset: int) -> dict:
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection
