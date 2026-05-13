from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    digest_to_email: str = os.getenv("DIGEST_TO_EMAIL", "")
    ntfy_topic: str = os.getenv("NTFY_TOPIC", "")
    google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    pubsub_topic: str = os.getenv("PUBSUB_TOPIC", "")
    pubsub_subscription: str = os.getenv("PUBSUB_SUBSCRIPTION", "")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", os.getenv("PUBSUB_VERIFICATION_TOKEN", ""))
    pubsub_push_token: str = os.getenv("PUBSUB_PUSH_TOKEN", "")
    importance_threshold: int = _env_int("IMPORTANCE_THRESHOLD", 70)
    max_emails_per_event: int = _env_int("MAX_EMAILS_PER_EVENT", 10)
    app_password: str = os.getenv("APP_PASSWORD", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _env_int("PORT", 8000)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")
    reply_action_secret: str = os.getenv("REPLY_ACTION_SECRET", "")
    reply_action_ttl_seconds: int = _env_int("REPLY_ACTION_TTL_SECONDS", 900)
    allow_legacy_reply_token: bool = _env_bool("ALLOW_LEGACY_REPLY_TOKEN", False)
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(ROOT_DIR / "data" / "app.db")))
    preferences_path: Path = Path(os.getenv("PREFERENCES_PATH", str(ROOT_DIR / "preferences.yaml")))
    personal_style_path: Path = Path(os.getenv("PERSONAL_STYLE_PATH", str(ROOT_DIR / "personal_style.md")))
    reply_persona_name: str = os.getenv("REPLY_PERSONA_NAME", "Tu Nombre")
    gmail_credentials_file: Path = Path(os.getenv("GMAIL_CREDENTIALS_FILE", str(ROOT_DIR / "credentials.json")))
    gmail_token_file: Path = Path(os.getenv("GMAIL_TOKEN_FILE", str(ROOT_DIR / "token.json")))
    gmail_watch_label_ids: tuple[str, ...] = ("INBOX",)
    gmail_model: str = "gpt-4.1-mini"

    @property
    def pubsub_topic_path(self) -> str:
        if self.pubsub_topic.startswith("projects/"):
            return self.pubsub_topic
        return f"projects/{self.google_cloud_project}/topics/{self.pubsub_topic}"

    @property
    def pubsub_subscription_path(self) -> str:
        if not self.pubsub_subscription:
            return ""
        if self.pubsub_subscription.startswith("projects/"):
            return self.pubsub_subscription
        return f"projects/{self.google_cloud_project}/subscriptions/{self.pubsub_subscription}"

    @property
    def reply_signing_secret(self) -> str:
        return self.reply_action_secret or self.webhook_secret


def get_settings() -> Settings:
    settings = Settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
