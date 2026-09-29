"""Serie finite: occorrenze indipendenti, generate insieme in una transazione."""

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .crud import audit, ensure_member
from .errors import ApiError
from .models import Event, Household, new_id
from .schemas import EventIn

MAX_OCCURRENCES = 366


def create_series(db, ctx, data):
    ensure_member(db, ctx, data.member_id)
    tz = ZoneInfo(db.get(Household, ctx.household_id).timezone)
    first = data.start_date if data.all_day else data.start_at.astimezone(tz).date()
    if data.repeat_until < first:
        raise ApiError(422, "validation_error", "La fine della ripetizione precede il primo appuntamento.")
    values = data.model_dump(exclude={"repeat", "repeat_until"})
    occurrences = []
    for index in range(MAX_OCCURRENCES + 1):
        if data.repeat == "monthly":
            year, month = divmod(first.year * 12 + first.month - 1 + index, 12)
            if year > 9999:
                break
            day = first.replace(year=year, month=month + 1,
                                day=min(first.day, calendar.monthrange(year, month + 1)[1]))
        else:
            offset = timedelta(days=index * (7 if data.repeat == "weekly" else 1))
            if offset > data.repeat_until - first:
                break
            day = first + offset
        if day > data.repeat_until:
            break
        if index == MAX_OCCURRENCES:
            raise ApiError(422, "validation_error", "Puoi creare al massimo 366 appuntamenti alla volta. Scegli una data finale più vicina.")
        occurrence = dict(values)
        if data.all_day:
            occurrence['start_date'] = day
            occurrence['end_date'] = day + (data.end_date - first) if data.end_date else None
        else:
            for field in ('start_at', 'end_at'):
                instant = values[field]
                if instant is not None:
                    local = instant.astimezone(tz)
                    target = day + (local.date() - first)
                    occurrence[field] = datetime.combine(target, local.timetz(), tz).astimezone(timezone.utc)
        # Validate each occurrence too (e.g. an interval across the DST transition).
        try:
            occurrences.append(EventIn.model_validate(occurrence).model_dump())
        except ValidationError:
            raise ApiError(422, "validation_error",
                           f"Orari non validi il {day:%d/%m/%Y}, in corrispondenza del cambio dell’ora. Scegli orari diversi.") from None
    series_id = new_id()
    events = []
    for fields in occurrences:
        event = Event(household_id=ctx.household_id, created_by=ctx.user_id,
                      series_id=series_id, **fields)
        db.add(event)
        events.append(event)
    db.flush()
    for event in events:
        audit(db, ctx, "create", event, {"series_id": series_id})
    return events[0]
