"""Riconciliazione tra eventi locali e Google Calendar."""

import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CalendarEventLink, Event, GoogleCalendar, GoogleConnection, utcnow


def _remote_fields(remote: dict, mode: str) -> dict:
    start, end = remote["start"], remote.get("end", {})
    if "date" in start:
        first = date.fromisoformat(start["date"])
        end_exclusive = date.fromisoformat(end.get("date", start["date"]))
        last = max(first, end_exclusive - timedelta(days=1))
        return {"title": "Occupato" if mode == "busy" else remote.get("summary", "Senza titolo")[:180],
                "all_day": True, "start_date": first, "end_date": last,
                "start_at": None, "end_at": None,
                "location": (remote.get("location") or "")[:300] or None,
                "notes": None if mode == "busy" else (remote.get("description") or "")[:2000] or None}
    start_at = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(timezone.utc)
    end_at = (datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00")).astimezone(timezone.utc)
              if end.get("dateTime") else None)
    return {"title": "Occupato" if mode == "busy" else remote.get("summary", "Senza titolo")[:180],
            "all_day": False, "start_at": start_at, "end_at": end_at,
            "start_date": None, "end_date": None,
            "location": (remote.get("location") or "")[:300] or None,
            "notes": None if mode == "busy" else (remote.get("description") or "")[:2000] or None}


def apply_remote_event(db: Session, connection: GoogleConnection, calendar: GoogleCalendar, remote: dict) -> str:
    link = db.scalar(select(CalendarEventLink).where(CalendarEventLink.calendar_id == calendar.id,
                                                     CalendarEventLink.external_id == remote["id"]))
    if remote.get("status") == "cancelled":
        if link is None:
            return "ignored"
        event = db.get(Event, link.event_id)
        if event.version != link.local_version:
            link.status, link.remote_payload = "conflict", {"deleted": True}
            return "conflict"
        event.deleted_at = utcnow()
        db.flush()
        link.local_version, link.etag, link.last_synced_at = event.version, remote.get("etag"), utcnow()
        return "deleted"
    fields = _remote_fields(remote, calendar.mode)
    if link is None:
        event = None
        external_id = remote["id"]
        if external_id.startswith("insieme"):
            try:
                local_id = str(uuid.UUID(hex=external_id[7:]))
                candidate = db.get(Event, local_id)
                if candidate and candidate.household_id == connection.household_id:
                    event = candidate
            except ValueError:
                pass
        if event is None:
            event = Event(household_id=connection.household_id, created_by=connection.user_id,
                          source="google-busy" if calendar.mode == "busy" else "google", **fields)
            db.add(event)
            db.flush()
        db.add(CalendarEventLink(calendar_id=calendar.id, event_id=event.id, external_id=remote["id"],
                                 etag=remote.get("etag"), local_version=event.version))
        return "created"
    event = db.get(Event, link.event_id)
    if link.etag == remote.get("etag"):
        return "unchanged"
    if event.version != link.local_version:
        link.status, link.remote_payload = "conflict", {
            **{key: value.isoformat() if isinstance(value, (date, datetime)) else value
               for key, value in fields.items()}, "deleted": False, "etag": remote.get("etag")}
        return "conflict"
    for key, value in fields.items():
        setattr(event, key, value)
    event.deleted_at = None
    db.flush()
    link.etag, link.local_version = remote.get("etag"), event.version
    link.status, link.remote_payload, link.last_synced_at = "synced", None, utcnow()
    return "updated"


def _google_body(event: Event, external_id: str | None = None) -> dict:
    body = {"summary": event.title, "location": event.location or "", "description": event.notes or ""}
    if external_id:
        body["id"] = external_id
    if event.all_day:
        body["start"] = {"date": event.start_date.isoformat()}
        body["end"] = {"date": ((event.end_date or event.start_date) + timedelta(days=1)).isoformat()}
    else:
        body["start"] = {"dateTime": event.start_at.isoformat()}
        body["end"] = {"dateTime": (event.end_at or event.start_at + timedelta(hours=1)).isoformat()}
    return body


