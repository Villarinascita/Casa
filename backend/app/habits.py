"""Abitudini della famiglia: cosa tiene e cosa scarta tra quanto Hermes prende dalle email
(vedi docs/superpowers/specs/2026-09-26-doppioni-e-abitudini-design.md §3)."""

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .email_domains import sender_address
from .models import Bill, EmailFeedback, Event, Task, utcnow

DISCARDED_EXAMPLES = 30
KEPT_EXAMPLES = 20
ALWAYS_DISCARDED = 3
KEPT_AFTER = timedelta(days=3)


def _domain(sender: str | None) -> str | None:
    address = sender_address(sender or "") or (sender if sender and "@" in sender else None)
    return address.rsplit("@", 1)[1] if address else None


def record(db: Session, household_id: str, kind: str, title: str, sender: str | None, verdict: str,
           entity_id: str | None = None) -> None:
    db.add(EmailFeedback(household_id=household_id, kind=kind, title=(title or "")[:180],
                         sender=(sender or None) and sender[:320], verdict=verdict, entity_id=entity_id))


def on_delete(db: Session, obj) -> None:
    """Eliminare un appuntamento o un'attività presi dalle email vuol dire «non mi serve»."""
    if isinstance(obj, (Event, Task)) and obj.source == "gmail":
        record(db, obj.household_id, "event" if isinstance(obj, Event) else "task", obj.title,
               obj.source_sender, "discarded", obj.id)
    elif isinstance(obj, Bill) and obj.source_sender:
        record(db, obj.household_id, "bill", obj.title, obj.source_sender, "discarded", obj.id)


def on_restore(db: Session, obj) -> None:
    """«Annulla» dopo un'eliminazione: quello scarto non valeva."""
    db.execute(delete(EmailFeedback).where(EmailFeedback.entity_id == obj.id,
                                           EmailFeedback.verdict == "discarded"))


def examples(db: Session, household_id: str) -> dict[str, list[str]]:
    discarded = db.scalars(select(EmailFeedback.title).where(
        EmailFeedback.household_id == household_id, EmailFeedback.verdict == "discarded")
        .order_by(EmailFeedback.created_at.desc()).limit(DISCARDED_EXAMPLES)).all()
    kept = list(db.scalars(select(EmailFeedback.title).where(
        EmailFeedback.household_id == household_id, EmailFeedback.verdict == "kept")
        .order_by(EmailFeedback.created_at.desc()).limit(KEPT_EXAMPLES)).all())
    if len(kept) < KEPT_EXAMPLES:
        cutoff = utcnow() - KEPT_AFTER
        for model in (Event, Task):
            kept += db.scalars(select(model.title).where(
                model.household_id == household_id, model.source == "gmail", model.deleted_at.is_(None),
                model.created_at < cutoff).order_by(model.created_at.desc()).limit(KEPT_EXAMPLES)).all()
    return {"discarded": list(dict.fromkeys(discarded)), "kept": list(dict.fromkeys(kept))[:KEPT_EXAMPLES]}


def always_discarded(db: Session, household_id: str, sender: str | None) -> bool:
    """Almeno 3 scarti dallo stesso dominio e nulla di tenuto: non proporre più nulla da lì."""
    domain = _domain(sender)
    if not domain:
        return False
    like = f"%@{domain}%"
    rows = db.execute(select(EmailFeedback.verdict, func.count()).where(
        EmailFeedback.household_id == household_id, EmailFeedback.sender.like(like))
        .group_by(EmailFeedback.verdict)).all()
    counts = dict(rows)
    if counts.get("discarded", 0) < ALWAYS_DISCARDED or counts.get("kept", 0):
        return False
    cutoff = utcnow() - KEPT_AFTER
    for model in (Event, Task):
        if db.scalar(select(func.count()).select_from(model).where(
                model.household_id == household_id, model.source == "gmail", model.deleted_at.is_(None),
                model.source_sender.like(like), model.created_at < cutoff)):
            return False
    return True
