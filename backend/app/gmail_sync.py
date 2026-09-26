"""Estrazione da Gmail: spesa resta una Proposal da confermare; appuntamenti, attività e
bollette si creano direttamente (vedi docs/superpowers/specs/2026-09-25-bollette-costi-casa-design.md)."""

import base64
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import habits
from .bill_taxonomy import known_supplier, normalize, taxonomy_of
from .dedup import find_same_bill, find_same_event, find_same_task
from .email_cleanup import TRASH_PERMISSION_MESSAGE, TrashNotPermitted, trash_message
from .email_domains import is_blocked_sender
from .email_promotions import is_bulk_mail, is_promotion_to_trash, trashed_sender
from .hermes_client import HermesInvalidResponse
from .models import Bill, EmailAutoTrash, EmailCreationNotice, EmailProcessed, Event, GoogleConnection, Proposal
from .routers.assistant import ACTION_TYPES
from .schemas import ActionBatchIn, BillIn


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


def _creation_summary(kind: str, obj, sender: str, timezone_name: str) -> str:
    if kind == "event":
        if obj.all_day:
            when = f"il {obj.start_date:%d/%m}"
        else:
            local = obj.start_at.astimezone(ZoneInfo(timezone_name))
            when = f"il {local:%d/%m} alle {local:%H:%M}"
        return f"Ho aggiunto l'appuntamento «{obj.title}» {when}, da un'email di {sender}. Cancellalo se non era vero."
    when = f" entro il {obj.due_date:%d/%m}" if obj.due_date else ""
    return f"Ho aggiunto l'attività «{obj.title}»{when}, da un'email di {sender}. Cancellala se non era vera."


def _is_stale(model, obj, now: datetime) -> bool:
    """Vero se l'oggetto appena creato (backfill di un'email vecchia) ha una data di
    riferimento di oltre un giorno nel passato: in tal caso non si accoda la notifica
    Telegram di controllo, per non far esplodere il canale al primo collegamento
    dell'account Gmail (finding §3 revisione finale). L'oggetto resta comunque creato."""
    cutoff = now.date() - timedelta(days=1)
    if model is Event:
        reference = obj.start_date if obj.all_day else (obj.start_at.date() if obj.start_at else None)
        return bool(reference and reference < cutoff)
    reference = getattr(obj, "due_date", None)
    return bool(reference and reference < cutoff)


