from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class Preferences:
    user_name: str = ""
    primary_email: str = ""
    always_important_senders: list[str] = field(default_factory=list)
    ignored_senders: list[str] = field(default_factory=list)
    important_domains: list[str] = field(default_factory=list)
    important_keywords: list[str] = field(default_factory=list)
    ignored_keywords: list[str] = field(default_factory=list)
    tone: str = "normal"


def load_preferences(path: Path) -> Preferences:
    if not path.exists():
        return Preferences()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Preferences(**data)
