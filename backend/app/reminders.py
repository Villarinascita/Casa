"""Promemoria persistenti e avanzamento nel fuso della famiglia."""

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ChannelLink, Household, Member, ReminderDelivery, Task


def advance_local(instant: datetime, repeat: str, timezone_name: str) -> datetime:
    local = instant.astimezone(ZoneInfo(timezone_name))
    if repeat == "daily":
        next_day = local.date() + timedelta(days=1)
    elif repeat == "weekly":
        next_day = local.date() + timedelta(days=7)
    elif repeat == "monthly":
        year, month = local.year, local.month + 1
        if month == 13:
            year, month = year + 1, 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        next_day = local.date().replace(year=year, month=month, day=day)
    else:
        raise ValueError("Ripetizione non supportata")
    return datetime.combine(next_day, local.timetz().replace(tzinfo=None), ZoneInfo(timezone_name)).astimezone(timezone.utc)


def enqueue_due(db: Session, now: datetime) -> int:
    """Materializza una consegna per attività scaduta; i retry non la duplicano."""
    tasks = db.scalars(select(Task).where(Task.remind_at <= now, Task.deleted_at.is_(None)).limit(100)).all()
    count = 0
    for task in tasks:
        scheduled = task.remind_at
        if task.status == "open":
            recipient = db.get(Member, task.member_id) if task.member_id else None
            db.add(ReminderDelivery(task_id=task.id, scheduled_at=scheduled,
                                    recipient_user_id=(recipient.user_id if recipient and recipient.user_id
                                                       else task.created_by)))
            count += 1
        if task.repeat:
            tz = db.get(Household, task.household_id).timezone
            while task.remind_at <= now:
                task.remind_at = advance_local(task.remind_at, task.repeat, tz)
            task.status = "open"
            task.completed_at = None
            task.completed_by = None
        else:
            task.remind_at = None
    db.commit()
    return count


def dispatch_pending(db: Session, send: Callable[[str, str], None], now: datetime) -> int:
    """Invia le consegne in sospeso; mantiene le fallite per un nuovo tentativo."""
    deliveries = db.scalars(select(ReminderDelivery).where(ReminderDelivery.status == "pending")
                            .order_by(ReminderDelivery.scheduled_at).limit(100)).all()
    delivered = 0
    for delivery in deliveries:
        task = db.get(Task, delivery.task_id)
        link = db.scalar(select(ChannelLink).where(ChannelLink.user_id == delivery.recipient_user_id,
                                                    ChannelLink.platform == "telegram"))
        if not task:
            delivery.status = "unavailable"
            delivery.last_error = "Attività non trovata."
            db.commit()
            continue
        if not link:
            delivery.last_error = "Account Telegram non collegato."
            db.commit()
            continue
        try:
            send(link.chat_id, f"Promemoria: {task.title}")
        except Exception as exc:
            delivery.attempts += 1
            delivery.last_error = str(exc)[:300]
        else:
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.attempts += 1
            delivery.last_error = None
            delivered += 1
        db.commit()
    return delivered
