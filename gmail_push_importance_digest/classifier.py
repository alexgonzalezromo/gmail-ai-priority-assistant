from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from gmail_push_importance_digest.email_utils import truncate_for_model
from gmail_push_importance_digest.preferences import Preferences
from gmail_push_importance_digest.schemas import ClassificationResult, EmailContent


LOGGER = logging.getLogger(__name__)


class ImportanceClassifier:
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini") -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def classify(self, email_data: EmailContent, preferences: Preferences) -> ClassificationResult:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "is_important": {"type": "boolean"},
                "importance_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                "category": {
                    "type": "string",
                    "enum": ["work", "finance", "personal", "admin", "university", "spam", "newsletter", "other"],
                },
                "summary": {"type": "string"},
                "why_it_matters": {"type": "string"},
                "action_needed": {"type": "string"},
                "deadline": {"type": ["string", "null"]},
                "should_notify_now": {"type": "boolean"},
            },
            "required": [
                "is_important",
                "importance_score",
                "urgency",
                "category",
                "summary",
                "why_it_matters",
                "action_needed",
                "deadline",
                "should_notify_now",
            ],
        }
        instructions = (
            "You classify Gmail messages for importance. "
            "Return only JSON that matches the provided schema. "
            "Treat newsletters, generic promotions, spam and irrelevant noreply messages as not important. "
            "Treat emails requiring action, deadlines, work, finance, legal, or university context as more important. "
            "Use the user preferences strongly."
        )
        prompt = {
            "user_preferences": {
                "always_important_senders": preferences.always_important_senders,
                "ignored_senders": preferences.ignored_senders,
                "important_domains": preferences.important_domains,
                "important_keywords": preferences.important_keywords,
                "ignored_keywords": preferences.ignored_keywords,
                "tone": preferences.tone,
            },
            "email": {
                "sender": email_data.sender,
                "subject": email_data.subject,
                "date": email_data.message_date,
                "snippet": email_data.snippet,
                "labels": email_data.labels,
                "body": truncate_for_model(email_data.plain_text),
            },
        }
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=json.dumps(prompt, ensure_ascii=True),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "importance_classification",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        parsed = json.loads(response.output_text)
        return ClassificationResult(**parsed)
