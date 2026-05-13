from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import HTTPException, Request


def validate_webhook_secret(request: Request, expected_secret: str, query_token: str | None) -> None:
    if not expected_secret:
        return
    header_secret = request.headers.get("x-webhook-secret")
    provided = header_secret or query_token
    if provided != expected_secret:
        raise HTTPException(status_code=401, detail="Webhook secret inválido")


def validate_pubsub_subscription(subscription: str | None, expected_subscription: str) -> None:
    if not expected_subscription:
        return
    if subscription != expected_subscription:
        raise HTTPException(status_code=401, detail="Subscription Pub/Sub inválida")


def decode_pubsub_payload(body: dict[str, Any]) -> dict[str, Any]:
    if "message" not in body:
        raise HTTPException(status_code=400, detail="Payload Pub/Sub inválido")
    encoded = body["message"].get("data")
    if not encoded:
        raise HTTPException(status_code=400, detail="El evento Pub/Sub no contiene data")
    try:
        decoded_bytes = base64.b64decode(encoded)
        decoded = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="No se pudo decodificar el payload Pub/Sub") from exc
    return {"message": body["message"], "subscription": body.get("subscription"), "decoded_data": decoded}
