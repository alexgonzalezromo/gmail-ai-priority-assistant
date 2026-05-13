# Gmail AI Priority Assistant

Este proyecto es un servicio pequeño y event-driven que vigila una bandeja de Gmail, recupera solo los mensajes nuevos, estima su importancia con OpenAI y avisa únicamente cuando de verdad hay algo que merece atención.

La idea de fondo es bastante simple: la mayoría de herramientas de correo están pensadas para leer más emails; esta está pensada para decidir cuáles pueden esperar.

## Cómo funciona

```text
Gmail users.watch()
  -> Google Cloud Pub/Sub
  -> webhook FastAPI
  -> Gmail History API
  -> parseo del mensaje
  -> clasificación con OpenAI
  -> aviso por email y/o ntfy
  -> borrador opcional de respuesta con IA
```

El sistema no hace polling de la bandeja. Gmail empuja un evento, el webhook lo acepta, el procesador consulta el histórico incremental desde el último `historyId` conocido y solo entonces descarga y clasifica los mensajes realmente nuevos.

Si un correo supera el umbral de importancia, la aplicación puede:

- enviar un aviso por email
- lanzar una notificación por `ntfy`
- preparar un borrador de respuesta en Gmail, sin enviar nada automáticamente

## Por qué tiene sentido este proyecto

Hay formas mucho más rápidas de montar una demo con Gmail y OpenAI. Lo interesante aquí no es solo conectar APIs, sino resolver bien las partes incómodas:

- ingesta push en lugar de polling
- estado incremental con Gmail History API
- deduplicación y tolerancia a reprocesados
- persistencia local con una huella pequeña
- cuidado real con secretos, tokens y datos personales en un repo público

Eso lo acerca más a un proyecto de sistemas útil que a una demo puntual.

## Stack

- Python 3.10+
- FastAPI
- Uvicorn
- Gmail API
- Google Cloud Pub/Sub
- OpenAI API
- SQLite
- `python-dotenv`
- `PyYAML`
- `systemd`

## Funcionalidades

- Ingesta push de Gmail sin bucle de polling.
- Procesamiento incremental a través de Gmail History API.
- Estado local en SQLite para deduplicación y recuperación.
- Clasificación de importancia con OpenAI.
- Alertas opcionales por `ntfy` para correos prioritarios.
- Borradores de respuesta generados con IA.
- Despliegue sencillo en un VPS pequeño, sin Docker.

## Estructura del proyecto

