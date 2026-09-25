"""Notifica Telegram di controllo dopo aver creato direttamente un appuntamento o
un'attività da un'email. Le righe le accoda gmail_sync.ingest_message, solo dopo che il
salvataggio è confermato (vedi docs/superpowers/specs/2026-09-25-bollette-costi-casa-design.md §8.3)."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ChannelLink, EmailCreationNotice


def dispatch_email_creation_notices(db: Session, send: Callable[[str, str], None], now: datetime) -> int:
    notices = db.scalars(select(EmailCreationNotice).where(EmailCreationNotice.sent_at.is_(None))
                         .order_by(EmailCreationNotice.created_at).limit(100)).all()
    sent = 0
    for notice in notices:
        link = db.scalar(select(ChannelLink).where(ChannelLink.user_id == notice.recipient_user_id,
                                                    ChannelLink.platform == "telegram"))
        if not link:
            continue
        send(link.chat_id, notice.summary)
        notice.sent_at = now
        sent += 1
        db.commit()
    return sent
