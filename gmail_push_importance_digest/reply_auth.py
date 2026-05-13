from __future__ import annotations

import base64
import hashlib
import hmac
import time


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_reply_signature(secret: str, message_id: str, expires: int) -> str:
    payload = f"{message_id}:{expires}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _urlsafe_b64(digest)


def build_signed_reply_params(secret: str, message_id: str, ttl_seconds: int) -> dict[str, str]:
    expires = int(time.time()) + max(ttl_seconds, 60)
    return {
        "message_id": message_id,
        "expires": str(expires),
        "sig": build_reply_signature(secret, message_id, expires),
    }


def validate_signed_reply_params(secret: str, message_id: str, expires: int, signature: str) -> bool:
    if expires < int(time.time()):
        return False
    expected = build_reply_signature(secret, message_id, expires)
    return hmac.compare_digest(signature, expected)
