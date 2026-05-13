from __future__ import annotations

import argparse
import json
from pprint import pprint

from gmail_push_importance_digest.classifier import ImportanceClassifier
from gmail_push_importance_digest.config import get_settings
from gmail_push_importance_digest.db import Database
from gmail_push_importance_digest.gmail_client import GmailClient
from gmail_push_importance_digest.logging_utils import configure_logging
from gmail_push_importance_digest.preferences import load_preferences
from gmail_push_importance_digest.processor import GmailEventProcessor
from gmail_push_importance_digest.email_utils import parse_message


def _deps():
    settings = get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.database_path)
    gmail = GmailClient(settings.gmail_credentials_file, settings.gmail_token_file)
    processor = GmailEventProcessor(settings, db, gmail)
    return settings, db, gmail, processor


def cmd_init_db(_: argparse.Namespace) -> int:
    _, db, _, _ = _deps()
    db.init_db()
    print(f"Base de datos inicializada en {db.db_path}")
    return 0


def cmd_auth_gmail(_: argparse.Namespace) -> int:
    _, _, gmail, _ = _deps()
    gmail.authenticate_interactive()
    print("Autenticación Gmail completada. token.json guardado.")
    return 0


def cmd_setup_watch(_: argparse.Namespace) -> int:
    settings, db, _, processor = _deps()
    db.init_db()
    result = processor.renew_watch(reset_history_id=True)
    print(json.dumps(result, indent=2))
    print(f"Topic configurado: {settings.pubsub_topic_path}")
    return 0


def cmd_renew_watch(_: argparse.Namespace) -> int:
    _, _, _, processor = _deps()
    result = processor.renew_watch(reset_history_id=False)
    print(json.dumps(result, indent=2))
    return 0


def cmd_test_read(args: argparse.Namespace) -> int:
    _, _, gmail, _ = _deps()
    message = gmail.get_message(args.message_id)
    parsed = parse_message(message)
    pprint(parsed.__dict__)
    return 0


def cmd_test_classify(args: argparse.Namespace) -> int:
    settings, _, gmail, _ = _deps()
    message = gmail.get_message(args.message_id)
    parsed = parse_message(message)
    preferences = load_preferences(settings.preferences_path)
    classifier = ImportanceClassifier(settings.openai_api_key, settings.gmail_model)
    result = classifier.classify(parsed, preferences)
    pprint(result.__dict__)
    return 0


def cmd_test_send(args: argparse.Namespace) -> int:
    _, _, gmail, _ = _deps()
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = args.to_email
    msg["Subject"] = args.subject
    msg.set_content(args.body)
    gmail.send_email(gmail.encode_message(msg.as_bytes()))
    print("Email de prueba enviado.")
    return 0


def cmd_run_history_once(_: argparse.Namespace) -> int:
    _, _, _, processor = _deps()
    result = processor.run_history_once()
    print(json.dumps(result, indent=2))
    return 0


def cmd_show_state(_: argparse.Namespace) -> int:
    _, db, gmail, _ = _deps()
    snapshot = db.fetch_state_snapshot()
    profile = gmail.get_profile()
    print("Estado actual:")
    pprint(snapshot)
    print("Perfil Gmail:")
    pprint(profile)
    return 0


def cmd_list_important(args: argparse.Namespace) -> int:
    _, db, _, _ = _deps()
    rows = db.list_important(limit=args.limit)
    for row in rows:
        print(
            f"[{row['processed_at']}] score={row['importance_score']} "
            f"urgency={row['urgency']} category={row['category']} "
            f"from={row['sender']} subject={row['subject']}"
        )
        print(f"  {row['summary']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    commands = {
        "init-db": cmd_init_db,
        "auth-gmail": cmd_auth_gmail,
        "setup-watch": cmd_setup_watch,
        "renew-watch": cmd_renew_watch,
        "run-history-once": cmd_run_history_once,
        "show-state": cmd_show_state,
    }
    for name, handler in commands.items():
        sub = subparsers.add_parser(name)
        sub.set_defaults(func=handler)

    test_read = subparsers.add_parser("test-read")
    test_read.add_argument("message_id")
    test_read.set_defaults(func=cmd_test_read)

    test_classify = subparsers.add_parser("test-classify")
    test_classify.add_argument("message_id")
    test_classify.set_defaults(func=cmd_test_classify)

    test_send = subparsers.add_parser("test-send")
    test_send.add_argument("to_email")
    test_send.add_argument("--subject", default="Prueba gmail_push_importance_digest")
    test_send.add_argument("--body", default="Prueba de envío desde Gmail API.")
    test_send.set_defaults(func=cmd_test_send)

    list_important = subparsers.add_parser("list-important")
    list_important.add_argument("--limit", type=int, default=20)
    list_important.set_defaults(func=cmd_list_important)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
