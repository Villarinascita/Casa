"""Promemoria Telegram persistenti per ogni singolo appuntamento."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from .models import ChannelLink, Event, EventReminderDelivery, Household, Member


def reminder_window(event, timezone_name):
    tz = ZoneInfo(timezone_name)
    if event.all_day:
        start = datetime.combine(event.start_date, time(9), tz).astimezone(timezone.utc)
        expires = datetime.combine(event.end_date or event.start_date, time.max, tz).astimezone(timezone.utc)
    else:
        start = event.start_at
        expires = event.end_at if event.end_at and event.end_at > start else start + timedelta(hours=1)
    return start - timedelta(minutes=event.reminder_minutes), expires, start


def enqueue_due(db, now):
    # The API allows at most a week of advance notice; include a day for timezone boundaries.
    latest = now + timedelta(days=8)
    candidates = db.scalars(select(Event).where(
        Event.deleted_at.is_(None), Event.reminder_minutes.is_not(None),
        or_(Event.start_at <= latest, Event.start_date <= latest.date()),
        or_(Event.end_at >= now, Event.start_at >= now - timedelta(hours=1),
            Event.start_date >= now.date() - timedelta(days=1),
            Event.end_date >= now.date() - timedelta(days=1)),
    )).all()
    count = 0
    for event in candidates:
        household = db.get(Household, event.household_id)
        scheduled, expires, _ = reminder_window(event, household.timezone)
        if not scheduled <= now < expires:
            continue
        existing = db.scalar(select(EventReminderDelivery).where(
            EventReminderDelivery.event_id == event.id,
            EventReminderDelivery.scheduled_at == scheduled))
        if existing is None:
            db.add(EventReminderDelivery(event_id=event.id, scheduled_at=scheduled))
            count += 1
        elif existing.status == 'cancelled':
            # Restoring an event or returning to the original time may reactivate an unsent notice.
            existing.status = 'pending'
            existing.last_error = None
            count += 1
    db.commit()
    return count


def dispatch_pending(db, send, now):
    # No LIMIT before checking Telegram links: unlinked users must not starve other deliveries.
    pending = db.scalars(select(EventReminderDelivery).where(
        EventReminderDelivery.status == 'pending').order_by(EventReminderDelivery.scheduled_at)).all()
    delivered = 0
    for delivery in pending:
        event = db.get(Event, delivery.event_id)
        if not event or event.deleted_at or event.reminder_minutes is None:
            delivery.status = 'cancelled'
            continue
        household = db.get(Household, event.household_id)
        scheduled, expires, start = reminder_window(event, household.timezone)
        if scheduled != delivery.scheduled_at or now >= expires:
            delivery.status = 'cancelled'
            continue
        if now < scheduled:
            continue
        member = db.get(Member, event.member_id) if event.member_id else None
        recipient = member.user_id if member and member.user_id else event.created_by
        link = db.scalar(select(ChannelLink).where(
            ChannelLink.user_id == recipient, ChannelLink.household_id == event.household_id,
            ChannelLink.platform == 'telegram'))
        if not link:
            delivery.last_error = 'Account Telegram non collegato.'
            continue
        local = start.astimezone(ZoneInfo(household.timezone))
        when = local.strftime('%d/%m/%Y') + (' · tutto il giorno' if event.all_day else local.strftime(' alle %H:%M'))
        message = f'Promemoria appuntamento: {event.title}\n{when}'
        if event.location:
            message += f'\nDove: {event.location}'
        try:
            send(link.chat_id, message)
        except Exception:
            delivery.attempts += 1
            delivery.last_error = 'Invio Telegram non riuscito. Nuovo tentativo al prossimo ciclo.'
        else:
            delivery.status = 'sent'
            delivery.sent_at = now
            delivery.attempts += 1
            delivery.last_error = None
            delivered += 1
        db.commit()
        if delivered >= 100:
            break
    db.commit()
    return delivered