def ingest_message(db: Session, connection: GoogleConnection, message: dict,
                   analyze: Callable[[str], dict], timezone_name: str, now: datetime | None = None,
                   blocked_domains: Sequence[str] = (), trash: Callable[[str], bool | None] | None = None,
                   auto_trash_promotions: bool = False, kept_senders: Sequence[str] = (),
                   judge: Callable[[str, list[str]], int | None] | None = None,
                   household_settings: dict | None = None) -> int:
    """`judge(nuovo, esistenti)`: Hermes decide nei casi dubbi se un appuntamento è già presente.
    `household_settings`: categorie dei costi e fornitori già classificati dalla famiglia."""
    now = now or datetime.now(timezone.utc)
    message_id = message["id"]
    seen = db.scalar(select(EmailProcessed).where(EmailProcessed.connection_id == connection.id,
                                                   EmailProcessed.message_id == message_id))
    if seen:
        return 0
    headers = {item.get("name", "").lower(): item.get("value", "")
               for item in message.get("payload", {}).get("headers", [])}
    if blocked_domains and is_blocked_sender(headers.get("from", ""), blocked_domains):
        # Dominio bloccato: nessuna analisi Hermes (nessun costo), l'email va nel cestino.
        if trash is not None:
            try:
                trash(message_id)
            except TrashNotPermitted:
                pass  # resta in casella; sync_gmail chiede di ricollegare Google
        db.add(EmailProcessed(connection_id=connection.id, message_id=message_id))
        db.commit()
        return 0
    sender = headers.get("from", "")[:320]
    subject = headers.get("subject", "")[:500]
    snippet = message.get("snippet", "")[:500]
    body = _body_text(message.get("payload", {}))[:12000] or snippet
    created_count = 0
    notices: list[tuple[str, str, str]] = []
    promo = False
    try:
        result = analyze(f"Da: {sender}\nOggetto: {subject}\nTesto: {body}")
        promo = result.get("promo") is True
        actions = result.get("actions") or []
        bills = result.get("bills") or []
        batch = ActionBatchIn.model_validate({"actions": actions}) if actions else None
        # Posta di massa (newsletter, promozioni): un appuntamento o un'attività non si crea mai da
        # solo ma passa da «Da controllare»; se Hermes la giudica pura pubblicità non si propone nemmeno.
        bulk = is_bulk_mail(message, headers)
        # Mittente di cui la famiglia ha sempre scartato tutto: niente appuntamenti né attività.
        unwanted = habits.always_discarded(db, connection.household_id, sender)
        tz = ZoneInfo(timezone_name)
        proposal_index = 0

        def propose(kind: str, data: dict, note: str | None = None) -> None:
            nonlocal proposal_index
            db.add(Proposal(household_id=connection.household_id, created_by=connection.user_id,
                            connection_id=connection.id, message_id=message_id,
                            thread_id=message.get("threadId", ""), item_index=proposal_index,
                            sender=sender, subject=subject, snippet=(note or snippet)[:500],
                            kind=kind, data=data))
            # Forza subito il flush: un vincolo di unicità violato emerge qui (già protetto
            # dall'except sotto) invece che al commit finale fuori da questo blocco.
            db.flush()
            proposal_index += 1

        if batch:
            for action in batch.actions:
                schema, model = ACTION_TYPES[action.kind]
                validated = schema.model_validate(action.data)
                if action.kind != "shopping" and (promo or unwanted):
                    continue
                # Un acquisto (l'email contiene un costo) o la posta di massa non sono voci della spesa.
                if action.kind == "shopping" and (promo or bulk or unwanted or bills):
                    continue
                if action.kind == "shopping" or bulk:
                    propose(action.kind, validated.model_dump(mode="json"))
                else:
                    data = validated.model_dump()
                    if model is Event:
                        same, other_time = find_same_event(db, connection.household_id, data, tz, judge)
                        if same is not None and not other_time:
                            continue  # già in calendario, anche se scritto diversamente
                        if same is not None:
                            # Stesso impegno a un orario diverso: decide la famiglia.
                            existing = same.start_at.astimezone(tz).strftime("%H:%M")
                            propose("event", validated.model_dump(mode="json"),
                                    f"In calendario c'è già «{same.title}» alle {existing}: "
                                    "questa email indica un orario diverso.")
                            created_count += 1
                            continue
                    elif find_same_task(db, connection.household_id, data["title"]):
                        continue
                    # Un appuntamento/attività estratti da email non devono mai assegnarsi
                    # automaticamente a un familiare: un member_id inventato dal modello farebbe
                    # fallire il flush (FK) e bloccherebbe per sempre l'ingestione di questo
                    # messaggio (vedi finding §1 revisione finale).
                    data.pop("member_id", None)
                    obj = model(household_id=connection.household_id, created_by=connection.user_id, **data)
                    obj.source = "gmail"
                    obj.source_sender = sender or None
                    db.add(obj)
                    db.flush()
                    if not _is_stale(model, obj, now):
                        notices.append((action.kind, obj.id,
                                       _creation_summary(action.kind, obj, sender, timezone_name)))
                created_count += 1
        for item in bills:
            try:
                item = dict(item)
                state = item.pop("payment_state", None)
                bill_data = BillIn.model_validate(item).model_dump()
            except (ValidationError, KeyError, TypeError, ValueError):
                # Una voce malformata non deve far saltare le altre bollette né le azioni
                # già create nello stesso messaggio (finding §2 revisione finale).
                continue
            if bill_data["amount"] is None:
                # Nessun importo individuabile: meglio non creare la voce che indovinare (§3 del design).
                continue
            # Fornitore già classificato dalla famiglia: vince sempre sulla scelta di Hermes.
            learned = known_supplier(household_settings, bill_data.get("supplier"))
            bill_data["category"], bill_data["subcategory"] = learned or normalize(
                taxonomy_of(household_settings), bill_data["category"], bill_data.get("subcategory"))
            if find_same_bill(db, connection.household_id, bill_data):
                continue  # la stessa somma già registrata (altra email sullo stesso pagamento)
            db.add(Bill(household_id=connection.household_id, created_by=connection.user_id,
                        source_sender=sender or None, source_subject=subject or None,
                        payment_state=state if state in ("pagato", "addebito_previsto") else "da_pagare",
                        **bill_data))
            db.flush()
            created_count += 1
    except (HermesInvalidResponse, ValidationError, KeyError, SQLAlchemyError):
        # Il modello ha risposto con qualcosa di inutilizzabile per questo messaggio: si
        # segna comunque come processato, altrimenti il worker lo ritenterebbe a ogni giro.
        db.rollback()
        created_count = 0
        notices = []
        promo = False
    db.add(EmailProcessed(connection_id=connection.id, message_id=message_id))
    try:
        db.commit()
    except SQLAlchemyError:
        # Difesa in profondità: un errore imprevisto anche qui (non solo nel blocco
        # sopra) non deve far ritentare questo messaggio all'infinito a ogni giro.
        db.rollback()
        created_count = 0
        notices = []
        promo = False
        db.add(EmailProcessed(connection_id=connection.id, message_id=message_id))
        db.commit()
    if (auto_trash_promotions and trash is not None
            and is_promotion_to_trash(message, headers, promo, created_count, kept_senders)):
        try:
            moved = trash(message_id) is not False  # False: già sparita (404)
        except TrashNotPermitted:
            moved = False  # resta in casella; sync_gmail chiede di ricollegare Google
        if moved:
            db.add(EmailAutoTrash(household_id=connection.household_id, connection_id=connection.id,
                                  recipient_user_id=connection.user_id, message_id=message_id,
                                  sender=trashed_sender(headers.get("from", "")), subject=subject))
            db.commit()
    for entity_type, entity_id, summary in notices:
        db.add(EmailCreationNotice(household_id=connection.household_id, entity_type=entity_type,
                                   entity_id=entity_id, recipient_user_id=connection.user_id, summary=summary))
    if notices:
        db.commit()
    return created_count


