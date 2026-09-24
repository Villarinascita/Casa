"""Worker persistente: Telegram, interpretazione Hermes e promemoria."""

import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .calendar_sync import push_local_event, sync_calendar
from .config import settings
from .db import SessionLocal
from .gmail_sync import sync_gmail
from .google import GoogleService
from .hermes_client import HermesClient
from .models import Event, GoogleCalendar, GoogleConnection, Household, WorkerCursor
from .reminders import dispatch_pending, enqueue_due
from .telegram import process_update

logger = logging.getLogger(__name__)


def run_google_once(db: Session, service: GoogleService, hermes_email: HermesClient, now: datetime) -> None:
    """Isola gli errori di ogni account; riprova al giro successivo."""
    for connection in db.scalars(select(GoogleConnection)).all():
        try:
            if connection.last_gmail_sync_at is None or (now - connection.last_gmail_sync_at).total_seconds() >= 600:
                timezone_name = db.get(Household, connection.household_id).timezone
                sync_gmail(db, connection, service,
                           lambda text: hermes_email.analyze_email(text, timezone_name, settings.hermes_email_model), now)
            calendars = db.scalars(select(GoogleCalendar).where(GoogleCalendar.connection_id == connection.id)).all()
            if not calendars:
                continue
            if any(c.last_synced_at is None or (now - c.last_synced_at).total_seconds() >= 600 for c in calendars):
                for calendar in calendars:
                    if calendar.last_synced_at is None or (now - calendar.last_synced_at).total_seconds() >= 600:
                        sync_calendar(db, connection, calendar, service, now)
                events = db.scalars(select(Event).where(Event.household_id == connection.household_id)).all()
                for event in events:
                    push_local_event(db, connection, event, service)
            connection.last_error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            connection = db.get(GoogleConnection, connection.id)
            connection.last_error = str(exc)[:500]
            db.commit()
            logger.exception("Sincronizzazione Google fallita per %s", connection.email)


class TelegramApi:
    def __init__(self, token: str, stt_url: str = "", stt_api_key: str = "", stt_model: str = "",
                 client: httpx.Client | None = None):
        self.token = token
        self.stt_url = stt_url
        self.stt_api_key = stt_api_key
        self.stt_model = stt_model
        self.client = client or httpx.Client(timeout=35)
        self.base = f"https://api.telegram.org/bot{token}"

    def _post(self, method: str, data: dict) -> dict:
        response = self.client.post(f"{self.base}/{method}", json=data)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram {method} non riuscito")
        return payload["result"]

    def get_updates(self, offset: int) -> list[dict]:
        return self._post("getUpdates", {"offset": offset, "timeout": 15, "allowed_updates": ["message"]})

    def send(self, chat_id: str, text: str) -> None:
        self._post("sendMessage", {"chat_id": chat_id, "text": text[:4096]})

    def transcribe(self, file_id: str) -> str:
        if not self.stt_url or not self.stt_api_key:
            raise RuntimeError("Trascrizione vocale non configurata")
        file_info = self._post("getFile", {"file_id": file_id})
        if file_info.get("file_size", 0) > 20_000_000:
            raise RuntimeError("Messaggio vocale troppo grande")
        audio = self.client.get(f"https://api.telegram.org/file/bot{self.token}/{file_info['file_path']}")
        audio.raise_for_status()
        result = self.client.post(self.stt_url, headers={"Authorization": f"Bearer {self.stt_api_key}"},
                                  data={"model": self.stt_model, "language": "it"},
                                  files={"file": ("voice.ogg", audio.content, "audio/ogg")})
        result.raise_for_status()
        return result.json()["text"].strip()


def run_once(db: Session, messenger, interpret, now: datetime) -> None:
    enqueue_due(db, now)
    dispatch_pending(db, messenger.send, now)
    cursor = db.get(WorkerCursor, "telegram")
    if cursor is None:
        cursor = WorkerCursor(name="telegram", value=0)
        db.add(cursor)
        db.commit()
    for update in messenger.get_updates(cursor.value):
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") == "private":
            if message.get("voice"):
                try:
                    message["text"] = messenger.transcribe(message["voice"]["file_id"])
                except Exception:
                    logger.exception("Trascrizione Telegram fallita")
                    messenger.send(str(chat["id"]), "Non riesco a trascrivere il vocale. Riprova o scrivi il messaggio.")
                    cursor.value = update["update_id"] + 1
                    db.commit()
                    continue
            reply = process_update(db, update, interpret)
            messenger.send(str(chat["id"]), reply)
        cursor.value = update["update_id"] + 1
        db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.telegram_bot_token:
        raise RuntimeError("INSIEME_TELEGRAM_BOT_TOKEN mancante")
    messenger = TelegramApi(settings.telegram_bot_token, settings.stt_url,
                            settings.stt_api_key, settings.stt_model)
    hermes = HermesClient(settings.hermes_url, settings.hermes_api_key, settings.hermes_model)
    hermes_email = HermesClient(settings.hermes_email_url or settings.hermes_url,
                                settings.hermes_email_api_key or settings.hermes_api_key,
                                settings.hermes_email_model)
    google = None
    if all((settings.public_url, settings.google_client_id, settings.google_client_secret,
            settings.google_token_key)):
        google = GoogleService(settings.google_client_id, settings.google_client_secret,
                               settings.public_url.rstrip("/") + "/api/v1/connections/google/callback",
                               settings.google_token_key)
    while True:
        try:
            with SessionLocal() as db:
                def interpret(text, ctx):
                    timezone_name = db.get(Household, ctx.household_id).timezone
                    return hermes.interpret(text, ctx, timezone_name)
                run_once(db, messenger, interpret, datetime.now(timezone.utc))
                if google:
                    run_google_once(db, google, hermes_email, datetime.now(timezone.utc))
        except Exception:
            logger.exception("Ciclo del worker fallito; nuovo tentativo tra 15 secondi")
            time.sleep(15)


if __name__ == "__main__":
    main()
