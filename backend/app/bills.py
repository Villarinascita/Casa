"""Promemoria Telegram per le bollette: alla scoperta e vicino alla scadenza.

Il destinatario è sempre bill.created_by: per una bolletta estratta da email è l'utente
proprietario della GoogleConnection (vedi gmail_sync.ingest_message), per una inserita a
mano è chi l'ha creata — coincide con la regola descritta nel design (§4)."""

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Bill, ChannelLink

DUE_SOON_DAYS = 3


def _send_to(db: Session, send: Callable[[str, str], None], recipient_user_id: str, text: str) -> bool:
    link = db.scalar(select(ChannelLink).where(ChannelLink.user_id == recipient_user_id,
                                                ChannelLink.platform == "telegram"))
    if not link:
        return False
    send(link.chat_id, text)
    return True


def _found_text(bill: Bill) -> str:
    amount = f", {bill.amount:.2f}€" if bill.amount is not None else ""
    due = f", scade il {bill.due_date:%d/%m}" if bill.due_date else ""
    return f"Trovata una bolletta: {bill.title}{amount}{due}."


def _due_text(bill: Bill) -> str:
    amount = f" di {bill.amount:.2f}€" if bill.amount is not None else ""
    return f"Promemoria: {bill.title}{amount} scade il {bill.due_date:%d/%m}. Segnalala pagata in app quando fatto."


def dispatch_bill_reminders(db: Session, send: Callable[[str, str], None], now: datetime) -> int:
    sent = 0
    found = db.scalars(select(Bill).where(Bill.found_reminder_sent_at.is_(None),
                                          Bill.deleted_at.is_(None)).limit(100)).all()
    for bill in found:
        if bill.created_by and _send_to(db, send, bill.created_by, _found_text(bill)):
            bill.found_reminder_sent_at = now
            sent += 1
            db.commit()

    threshold = now.date() + timedelta(days=DUE_SOON_DAYS)
    due_soon = db.scalars(select(Bill).where(Bill.due_reminder_sent_at.is_(None),
                                             Bill.deleted_at.is_(None),
                                             Bill.payment_state != "pagato",
                                             Bill.due_date.is_not(None),
                                             Bill.due_date <= threshold).limit(100)).all()
    for bill in due_soon:
        if bill.created_by and _send_to(db, send, bill.created_by, _due_text(bill)):
            bill.due_reminder_sent_at = now
            sent += 1
            db.commit()
    return sent
