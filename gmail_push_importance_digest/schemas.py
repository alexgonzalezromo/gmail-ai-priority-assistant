from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class EmailContent:
    gmail_message_id: str
    thread_id: str
    history_id: str | None
    rfc_message_id: str | None
    sender: str
    subject: str
    message_date: str | None
    snippet: str
    plain_text: str
    labels: list[str]
    internal_ts: datetime | None


@dataclass(slots=True)
class ClassificationResult:
    is_important: bool
    importance_score: int
    urgency: str
    category: str
    summary: str
    why_it_matters: str
    action_needed: str
    deadline: str | None
    should_notify_now: bool
