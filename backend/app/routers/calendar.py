"""Conflitti di sincronizzazione del calendario, risolti dall'utente."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..models import CalendarEventLink, Event, GoogleCalendar, GoogleConnection, utcnow
from ..security import Ctx, current

router = APIRouter(prefix="/calendar/conflicts", tags=["calendar"])


class Resolution(BaseModel):
    choice: Literal["google", "local"]


def _owned_link(db: Session, ctx: Ctx, link_id: str):
    row = db.execute(
        select(CalendarEventLink, Event, GoogleCalendar, GoogleConnection)
        .join(Event, Event.id == CalendarEventLink.event_id)
        .join(GoogleCalendar, GoogleCalendar.id == CalendarEventLink.calendar_id)
        .join(GoogleConnection, GoogleConnection.id == GoogleCalendar.connection_id)
        .where(CalendarEventLink.id == link_id, Event.household_id == ctx.household_id,
               GoogleConnection.user_id == ctx.user_id)
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "Conflitto non trovato.")
    return row


@router.get("")
def list_conflicts(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    rows = db.execute(
        select(CalendarEventLink, Event, GoogleCalendar, GoogleConnection)
        .join(Event, Event.id == CalendarEventLink.event_id)
        .join(GoogleCalendar, GoogleCalendar.id == CalendarEventLink.calendar_id)
        .join(GoogleConnection, GoogleConnection.id == GoogleCalendar.connection_id)
        .where(Event.household_id == ctx.household_id, GoogleConnection.user_id == ctx.user_id,
               CalendarEventLink.status == "conflict")
    ).all()
    return [{"id": link.id, "event_id": event.id, "local_title": event.title,
             "remote": link.remote_payload, "calendar": calendar.title} for link, event, calendar, _ in rows]


@router.post("/{link_id}/resolve")
def resolve(link_id: str, data: Resolution, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    link, event, calendar, connection = _owned_link(db, ctx, link_id)
    if link.status != "conflict" or not link.remote_payload:
        raise ApiError(409, "not_in_conflict", "Il conflitto è già stato risolto.")
    payload = link.remote_payload
    if data.choice == "local":
        if calendar.mode != "full" or payload.get("deleted"):
            raise ApiError(422, "read_only", "Non è possibile aggiornare questo calendario Google.")
        from ..google import GoogleService
        from .google_connections import get_service
        from ..calendar_sync import _google_body
        from urllib.parse import quote

        service: GoogleService = get_service()
        url = ("https://www.googleapis.com/calendar/v3/calendars/" + quote(calendar.external_id, safe="")
               + "/events/" + quote(link.external_id, safe=""))
        remote = service.api.patch(url, service.access_token(connection), _google_body(event), payload.get("etag"))
        link.etag = remote.get("etag")
    else:
        if payload.get("deleted"):
            event.deleted_at = utcnow()
        else:
            for key in ("title", "all_day", "location", "notes"):
                setattr(event, key, payload.get(key))
            for key in ("start_at", "end_at"):
                setattr(event, key, datetime.fromisoformat(payload[key]) if payload.get(key) else None)
            for key in ("start_date", "end_date"):
                setattr(event, key, date.fromisoformat(payload[key]) if payload.get(key) else None)
            event.deleted_at = None
        link.etag = payload.get("etag")
    db.flush()
    link.local_version = event.version
    link.status = "synced"
    link.remote_payload = None
    link.last_synced_at = utcnow()
    db.commit()
    return {"status": link.status, "event_id": event.id}
