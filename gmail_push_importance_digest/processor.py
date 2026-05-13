from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from googleapiclient.errors import HttpError

from gmail_push_importance_digest.classifier import ImportanceClassifier
from gmail_push_importance_digest.config import Settings
from gmail_push_importance_digest.db import Database
from gmail_push_importance_digest.email_utils import build_digest_email, parse_message
from gmail_push_importance_digest.gmail_client import GmailClient
from gmail_push_importance_digest.preferences import load_preferences
from gmail_push_importance_digest.ntfy import send_ntfy
from gmail_push_importance_digest.reply_auth import build_signed_reply_params


LOGGER = logging.getLogger(__name__)


class GmailEventProcessor:
    def __init__(self, settings: Settings, db: Database, gmail_client: GmailClient) -> None:
        self.settings = settings
        self.db = db
        self.gmail_client = gmail_client

    def renew_watch(self, reset_history_id: bool = False) -> dict[str, Any]:
        result = self.gmail_client.watch_mailbox(
            topic_name=self.settings.pubsub_topic_path,
            label_ids=list(self.settings.gmail_watch_label_ids),
        )
        self.db.set_state("watch_expiration", str(result["expiration"]))
        if reset_history_id or not self.db.get_state("last_history_id"):
            self.db.set_state("last_history_id", str(result["historyId"]))
        return result

    def process_pubsub_notification(self, event: dict[str, Any]) -> dict[str, int]:
        message = event["message"]
        pubsub_message_id = message["messageId"]
        decoded = event["decoded_data"]
        email_address = decoded["emailAddress"]
        incoming_history_id = str(decoded["historyId"])

        inserted = self.db.save_webhook_event(pubsub_message_id, email_address, incoming_history_id, event)
        if not inserted:
            LOGGER.info("Evento Pub/Sub duplicado ignorado: %s", pubsub_message_id)
            return {"processed": 0, "important": 0, "notified": 0}

        try:
            summary = self._process_incremental_history(incoming_history_id)
            self.db.mark_webhook_event(pubsub_message_id, "processed")
            return summary
        except Exception:
            self.db.mark_webhook_event(pubsub_message_id, "failed")
            raise

    def _process_incremental_history(self, incoming_history_id: str) -> dict[str, int]:
        last_history_id = self.db.get_state("last_history_id")
        if not last_history_id:
            self.db.set_state("last_history_id", incoming_history_id)
            LOGGER.info("Inicializado last_history_id=%s desde notificación", incoming_history_id)
            return {"processed": 0, "important": 0, "notified": 0}

        try:
            max_history_results = max(50, self.settings.max_emails_per_event * 5)
            history_pages = []
            page_token = None
            while True:
                page = self.gmail_client.list_history(
                    start_history_id=last_history_id,
                    max_results=max_history_results,
                    page_token=page_token,
                )
                history_pages.append(page)
                page_token = page.get("nextPageToken")
                if not page_token:
                    break

            message_ids = self._extract_message_ids_from_history(history_pages)
            new_history_id = str(history_pages[-1].get("historyId", incoming_history_id))
        except HttpError as exc:
            if not self.gmail_client.is_history_out_of_date(exc):
                raise
            LOGGER.warning("HistoryId desactualizado; aplicando fallback reciente")
            message_ids = [item["id"] for item in self.gmail_client.list_recent_messages(self.settings.max_emails_per_event)]
            new_history_id = incoming_history_id

        limited_ids = message_ids[: self.settings.max_emails_per_event]
        processed = 0
        important = 0
        notified = 0

        classifier = ImportanceClassifier(self.settings.openai_api_key, self.settings.gmail_model)
        preferences = load_preferences(self.settings.preferences_path)
        for gmail_message_id in limited_ids:
            result = self._process_single_message(gmail_message_id, classifier, preferences)
            if result is None:
                continue
            processed += 1 if result["processed"] else 0
            important += 1 if result["important"] else 0
            notified += 1 if result["notified"] else 0

        self.db.set_state("last_history_id", new_history_id)
        self.db.save_digest_run(
            run_type="event",
            trigger_source="pubsub",
            message_count=processed,
            important_count=important,
            notifications_sent_count=notified,
            notes=f"history_id={new_history_id}",
        )
        return {"processed": processed, "important": important, "notified": notified}

    @staticmethod
    def _extract_message_ids_from_history(history_pages: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for history_response in history_pages:
            for history_item in history_response.get("history", []):
                for added in history_item.get("messagesAdded", []):
                    message = added.get("message", {})
                    message_id = message.get("id")
                    if message_id and message_id not in seen:
                        seen.add(message_id)
                        ordered.append(message_id)
        return ordered

    def _process_single_message(self, gmail_message_id: str, classifier: ImportanceClassifier, preferences) -> dict[str, bool]:
        try:
            raw_message = self.gmail_client.get_message(gmail_message_id)
        except HttpError as e:
            if getattr(e, "resp", None) is not None and e.resp.status == 404:
                print(f"[WARN] Gmail message not found, skipping: {gmail_message_id}")
                return None
            raise
        email_data = parse_message(raw_message)

        if email_data.subject and email_data.subject.startswith("Email importante:"):
            LOGGER.info("Email generado por la app, se omite: %s", email_data.subject)
            return {"processed": False, "important": False, "notified": False}

        if "SENT" in (email_data.labels or []):
            LOGGER.info("Email enviado por mí, se omite: %s", email_data.subject)
            return {"processed": False, "important": False, "notified": False}

        if self.db.is_processed(email_data.gmail_message_id, email_data.rfc_message_id):
            LOGGER.info("Email ya procesado, se omite: %s", email_data.gmail_message_id)
            return {"processed": False, "important": False, "notified": False}

        classification = classifier.classify(email_data, preferences)
        should_alert = classification.is_important and classification.importance_score >= self.settings.importance_threshold

        self.db.save_processed_email(
            {
                "gmail_message_id": email_data.gmail_message_id,
                "rfc_message_id": email_data.rfc_message_id,
                "thread_id": email_data.thread_id,
                "sender": email_data.sender,
                "subject": email_data.subject,
                "message_date": email_data.message_date,
                "history_id": email_data.history_id,
                "importance_score": classification.importance_score,
                "is_important": classification.is_important,
                "should_notify_now": classification.should_notify_now,
                "category": classification.category,
                "urgency": classification.urgency,
                "summary": classification.summary,
                "why_it_matters": classification.why_it_matters,
                "action_needed": classification.action_needed,
                "deadline": classification.deadline,
                "raw_labels": email_data.labels,
            }
        )

        notified = False

        if should_alert and getattr(self.settings, "ntfy_topic", ""):
            ntfy_title = f"Email importante: {email_data.subject}"
            ntfy_message = (
                f"De: {email_data.sender}\n"
                f"Score: {classification.importance_score}/10\n"
                f"Urgencia: {classification.urgency}\n\n"
                f"Resumen: {classification.summary}\n\n"
                f"Acción: {classification.action_needed}"
            )
            reply_url = ""
            if self.settings.public_base_url and self.settings.reply_signing_secret:
                base_url = self.settings.public_base_url.rstrip("/")
                query = urlencode(
                    build_signed_reply_params(
                        secret=self.settings.reply_signing_secret,
                        message_id=email_data.gmail_message_id,
                        ttl_seconds=self.settings.reply_action_ttl_seconds,
                    )
                )
                reply_url = f"{base_url}/reply-ai?{query}"

            send_ntfy(
                topic=self.settings.ntfy_topic,
                title=ntfy_title[:120],
                message=ntfy_message,
                priority="high",
                actions=f"http,Responder IA,{reply_url}" if reply_url else None,
            )
            notified = True
            LOGGER.info("Push ntfy enviado para email %s", email_data.gmail_message_id)

        if should_alert and self.settings.digest_to_email:
            mime_message = build_digest_email(
                to_email=self.settings.digest_to_email,
                analyzed_email=email_data,
                result={
                    "is_important": classification.is_important,
                    "importance_score": classification.importance_score,
                    "category": classification.category,
                    "urgency": classification.urgency,
                    "summary": classification.summary,
                    "why_it_matters": classification.why_it_matters,
                    "action_needed": classification.action_needed,
                    "deadline": classification.deadline,
                    "should_notify_now": classification.should_notify_now,
                },
            )
            if self.db.save_notification(email_data.gmail_message_id, self.settings.digest_to_email, mime_message["Subject"]):
                encoded = self.gmail_client.encode_message(mime_message.as_bytes())
                self.gmail_client.send_email(encoded)
                notified = True
                LOGGER.info("Alerta enviada para email %s", email_data.gmail_message_id)

        return {"processed": True, "important": classification.is_important, "notified": notified}

    def run_history_once(self) -> dict[str, int]:
        last_history_id = self.db.get_state("last_history_id")
        if not last_history_id:
            raise RuntimeError("No existe last_history_id. Ejecuta primero `python manage.py setup-watch`.")
        return self._process_incremental_history(last_history_id)
