from email.mime.text import MIMEText
from email.utils import parseaddr
from openai import OpenAI


def generate_reply(
    openai_api_key: str,
    original_subject: str,
    original_sender: str,
    original_body: str,
    persona_name: str,
    style_path,
) -> str:
    style = ""
    if style_path.exists():
        style = style_path.read_text(encoding="utf-8")

    client = OpenAI(api_key=openai_api_key)

    prompt = f"""
Eres {persona_name} respondiendo emails.

ESTILO PERSONAL:
{style}

EMAIL ORIGINAL:
De: {original_sender}
Asunto: {original_subject}

Contenido:
{original_body}

INSTRUCCIONES:
- Responde como {persona_name}.
- Natural y humano.
- No sonar como IA.
- Breve y útil.
- Responde SIEMPRE en español de España.
- Aunque el email original esté en inglés, responde en español salvo que explícitamente pidan inglés.
- Devuelve SOLO el cuerpo de la respuesta.
"""

    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )

    return response.output_text.strip()


def build_reply_message(to_email: str, subject: str, body: str, thread_id: str | None = None):
    msg = MIMEText(body)

    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    msg["To"] = parseaddr(to_email)[1] or to_email
    msg["Subject"] = subject

    return msg