```text
gmail_push_importance_digest/
|-- gmail_push_importance_digest/
|   |-- ai_reply.py
|   |-- app.py
|   |-- classifier.py
|   |-- cli.py
|   |-- config.py
|   |-- db.py
|   |-- email_utils.py
|   |-- gmail_client.py
|   |-- logging_utils.py
|   |-- ntfy.py
|   |-- preferences.py
|   |-- processor.py
|   |-- reply_auth.py
|   |-- schemas.py
|   `-- webhook.py
|-- data/
|   `-- .gitkeep
|-- systemd/
|-- .env.example
|-- preferences.example.yaml
|-- manage.py
|-- pyproject.toml
`-- README.md
```

## Puesta en marcha local

### 1. Crear el entorno

En Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

En Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Crear los ficheros locales

```bash
cp .env.example .env
cp preferences.example.yaml preferences.yaml
```

Ficheros de runtime que deben quedarse en local:

- `credentials.json`
- `token.json`
- opcionalmente `personal_style.md`

### 3. Inicializar y autenticar

```bash
python manage.py init-db
python manage.py auth-gmail
python manage.py setup-watch
```

### 4. Levantar la API

```bash
uvicorn gmail_push_importance_digest.app:app --host 0.0.0.0 --port 8000
```

## Configuración

Todo lo sensible va en `.env`, nunca en el repositorio.

```env
OPENAI_API_KEY=
DIGEST_TO_EMAIL=
GOOGLE_CLOUD_PROJECT=
PUBSUB_TOPIC=
PUBSUB_SUBSCRIPTION=
WEBHOOK_SECRET=
PUBSUB_PUSH_TOKEN=
NTFY_TOPIC=
PUBLIC_BASE_URL=https://your-public-domain.example
REPLY_ACTION_SECRET=
REPLY_ACTION_TTL_SECONDS=900
ALLOW_LEGACY_REPLY_TOKEN=false
DATABASE_PATH=./data/app.db
PREFERENCES_PATH=./preferences.yaml
GMAIL_CREDENTIALS_FILE=./credentials.json
GMAIL_TOKEN_FILE=./token.json
PERSONAL_STYLE_PATH=./personal_style.md
IMPORTANCE_THRESHOLD=70
MAX_EMAILS_PER_EVENT=10
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
```

Notas:

- `PUBSUB_TOPIC` puede ser un nombre corto o una ruta completa `projects/.../topics/...`.
- `PUBSUB_SUBSCRIPTION` puede ser un nombre corto o una ruta completa `projects/.../subscriptions/...`.
- `PUBLIC_BASE_URL` solo hace falta si quieres acciones de respuesta clicables.
- `REPLY_ACTION_SECRET` permite firmar enlaces de respuesta con un secreto dedicado.
- `ALLOW_LEGACY_REPLY_TOKEN=false` deja desactivado por defecto el antiguo token fijo en query string.

## Preferencias

`preferences.yaml` se queda fuera de Git y debe mantenerse en local.

`preferences.example.yaml` sirve como plantilla para definir cosas como:

- remitentes importantes
- remitentes ignorados
- palabras clave importantes
- tono preferido

## Comandos CLI

```bash
python manage.py init-db
python manage.py auth-gmail
python manage.py setup-watch
python manage.py renew-watch
python manage.py test-read <gmail_message_id>
python manage.py test-classify <gmail_message_id>
python manage.py test-send owner@example.com --subject "Test" --body "Hello"
python manage.py run-history-once
python manage.py show-state
python manage.py list-important --limit 20
```

## Seguridad y privacidad

Este repositorio está pensado para ser seguro como código público, no como volcado de datos de ejecución.

Se ignoran a propósito:

- `.env`
- `.env.*`
- credenciales OAuth
- tokens de Gmail
- bases de datos SQLite
- logs y backups
- preferencias locales
- ficheros de estilo personal

Medidas aplicadas en la implementación actual:

- los secretos se cargan desde variables de entorno o ficheros locales
- el webhook valida el secreto compartido
- se puede validar la subscription esperada de Pub/Sub
- el estado de ejecución vive en SQLite local
- las acciones de respuesta usan enlaces firmados y con expiración en lugar de una URL con secreto permanente

Nota operativa:

En cuanto ejecutes la app con una bandeja real, la base de datos local almacenará remitentes, asuntos, resúmenes y metadatos reales. Ese contenido debe quedarse en local y no debe versionarse nunca.

Si alguna credencial real estuvo expuesta en una revisión pública anterior, hay que rotarla aunque el repositorio actual ya esté limpio.

## Flujo de respuesta

`/reply-ai` crea un borrador en Gmail. No envía correos automáticamente.

Modelo de autenticación actual:

- preferido: enlaces firmados y de vida corta
- soportado: cabecera `x-webhook-secret`
- legado opcional: `?token=` solo si `ALLOW_LEGACY_REPLY_TOKEN=true`

Así se mantiene el flujo cómodo de tocar y generar borrador, sin publicar un secreto fijo en la URL.

## Despliegue

El repositorio incluye plantillas `systemd` para un despliegue simple en VPS.

Antes de usarlas:

1. Sustituye `YOUR_APP_USER`.
2. Sustituye `/srv/gmail_push_importance_digest` por la ruta real del servidor.
3. Asegúrate de que `.env` existe en esa ruta.

Instalación típica:

```bash
sudo cp systemd/gmail-push-web.service /etc/systemd/system/
sudo cp systemd/gmail-watch-renew.service /etc/systemd/system/
sudo cp systemd/gmail-watch-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gmail-push-web.service
sudo systemctl enable --now gmail-watch-renew.timer
```

Logs útiles:

```bash
sudo journalctl -u gmail-push-web.service -f
sudo journalctl -u gmail-watch-renew.service -f
```

## Notas sobre Google Cloud

Para usar el proyecto necesitas:

1. un proyecto de Google Cloud
2. Gmail API habilitada
3. Pub/Sub API habilitada
4. un cliente OAuth para Gmail
5. un topic de Pub/Sub al que Gmail pueda publicar
6. una push subscription apuntando al webhook público

Endpoint típico del webhook:

```text
POST /webhooks/gmail
```

## Roadmap

- validación OIDC para pushes de Pub/Sub
- mejor redacción de logs sensibles
- worker opcional para mayor volumen
- tests automáticos sobre validación del webhook e histórico
- filtros y preferencias más ricos

## Disclaimer

Este repositorio no versiona:

- claves API reales
- secretos OAuth
- refresh tokens
- datos reales de correo
- bases de datos de producción
- ficheros locales de preferencias

Si lo usas como base, genera tus propias credenciales y mantén los datos operativos fuera de Git desde el primer día.
