import requests


def send_ntfy(topic: str, title: str, message: str, priority: str = "default", actions: str | None = None):
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": "email,triage,ai",
    }

    if actions:
        headers["Actions"] = actions

    r = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
