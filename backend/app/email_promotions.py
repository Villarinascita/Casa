"""Pubblicità nel cestino in automatico, riepilogo settimanale su Telegram e comando «tieni»
(vedi docs/superpowers/specs/2026-09-26-pubblicita-automatica-design.md)."""

import re
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .email_cleanup import queue_domain_cleanups
from .email_domains import is_blocked_sender, normalize_blocked_sender, sender_address
from .models import ChannelLink, EmailAutoTrash, Household

SUMMARY_AFTER = timedelta(days=7)
SUMMARY_TOP = 10
KEEP_COMMAND = re.compile(r"^/?tieni\s+(.+)$", re.IGNORECASE)
_BULK_LABELS = {"CATEGORY_PROMOTIONS"}
_PROTECTED_LABELS = {"STARRED", "IMPORTANT"}


def is_promotion_to_trash(message: dict, headers: dict[str, str], promo: bool, created: int,
                          kept_senders: Sequence[str]) -> bool:
    """Tutte le condizioni della §2: in dubbio l'email resta in casella."""
    labels = set(message.get("labelIds") or [])
    bulk = bool(headers.get("list-unsubscribe")) or bool(labels & _BULK_LABELS)
    return (promo and bulk and created == 0 and not labels & _PROTECTED_LABELS
            and not is_blocked_sender(headers.get("from", ""), kept_senders))


def _domain(sender: str) -> str:
    return sender.rsplit("@", 1)[-1]


def dispatch_promo_summaries(db: Session, send: Callable[[str, str], None], now: datetime) -> int:
    pending = db.scalars(select(EmailAutoTrash).where(EmailAutoTrash.reported_at.is_(None))).all()
    by_user: dict[str, list[EmailAutoTrash]] = {}
    for row in pending:
        by_user.setdefault(row.recipient_user_id, []).append(row)
    sent = 0
    for user_id, rows in by_user.items():
        if now - min(row.trashed_at for row in rows) < SUMMARY_AFTER:
            continue
        link = db.scalar(select(ChannelLink).where(ChannelLink.user_id == user_id,
                                                    ChannelLink.platform == "telegram"))
        if link is None:
            continue
        counts = Counter(_domain(row.sender) for row in rows)
        top = ", ".join(f"{domain} {count}" for domain, count in counts.most_common(SUMMARY_TOP))
        example = counts.most_common(1)[0][0].split(".")[-2] if counts else "nome"
        text = (f"Negli ultimi giorni ho messo nel cestino {len(rows)} email pubblicitarie: {top}.\n"
                "Restano nel cestino di Gmail per 30 giorni. Se un mittente ti serve scrivimi "
                f"«tieni {example}».")
        try:
            send(link.chat_id, text)
        except Exception:
            continue  # si ritenta al prossimo giro
        for row in rows:
            row.reported_at = now
        db.commit()
        sent += 1
    return sent


def keep_sender(db: Session, household_id: str, request: str) -> str:
    """Aggiunge un dominio/indirizzo ai mittenti da tenere e lo toglie dai bloccati."""
    word = request.strip().lower()
    try:
        entry = normalize_blocked_sender(word)
    except ValueError:
        senders = db.scalars(select(EmailAutoTrash.sender).where(EmailAutoTrash.household_id == household_id)).all()
        matches = sorted({_domain(sender) for sender in senders if word and word in _domain(sender)})
        if len(matches) != 1:
            found = f" Ho trovato: {', '.join(matches[:5])}." if matches else ""
            return f"Non so quale mittente intendi con «{request.strip()}».{found} Scrivimi il dominio preciso, es. «tieni newsletter.conad.com»."
        entry = matches[0]
    household = db.get(Household, household_id)
    settings = dict(household.settings or {})
    kept = list(settings.get("kept_email_senders", []))
    blocked = list(settings.get("blocked_email_domains", []))
    if entry not in kept:
        kept.append(entry)
    remaining = [item for item in blocked if item != entry]
    settings["kept_email_senders"] = kept
    settings["blocked_email_domains"] = remaining
    household.settings = settings
    queue_domain_cleanups(db, household_id, blocked, remaining)
    db.commit()
    return (f"Va bene, le email da {entry} non finiranno più nel cestino. "
            "Quelle già spostate le trovi nel cestino di Gmail.")


def keep_command(text: str) -> str | None:
    match = KEEP_COMMAND.match(text.strip())
    return match.group(1) if match else None


def trashed_sender(from_header: str) -> str:
    return (sender_address(from_header) or from_header or "?")[:320]
