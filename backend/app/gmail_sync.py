"""Estrazione di proposte Gmail senza conservare il testo integrale dei messaggi."""

import base64
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .hermes_client import HermesInvalidResponse
from .models import EmailProcessed, GoogleConnection, Proposal
from .routers.assistant import ACTION_TYPES
from .schemas import ActionBatchIn


def _body_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/html":
        return ""
    if payload.get("body", {}).get("data"):
        encoded = payload["body"]["data"]
        try:
            return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return ""
    return "\n".join(filter(None, (_body_text(part) for part in payload.get("parts", []))))


def ingest_message(db: Session, connection: GoogleConnection, message: dict,
                   analyze: Callable[[str], dict]) -> int:
    message_id = message["id"]
    seen = db.scalar(select(EmailProcessed).where(EmailProcessed.connection_id == connection.id,
                                                   EmailProcessed.message_id == message_id))
    if seen:
        return 0
    headers = {item.get("name", "").lower(): item.get("value", "")
               for item in message.get("payload", {}).get("headers", [])}
    sender = headers.get("from", "")[:320]
    subject = headers.get("subject", "")[:500]
    snippet = message.get("snippet", "")[:500]
    body = _body_text(message.get("payload", {}))[:12000] or snippet
    try:
        result = analyze(f"Da: {sender}\nOggetto: {subject}\nTesto: {body}")
        actions = result.get("actions") or []
        batch = ActionBatchIn.model_validate({"actions": actions}) if actions else None
        if batch:
            for index, action in enumerate(batch.actions):
                schema, _ = ACTION_TYPES[action.kind]
                data = schema.model_validate(action.data).model_dump(mode="json")
                db.add(Proposal(household_id=connection.household_id, created_by=connection.user_id,
                                connection_id=connection.id, message_id=message_id,
                                thread_id=message.get("threadId", ""), item_index=index,
                                sender=sender, subject=subject, snippet=snippet,
                                kind=action.kind, data=data))
    except (HermesInvalidResponse, ValidationError, KeyError):
        # Il modello ha risposto con qualcosa di inutilizzabile per questo messaggio: si
        # segna comunque come processato, altrimenti il worker lo ritenterebbe a ogni giro.
        db.rollback()
        actions = []
    db.add(EmailProcessed(connection_id=connection.id, message_id=message_id))
    db.commit()
    return len(actions)


def sync_gmail(db: Session, connection: GoogleConnection, service,
               analyze: Callable[[str], dict], now: datetime | None = None) -> int:
    """Scorre i messaggi che corrispondono ai filtri; riprende dalle pagine incomplete."""
    now = now or datetime.now(timezone.utc)
    since = connection.last_gmail_sync_at - timedelta(days=1) if connection.last_gmail_sync_at else now - timedelta(days=365)
    query = f"{connection.gmail_query} after:{since:%Y/%m/%d}".strip()
    params = {"q": query, "maxResults": 50}
    if connection.gmail_page_token:
        params["pageToken"] = connection.gmail_page_token
    token = service.access_token(connection)
    page = service.api.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", token, params)
    proposals = 0
    for item in page.get("messages", []):
        message = service.api.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}", token,
            {"format": "full"})
        proposals += ingest_message(db, connection, message, analyze)
    connection.gmail_page_token = page.get("nextPageToken")
    if not connection.gmail_page_token:
        connection.last_gmail_sync_at = now
    connection.last_error = None
    db.commit()
    return proposals
