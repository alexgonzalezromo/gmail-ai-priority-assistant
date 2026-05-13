from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT UNIQUE NOT NULL,
    rfc_message_id TEXT UNIQUE,
    thread_id TEXT,
    sender TEXT,
    subject TEXT,
    message_date TEXT,
    history_id TEXT,
    importance_score INTEGER,
    is_important INTEGER NOT NULL DEFAULT 0,
    should_notify_now INTEGER NOT NULL DEFAULT 0,
    category TEXT,
    urgency TEXT,
    summary TEXT,
    why_it_matters TEXT,
    action_needed TEXT,
    deadline TEXT,
    raw_labels TEXT,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gmail_message_id, recipient_email)
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pubsub_message_id TEXT UNIQUE,
    email_address TEXT,
    history_id TEXT,
    payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'received',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS digest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    important_count INTEGER NOT NULL DEFAULT 0,
    notifications_sent_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def get_state(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(key, value, updated_at)
                VALUES(?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def is_processed(self, gmail_message_id: str, rfc_message_id: str | None) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM processed_emails
                WHERE gmail_message_id = ?
                   OR (? IS NOT NULL AND rfc_message_id = ?)
                LIMIT 1
                """,
                (gmail_message_id, rfc_message_id, rfc_message_id),
            ).fetchone()
            return row is not None

    def save_processed_email(self, record: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_emails (
                    gmail_message_id, rfc_message_id, thread_id, sender, subject, message_date,
                    history_id, importance_score, is_important, should_notify_now, category,
                    urgency, summary, why_it_matters, action_needed, deadline, raw_labels
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["gmail_message_id"],
                    record.get("rfc_message_id"),
                    record.get("thread_id"),
                    record.get("sender"),
                    record.get("subject"),
                    record.get("message_date"),
                    record.get("history_id"),
                    record.get("importance_score"),
                    int(record.get("is_important", False)),
                    int(record.get("should_notify_now", False)),
                    record.get("category"),
                    record.get("urgency"),
                    record.get("summary"),
                    record.get("why_it_matters"),
                    record.get("action_needed"),
                    record.get("deadline"),
                    json.dumps(record.get("raw_labels", [])),
                ),
            )

    def save_webhook_event(self, pubsub_message_id: str, email_address: str, history_id: str, payload: dict[str, Any]) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO webhook_events(pubsub_message_id, email_address, history_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (pubsub_message_id, email_address, history_id, json.dumps(payload)),
            )
            return cur.rowcount == 1

    def mark_webhook_event(self, pubsub_message_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE webhook_events
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pubsub_message_id = ?
                """,
                (status, pubsub_message_id),
            )

    def save_notification(self, gmail_message_id: str, recipient_email: str, subject: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO notifications_sent(gmail_message_id, recipient_email, subject)
                VALUES (?, ?, ?)
                """,
                (gmail_message_id, recipient_email, subject),
            )
            return cur.rowcount == 1

    def save_digest_run(
        self,
        run_type: str,
        trigger_source: str,
        message_count: int,
        important_count: int,
        notifications_sent_count: int,
        notes: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO digest_runs(run_type, trigger_source, message_count, important_count, notifications_sent_count, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_type, trigger_source, message_count, important_count, notifications_sent_count, notes),
            )

    def list_important(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT sender, subject, importance_score, urgency, category, summary, processed_at
                FROM processed_emails
                WHERE is_important = 1
                ORDER BY processed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return list(rows)

    def fetch_state_snapshot(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_state ORDER BY key").fetchall()
            return {row["key"]: row["value"] for row in rows}
