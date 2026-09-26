"""Pulizia retroattiva delle email dei domini bloccati (cestino Gmail, mai cancellazione)."""

import json
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


RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
RATE_LIMIT_DETAIL_REASONS = {"RATE_LIMIT_EXCEEDED"}


def _is_permission_denied(response: httpx.Response) -> bool:
    """Vero se il 403 indica scope/permesso insufficiente (non un rate limit)."""
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        return True  # corpo non interpretabile: per prudenza si tratta come permesso mancante
    error = body.get("error", {}) if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        return False
    # Il rate limit va controllato per primo: un 403 con status PERMISSION_DENIED ma
    # reason di rate limit non è un permesso mancante, va ritentato.
    for item in error.get("errors") or []:
        if isinstance(item, dict) and item.get("reason") in RATE_LIMIT_REASONS:
            return False
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason") in RATE_LIMIT_DETAIL_REASONS:
            return False
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason") == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
            return True
    for item in error.get("errors") or []:
        if isinstance(item, dict) and item.get("reason") == "insufficientPermissions":
            return True
    # Nessuna reason riconosciuta: un 403 PERMISSION_DENIED "nudo" si tratta per prudenza
    # come permesso mancante (mostra solo un avviso e ritenta).
    return error.get("status") == "PERMISSION_DENIED"


def trash_message(service, token: str, message_id: str) -> bool:
    """Sposta un'email nel cestino di Gmail (recuperabile 30 giorni). Mai cancellazione permanente.

    Ritorna True se l'email è stata effettivamente spostata, False se era già sparita (404).
    """
    try:
        service.api.post(f"{GMAIL_MESSAGES}/{message_id}/trash", token, {})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            if _is_permission_denied(exc.response):
                raise TrashNotPermitted(TRASH_PERMISSION_MESSAGE) from exc
            raise  # es. rateLimitExceeded: si ritenta, non è un permesso mancante
        if exc.response.status_code == 404:
            return False  # già sparita: niente da fare
        raise
    return True


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
        except Exception:
            db.rollback()
            logger.exception("Pulizia del dominio %s interrotta; riprova al prossimo giro", row.domain)
            continue

        page_trashed = 0
        page_failed = False
        permission_denied = False
        for item in page.get("messages", []):
            try:
                # La ricerca Gmail «from:» è per sottostringa: si verifica il dominio esatto.
                if not is_blocked_sender(_sender(service, token, item["id"]), [row.domain]):
                    continue
                moved_now = trash_message(service, token, item["id"])
            except TrashNotPermitted:
                connection.last_error = TRASH_PERMISSION_MESSAGE
                if page_trashed:
                    # Sono già state spostate email in questa pagina: si rispetta comunque la
                    # regola "trashed >= 1 -> riparte dall'inizio" nonostante il permesso negato.
                    row.page_token = None
                db.commit()
                permission_denied = True
                break
            except Exception:
                db.rollback()
                page_failed = True
                logger.warning("Errore sul messaggio %s del dominio %s; si continua con gli altri",
                               item["id"], row.domain, exc_info=True)
                continue
            if moved_now:
                row.trashed_count += 1
                page_trashed += 1
                moved += 1
            db.commit()

        if permission_denied:
            continue

        if page_trashed:
            # Sono state spostate email in questa pagina: si riparte dall'inizio al prossimo giro
            # per non saltare messaggi con un set di risultati che si è ristretto.
            row.page_token = None
        elif page_failed:
            # Nessun successo ma almeno un fallimento non-permesso (es. 429/5xx transitorio):
            # si ritenta la stessa pagina al prossimo giro, senza seguire nextPageToken né
            # marcare la pulizia come conclusa.
            pass
        else:
            next_token = page.get("nextPageToken")
            if next_token:
                row.page_token = next_token
            else:
                row.status, row.completed_at = "done", now
        db.commit()
    return moved