def push_local_event(db: Session, connection: GoogleConnection, event: Event, service) -> str:
    link = db.scalar(select(CalendarEventLink).where(CalendarEventLink.event_id == event.id))
    is_new = link is None
    if link:
        calendar = db.get(GoogleCalendar, link.calendar_id)
        if calendar.connection_id != connection.id:
            return "ignored"
        if calendar.mode == "busy" or link.status == "conflict" or event.version == link.local_version:
            return "ignored"
        url = ("https://www.googleapis.com/calendar/v3/calendars/" + quote(calendar.external_id, safe="")
               + "/events/" + quote(link.external_id, safe=""))
    else:
        if (event.deleted_at is not None or event.source.startswith("google") or event.source in ("gmail", "nonni")
                or event.created_by != connection.user_id):
            # Gli eventi creati automaticamente da un'email restano locali finché l'utente
            # non ci interagisce: niente push immediato verso Google Calendar, sia per il
            # backfill di un anno che per qualsiasi email futura (finding §3 revisione finale).
            return "ignored"
        calendar = db.scalar(select(GoogleCalendar).where(GoogleCalendar.connection_id == connection.id,
                                                           GoogleCalendar.outbound_default.is_(True),
                                                           GoogleCalendar.mode == "full"))
        if calendar is None:
            return "ignored"
        url = "https://www.googleapis.com/calendar/v3/calendars/" + quote(calendar.external_id, safe="") + "/events"
    token = service.access_token(connection)
    try:
        if link and event.deleted_at is not None:
            service.api.delete(url, token, link.etag)
            link.local_version, link.last_synced_at = event.version, utcnow()
            db.commit()
            return "deleted"
        if link:
            remote = service.api.patch(url, token, _google_body(event), link.etag)
        else:
            external_id = "insieme" + uuid.UUID(event.id).hex
            remote = service.api.post(url, token, _google_body(event, external_id))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 412 and link:
            remote = service.api.get(url, token)
            apply_remote_event(db, connection, calendar, remote)
            db.commit()
            return "conflict"
        if exc.response.status_code == 409 and not link:
            remote = service.api.get(url + "/" + external_id, token)
        else:
            raise
    if link is None:
        link = CalendarEventLink(calendar_id=calendar.id, event_id=event.id,
                                 external_id=remote["id"], etag=remote.get("etag"),
                                 local_version=event.version)
        db.add(link)
    else:
        link.etag, link.local_version, link.last_synced_at = remote.get("etag"), event.version, utcnow()
    db.commit()
    return "created" if is_new else "updated"


def sync_calendar(db: Session, connection: GoogleConnection, calendar: GoogleCalendar, service,
                  now: datetime) -> int:
    full = not calendar.last_full_sync_at or now - calendar.last_full_sync_at >= timedelta(days=1)
    params = {"singleEvents": "true", "showDeleted": "true", "maxResults": 250,
              "timeMin": (now - timedelta(days=365)).isoformat(),
              "timeMax": (now + timedelta(days=365)).isoformat()}
    if not full and calendar.last_synced_at:
        params["updatedMin"] = (calendar.last_synced_at - timedelta(minutes=5)).isoformat()
    token = service.access_token(connection)
    url = "https://www.googleapis.com/calendar/v3/calendars/" + quote(calendar.external_id, safe="") + "/events"
    count = 0
    while True:
        page = service.api.get(url, token, params)
        for remote in page.get("items", []):
            if apply_remote_event(db, connection, calendar, remote) not in ("ignored", "unchanged"):
                count += 1
        if not page.get("nextPageToken"):
            break
        params["pageToken"] = page["nextPageToken"]
    calendar.last_synced_at = now
    if full:
        calendar.last_full_sync_at = now
    db.commit()
    return count
