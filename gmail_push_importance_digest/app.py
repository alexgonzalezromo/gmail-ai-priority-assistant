from __future__ import annotations

import logging
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from gmail_push_importance_digest import __version__
from gmail_push_importance_digest.config import get_settings
from gmail_push_importance_digest.db import Database
from gmail_push_importance_digest.gmail_client import GmailClient
from gmail_push_importance_digest.logging_utils import configure_logging
from gmail_push_importance_digest.processor import GmailEventProcessor

from gmail_push_importance_digest.ai_reply import (
    generate_reply,
    build_reply_message,
)
from gmail_push_importance_digest.email_utils import parse_message
from gmail_push_importance_digest.ntfy import send_ntfy
from gmail_push_importance_digest.reply_auth import validate_signed_reply_params

from gmail_push_importance_digest.webhook import (
    decode_pubsub_payload,
    validate_pubsub_subscription,
    validate_webhook_secret,
)


settings = get_settings()
configure_logging(settings.log_level)
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="Gmail AI Priority Assistant", version=__version__)


def _build_processor() -> GmailEventProcessor:
    db = Database(settings.database_path)
    db.init_db()
    gmail_client = GmailClient(settings.gmail_credentials_file, settings.gmail_token_file)
    return GmailEventProcessor(settings, db, gmail_client)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/gmail")
async def gmail_webhook(request: Request, background_tasks: BackgroundTasks, token: str | None = None):
    validate_webhook_secret(request, settings.webhook_secret, token)
    body = await request.json()
    decoded_event = decode_pubsub_payload(body)
    validate_pubsub_subscription(decoded_event.get("subscription"), settings.pubsub_subscription_path)

    def _process() -> None:
        processor = _build_processor()
        summary = processor.process_pubsub_notification(decoded_event)
        LOGGER.info("Webhook procesado: %s", summary)

    background_tasks.add_task(_process)
    return JSONResponse({"status": "accepted"})


@app.api_route("/reply-ai", methods=["GET", "POST"])
def reply_ai(
    message_id: str,
    expires: Annotated[int | None, Query()] = None,
    sig: str | None = None,
    token: str | None = None,
    x_webhook_secret: str | None = Header(default=None),
):
    if x_webhook_secret:
        if x_webhook_secret != settings.webhook_secret:
            raise HTTPException(status_code=401, detail="invalid token")
    elif expires is not None and sig:
        if not settings.reply_signing_secret or not validate_signed_reply_params(
            secret=settings.reply_signing_secret,
            message_id=message_id,
            expires=expires,
            signature=sig,
        ):
            raise HTTPException(status_code=401, detail="invalid or expired signature")
    elif settings.allow_legacy_reply_token and token:
        if token != settings.webhook_secret:
            raise HTTPException(status_code=401, detail="invalid token")
    else:
        raise HTTPException(status_code=401, detail="invalid token")

    processor = _build_processor()

    raw = processor.gmail_client.get_message(message_id)
    parsed = parse_message(raw)

    reply_text = generate_reply(
        openai_api_key=settings.openai_api_key,
        original_subject=parsed.subject,
        original_sender=parsed.sender,
        original_body=(
            getattr(parsed, "body_text", None)
            or getattr(parsed, "plain_text", None)
            or getattr(parsed, "text", None)
            or getattr(parsed, "snippet", None)
            or ""
        )[:4000],
        persona_name=settings.reply_persona_name,
        style_path=settings.personal_style_path,
    )

    mime = build_reply_message(
        to_email=parsed.sender,
        subject=parsed.subject,
        body=reply_text,
        thread_id=parsed.thread_id,
    )

    encoded = processor.gmail_client.encode_message(mime.as_bytes())

    draft = processor.gmail_client.create_draft(encoded)

    if getattr(settings, "ntfy_topic", ""):
        send_ntfy(
            topic=settings.ntfy_topic,
            title="Borrador IA creado",
            message=f"Se ha creado un borrador para responder a: {parsed.subject}",
            priority="default",
        )

    return {
        "status": "draft_created",
        "draft_id": draft.get("id"),
    }
