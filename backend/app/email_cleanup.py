"""Pulizia retroattiva delle email dei domini bloccati (cestino Gmail, mai cancellazione)."""

import logging
from collections.abc import Iterable
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .email_domains import is_blocked_sender
from .models import EmailDomainCleanup, GoogleConnection, utcnow

logger = logging.getLogger(__name__)

GMAIL_MESSAGES = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
TRASH_PERMISSION_MESSAGE = "Ricollega Google in Impostazioni per consentire lo spostamento nel cestino."


class TrashNotPermitted(Exception):
    """Gmail rifiuta il cestino (403): la connessione ha solo il permesso di lettura."""


def trash_message(service, token: str, message_id: str) -> None:
    """Sposta un'email nel cestino di Gmail (recuperabile 30 giorni). Mai cancellazione permanente."""
    try:
        service.api.post(f"{GMAIL_MESSAGES}/{message_id}/trash", token, {})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise TrashNotPermitted(TRASH_PERMISSION_MESSAGE) from exc
        if exc.response.status_code == 404:
            return  # già sparita: niente da fare
        raise


def queue_domain_cleanups(db: Session, household_id: str, previous: Iterable[str], current: Iterable[str]) -> None:
    """Avvia una pulizia per ogni dominio appena aggiunto; chiude quelle dei domini tolti."""
    previous, current = set(previous), set(current)
    connections = db.scalars(select(GoogleConnection).where(GoogleConnection.household_id == household_id)).all()
    for domain in sorted(current - previous):
        for connection in connections:
            db.add(EmailDomainCleanup(household_id=household_id, connection_id=connection.id, domain=domain))
    removed = previous - current
    if removed:
        for row in db.scalars(select(EmailDomainCleanup).where(
                EmailDomainCleanup.household_id == household_id, EmailDomainCleanup.status == "running",
                EmailDomainCleanup.domain.in_(removed))).all():
            row.status = "done"
            row.completed_at = utcnow()


def _sender(service, token: str, message_id: str) -> str:
    meta = service.api.get(f"{GMAIL_MESSAGES}/{message_id}", token,
                           {"format": "metadata", "metadataHeaders": "From"})
    return next((h.get("value", "") for h in meta.get("payload", {}).get("headers", [])
                 if h.get("name", "").lower() == "from"), "")


def run_domain_cleanups(db: Session, service, now: datetime) -> int:
    """Una pagina (max 50) per ogni pulizia in corso; ritorna quante email ha spostato nel cestino."""
    moved = 0
    for row in db.scalars(select(EmailDomainCleanup).where(EmailDomainCleanup.status == "running")).all():
        connection = db.get(GoogleConnection, row.connection_id)
        if connection is None:
            row.status, row.completed_at = "done", now
            db.commit()
            continue
        try:
            token = service.access_token(connection)
            params = {"q": f"in:inbox from:{row.domain}", "maxResults": 50}
            if row.page_token:
                params["pageToken"] = row.page_token
            page = service.api.get(GMAIL_MESSAGES, token, params)
            for item in page.get("messages", []):
                # La ricerca Gmail «from:» è per sottostringa: si verifica il dominio esatto.
                if not is_blocked_sender(_sender(service, token, item["id"]), [row.domain]):
                    continue
                trash_message(service, token, item["id"])
                row.trashed_count += 1
                moved += 1
                db.commit()
        except TrashNotPermitted:
            connection.last_error = TRASH_PERMISSION_MESSAGE
            db.commit()
            continue
        except Exception:
            db.rollback()
            logger.exception("Pulizia del dominio %s interrotta; riprova al prossimo giro", row.domain)
            continue
        row.page_token = page.get("nextPageToken")
        if not row.page_token:
            row.status, row.completed_at = "done", now
        db.commit()
    return moved
