from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


LOGGER = logging.getLogger(__name__)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient:
    def __init__(self, credentials_file: Path, token_file: Path) -> None:
        self.credentials_file = credentials_file
        self.token_file = token_file

    def get_credentials(self) -> Credentials:
        creds: Credentials | None = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
            return creds
        if creds and creds.valid:
            return creds
        raise RuntimeError("No hay credenciales válidas. Ejecuta `python manage.py auth-gmail`.")

    def authenticate_interactive(self) -> None:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_file),
            SCOPES,
            redirect_uri="http://localhost:8080/",
        )
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true",
        )

        print("\nAbre esta URL en tu navegador:\n")
        print(auth_url)
        print("\nTras autorizar, Google intentará abrir localhost y fallará.")
        print("Copia la URL completa que queda en el navegador y pégala aquí.\n")

        redirected_url = input("URL completa: ").strip()
        flow.fetch_token(authorization_response=redirected_url)

        creds = flow.credentials
        self.token_file.write_text(creds.to_json(), encoding="utf-8")

    def service(self):
        creds = self.get_credentials()
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def watch_mailbox(self, topic_name: str, label_ids: list[str] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"topicName": topic_name}
        if label_ids:
            body["labelIds"] = label_ids
            body["labelFilterBehavior"] = "INCLUDE"
        return self.service().users().watch(userId="me", body=body).execute()

    def get_profile(self) -> dict[str, Any]:
        return self.service().users().getProfile(userId="me").execute()

    def get_message(self, message_id: str) -> dict[str, Any]:
        return (
            self.service()
            .users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def list_history(self, start_history_id: str, max_results: int = 100, page_token: str | None = None) -> dict[str, Any]:
        request = (
            self.service()
            .users()
            .history()
            .list(
                userId="me",
                startHistoryId=start_history_id,
                historyTypes=["messageAdded"],
                maxResults=max_results,
                pageToken=page_token,
            )
        )
        return request.execute()

    def list_recent_messages(self, max_results: int = 10) -> list[dict[str, Any]]:
        response = (
            self.service()
            .users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
            .execute()
        )
        return response.get("messages", [])

    def send_email(self, raw_message_b64: str) -> dict[str, Any]:
        return (
            self.service()
            .users()
            .messages()
            .send(userId="me", body={"raw": raw_message_b64})
            .execute()
        )



    def create_draft(self, raw_message_b64: str) -> dict[str, Any]:
        return (
            self.service()
            .users()
            .drafts()
            .create(
                userId="me",
                body={
                    "message": {
                        "raw": raw_message_b64
                    }
                },
            )
            .execute()
        )

    @staticmethod
    def encode_message(mime_message: bytes) -> str:
        return base64.urlsafe_b64encode(mime_message).decode("utf-8")

    @staticmethod
    def is_history_out_of_date(exc: HttpError) -> bool:
        return exc.resp.status == 404
