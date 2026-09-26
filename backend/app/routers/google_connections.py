"""OAuth e preferenze Google per ciascun utente."""

from urllib.parse import urljoin

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..errors import ApiError
from ..google import GoogleService
from ..models import CalendarEventLink, EmailDomainCleanup, EmailProcessed, GoogleCalendar, GoogleConnection, Proposal
from ..security import Ctx, current

router = APIRouter(prefix="/connections/google", tags=["connections"])


def get_service() -> GoogleService:
    if not all((settings.public_url, settings.google_client_id, settings.google_client_secret,
                settings.google_token_key)):
        raise ApiError(503, "google_not_configured", "Google non è ancora configurato sul server.")
    redirect_uri = settings.public_url.rstrip("/") + "/api/v1/connections/google/callback"
    return GoogleService(settings.google_client_id, settings.google_client_secret,
                         redirect_uri, settings.google_token_key)


def own_connection(db: Session, ctx: Ctx) -> GoogleConnection:
    row = db.scalar(select(GoogleConnection).where(GoogleConnection.user_id == ctx.user_id,
                                                    GoogleConnection.household_id == ctx.household_id))
    if row is None:
        raise ApiError(404, "not_connected", "Account Google non collegato.")
    return row


@router.post("/start")
def start(ctx: Ctx = Depends(current), db: Session = Depends(get_db), service: GoogleService = Depends(get_service)):
    return {"authorization_url": service.start(db, ctx)}


@router.get("/callback", include_in_schema=False)
def callback(state: str, code: str, db: Session = Depends(get_db), service: GoogleService = Depends(get_service)):
    try:
        service.finish(db, state, code)
    except ValueError as exc:
        raise ApiError(400, "google_oauth_failed", str(exc)) from None
    return RedirectResponse(url="/#impostazioni")


@router.get("")
def status(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    row = db.scalar(select(GoogleConnection).where(GoogleConnection.user_id == ctx.user_id,
                                                    GoogleConnection.household_id == ctx.household_id))
    if row is None:
        return {"connected": False}
    calendars = db.scalars(select(GoogleCalendar).where(GoogleCalendar.connection_id == row.id)).all()
    return {"connected": True, "email": row.email, "gmail_query": row.gmail_query,
            "last_gmail_sync_at": row.last_gmail_sync_at,
            "last_error": row.last_error,
            "calendars": [{"id": c.external_id, "title": c.title, "mode": c.mode,
                           "outbound_default": c.outbound_default, "last_synced_at": c.last_synced_at}
                          for c in calendars]}


class GmailSettings(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@router.put("/gmail")
def configure_gmail(data: GmailSettings, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    row = own_connection(db, ctx)
    row.gmail_query = data.query.strip()
    row.gmail_history_id = None
    row.gmail_page_token = None
    row.last_gmail_sync_at = None
    db.commit()
    return {"query": row.gmail_query}


@router.get("/calendars/available")
def available_calendars(ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                        service: GoogleService = Depends(get_service)):
    connection = own_connection(db, ctx)
    token = service.access_token(connection)
    items = service.api.get("https://www.googleapis.com/calendar/v3/users/me/calendarList", token).get("items", [])
    return [{"id": item["id"], "title": item.get("summary", item["id"]),
             "access_role": item.get("accessRole")} for item in items]


class CalendarSelection(BaseModel):
    id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=250)
    mode: str = Field(pattern="^(full|busy)$")
    outbound_default: bool = False


@router.put("/calendars")
def select_calendars(selections: list[CalendarSelection], ctx: Ctx = Depends(current),
                     db: Session = Depends(get_db), service: GoogleService = Depends(get_service)):
    connection = own_connection(db, ctx)
    if len(selections) > 30 or len({item.id for item in selections}) != len(selections):
        raise ApiError(422, "invalid_calendars", "Elenco dei calendari non valido.")
    defaults = [item for item in selections if item.outbound_default]
    if len(defaults) > 1 or any(item.mode == "busy" for item in defaults):
        raise ApiError(422, "invalid_default", "Scegli al massimo un calendario personale predefinito.")
    token = service.access_token(connection)
    available = {item["id"]: item for item in service.api.get(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList", token).get("items", [])}
    if any(item.id not in available for item in selections):
        raise ApiError(422, "invalid_calendars", "Uno dei calendari non è accessibile.")
    if any(available[item.id].get("accessRole") not in ("owner", "writer") for item in defaults):
        raise ApiError(422, "read_only_calendar", "Il calendario predefinito non consente la scrittura.")
    existing = {row.external_id: row for row in db.scalars(select(GoogleCalendar).where(
        GoogleCalendar.connection_id == connection.id)).all()}
    for item in selections:
        row = existing.pop(item.id, None)
        if row is None:
            row = GoogleCalendar(connection_id=connection.id, external_id=item.id, title=item.title)
            db.add(row)
        if row.mode != item.mode:
            row.sync_token = None
        row.mode = item.mode
        row.title = item.title
        row.outbound_default = item.outbound_default
    for row in existing.values():
        db.execute(delete(CalendarEventLink).where(CalendarEventLink.calendar_id == row.id))
        db.delete(row)
    db.commit()
    return {"selected": len(selections)}


@router.delete("", status_code=204)
def disconnect(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    row = own_connection(db, ctx)
    calendar_ids = select(GoogleCalendar.id).where(GoogleCalendar.connection_id == row.id)
    db.execute(delete(CalendarEventLink).where(CalendarEventLink.calendar_id.in_(calendar_ids)))
    db.execute(delete(GoogleCalendar).where(GoogleCalendar.connection_id == row.id))
    db.execute(delete(Proposal).where(Proposal.connection_id == row.id))
    db.execute(delete(EmailProcessed).where(EmailProcessed.connection_id == row.id))
    db.execute(delete(EmailDomainCleanup).where(EmailDomainCleanup.connection_id == row.id))
    db.delete(row)
    db.commit()