def sync_gmail(db: Session, connection: GoogleConnection, service,
               analyze: Callable[[str], dict], timezone_name: str, now: datetime | None = None,
               blocked_domains: Sequence[str] = (), auto_trash_promotions: bool = False,
               kept_senders: Sequence[str] = (), judge: Callable[[str, list[str]], int | None] | None = None,
               household_settings: dict | None = None) -> int:
    """Scorre i messaggi che corrispondono ai filtri; riprende dalle pagine incomplete."""
    now = now or datetime.now(timezone.utc)
    since = connection.last_gmail_sync_at - timedelta(days=1) if connection.last_gmail_sync_at else now - timedelta(days=365)
    query = f"{connection.gmail_query} after:{since:%Y/%m/%d}".strip()
    params = {"q": query, "maxResults": 50}
    if connection.gmail_page_token:
        params["pageToken"] = connection.gmail_page_token
    token = service.access_token(connection)
    permission_missing = False

    def trash(message_id: str) -> bool:
        nonlocal permission_missing
        try:
            return trash_message(service, token, message_id)
        except TrashNotPermitted:
            permission_missing = True
            raise

    page = service.api.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", token, params)
    created = 0
    for item in page.get("messages", []):
        message = service.api.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}", token,
            {"format": "full"})
        created += ingest_message(db, connection, message, analyze, timezone_name, now,
                                  blocked_domains=blocked_domains, trash=trash,
                                  auto_trash_promotions=auto_trash_promotions, kept_senders=kept_senders,
                                  judge=judge, household_settings=household_settings)
    connection.gmail_page_token = page.get("nextPageToken")
    if not connection.gmail_page_token:
        connection.last_gmail_sync_at = now
    connection.last_error = TRASH_PERMISSION_MESSAGE if permission_missing else None
    db.commit()
    return created
