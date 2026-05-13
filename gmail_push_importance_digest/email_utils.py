from __future__ import annotations

import base64
import html
import logging
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup

from gmail_push_importance_digest.schemas import EmailContent


LOGGER = logging.getLogger(__name__)
MAX_MODEL_CHARS = 8000


def _decode_part(data: str | None) -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data.encode("utf-8"))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        LOGGER.warning("No se pudo decodificar una parte MIME")
        return ""


def _walk_parts(payload: dict[str, Any]) -> tuple[str, str]:
    plain_chunks: list[str] = []
    html_chunks: list[str] = []

    def _visit(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if mime_type == "text/plain":
            plain_chunks.append(_decode_part(body_data))
        elif mime_type == "text/html":
            html_chunks.append(_decode_part(body_data))
        for child in part.get("parts", []) or []:
            _visit(child)

    _visit(payload)
    return "\n".join(plain_chunks).strip(), "\n".join(html_chunks).strip()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return soup.get_text("\n", strip=True)


def strip_signature_and_noise(text: str) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    stop_markers = ("--", "unsubscribe", "manage preferences", "sent from my iphone", "este correo")
    for line in lines:
        lower = line.lower()
        if any(marker in lower for marker in stop_markers):
            break
        if line:
            cleaned.append(line)
    merged = "\n".join(cleaned)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    return merged[:MAX_MODEL_CHARS]


def parse_headers(headers: list[dict[str, str]]) -> dict[str, str]:
    return {item["name"].lower(): item["value"] for item in headers}


def parse_message(message: dict[str, Any]) -> EmailContent:
    payload = message.get("payload", {})
    headers = parse_headers(payload.get("headers", []))
    plain_text, html_text = _walk_parts(payload)
    if not plain_text:
        plain_text = html_to_text(html_text)
    cleaned_body = strip_signature_and_noise(plain_text or message.get("snippet", ""))

    date_header = headers.get("date")
    parsed_date = None
    if date_header:
        try:
            parsed_date = parsedate_to_datetime(date_header)
        except Exception:
            parsed_date = None
    if parsed_date and parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    return EmailContent(
        gmail_message_id=message["id"],
        thread_id=message.get("threadId", ""),
        history_id=message.get("historyId"),
        rfc_message_id=headers.get("message-id"),
        sender=headers.get("from", ""),
        subject=headers.get("subject", "(sin asunto)"),
        message_date=date_header,
        snippet=message.get("snippet", ""),
        plain_text=cleaned_body,
        labels=message.get("labelIds", []),
        internal_ts=parsed_date,
    )


def build_digest_email(
    to_email: str,
    analyzed_email: EmailContent,
    result: dict[str, Any],
) -> EmailMessage:
    subject = f"Email importante: {analyzed_email.subject}"
    deadline = result.get("deadline") or "Sin deadline detectado"
    text_body = (
        f"Remitente: {analyzed_email.sender}\n"
        f"Asunto: {analyzed_email.subject}\n"
        f"Fecha: {analyzed_email.message_date or 'desconocida'}\n\n"
        f"Resumen: {result.get('summary', '')}\n"
        f"Por que importa: {result.get('why_it_matters', '')}\n"
        f"Accion recomendada: {result.get('action_needed', '')}\n"
        f"Deadline: {deadline}\n"
        f"Urgencia: {result.get('urgency', 'unknown')}\n"
        f"Categoria: {result.get('category', 'other')}\n"
        f"Referencia Gmail Message ID: {analyzed_email.gmail_message_id}\n"
    )
    html_body = f"""
    <html>
      <body>
        <h2>Email importante detectado</h2>
        <p><strong>Remitente:</strong> {html.escape(analyzed_email.sender)}</p>
        <p><strong>Asunto:</strong> {html.escape(analyzed_email.subject)}</p>
        <p><strong>Fecha:</strong> {html.escape(analyzed_email.message_date or 'desconocida')}</p>
        <p><strong>Resumen:</strong> {html.escape(result.get('summary', ''))}</p>
        <p><strong>Por qu&eacute; importa:</strong> {html.escape(result.get('why_it_matters', ''))}</p>
        <p><strong>Acci&oacute;n recomendada:</strong> {html.escape(result.get('action_needed', ''))}</p>
        <p><strong>Deadline:</strong> {html.escape(deadline)}</p>
        <p><strong>Urgencia:</strong> {html.escape(result.get('urgency', 'unknown'))}</p>
        <p><strong>Categor&iacute;a:</strong> {html.escape(result.get('category', 'other'))}</p>
        <p><strong>Referencia Gmail Message ID:</strong> {html.escape(analyzed_email.gmail_message_id)}</p>
      </body>
    </html>
    """
    message = EmailMessage()
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def truncate_for_model(text: str, limit: int = MAX_MODEL_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit]
