"""La settimana dei nonni: una sola pagina, solo lettura, con le cose assegnate ai nonni
(vedi docs/superpowers/specs/2026-09-26-settimana-nonni-design.md)."""

import base64
import binascii
import secrets
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..grandparent_plan import PlanError, apply_plan, create_plan, describe
from ..models import Event, GrandparentPlan, Household, HouseholdUser, Member, Task, User, UserSession, utcnow
from ..security import Ctx, current, hash_password

router = APIRouter(tags=["nonni"])
DAY_NAMES = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def grandparent_members(settings: dict | None) -> list[str]:
    value = (settings or {}).get("grandparent_members")
    return list(value) if isinstance(value, list) else []


@router.get("/nonni/week")
def week(start: date | None = Query(None, description="Un giorno qualsiasi della settimana"),
         ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    household = db.get(Household, ctx.household_id)
    tz = ZoneInfo(household.timezone)
    today = datetime.now(tz).date()
    monday = (start or today) - timedelta(days=(start or today).weekday())
    days = [monday + timedelta(days=i) for i in range(7)]
    members = {m.id: m.display_name for m in db.scalars(select(Member).where(Member.household_id == household.id))}
    chosen = [m for m in grandparent_members(household.settings) if m in members]
    items: dict[date, list[dict]] = {d: [] for d in days}
    if chosen:
        first = datetime.combine(monday, time.min, tzinfo=tz)
        events = db.scalars(select(Event).where(
            Event.household_id == household.id, Event.deleted_at.is_(None), Event.member_id.in_(chosen),
            or_(Event.start_at.between(first, first + timedelta(days=7)),
                Event.start_date.between(monday - timedelta(days=31), days[-1])))).all()
        for event in events:
            if event.all_day:
                span = [d for d in days if event.start_date <= d <= (event.end_date or event.start_date)]
                when = None
            else:
                local = event.start_at.astimezone(tz)
                span = [local.date()] if local.date() in items else []
                when = local.strftime("%H:%M")
            for d in span:
                items[d].append({"time": when, "title": event.title, "place": event.location,
                                 "notes": event.notes, "who": members.get(event.member_id)})
        for task in db.scalars(select(Task).where(
                Task.household_id == household.id, Task.deleted_at.is_(None), Task.status == "open",
                Task.member_id.in_(chosen), Task.due_date.between(monday, days[-1]))).all():
            items[task.due_date].append({"time": None, "title": task.title, "place": None, "notes": task.notes,
                                         "who": members.get(task.member_id)})
    return {
        "start": monday.isoformat(), "today": today.isoformat(),
        "who": [members[m] for m in chosen],
        "days": [{"date": d.isoformat(), "name": DAY_NAMES[d.weekday()],
                  # Prima gli orari, poi le indicazioni senza orario (es. «dopo la ginnastica: doccia e cena»).
                  "items": sorted(items[d], key=lambda i: (i["time"] is None, i["time"] or ""))} for d in days],
    }


# --- Accessi dei nonni (solo l'amministratore della famiglia) ---------------------------------

class GrandparentIn(BaseModel):
    login: str = Field(min_length=3, max_length=40)

    @field_validator("login")
    @classmethod
    def _login(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError("Usa solo lettere, numeri, punto o trattino (es. nonna.anna).")
        return value


def _admin(ctx: Ctx) -> None:
    if ctx.role != "admin":
        raise ApiError(403, "forbidden", "Solo l'amministratore della famiglia può gestire gli accessi.")


def _password() -> str:
    """Facile da dettare al telefono: tre gruppi di lettere e numeri senza caratteri ambigui."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


@router.get("/household/users")
def list_users(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    _admin(ctx)
    rows = db.execute(select(User, HouseholdUser).join(HouseholdUser, HouseholdUser.user_id == User.id)
                      .where(HouseholdUser.household_id == ctx.household_id).order_by(User.login)).all()
    return [{"id": u.id, "login": u.login, "role": m.role, "disabled": u.disabled} for u, m in rows]


@router.post("/household/users", status_code=201)
def create_grandparent(data: GrandparentIn, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Nuovo accesso «nonno»: vede solo la settimana dei nonni. La password si mostra una volta sola."""
    _admin(ctx)
    if db.scalar(select(User).where(User.login == data.login)):
        raise ApiError(409, "login_taken", "Questo nome utente esiste già.")
    password = _password()
    user = User(login=data.login, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(HouseholdUser(household_id=ctx.household_id, user_id=user.id, role="nonno"))
    db.commit()
    return {"id": user.id, "login": user.login, "password": password}


@router.post("/household/users/{user_id}/password")
def reset_grandparent_password(user_id: str, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Nuova password per un accesso dei nonni (dimenticata o telefono cambiato)."""
    _admin(ctx)
    membership = db.get(HouseholdUser, (ctx.household_id, user_id))
    if membership is None or membership.role != "nonno":
        raise ApiError(404, "not_found", "Accesso non trovato.")
    password = _password()
    user = db.get(User, user_id)
    user.password_hash = hash_password(password)
    # Telefono perso o cambiato: gli accessi già aperti con la vecchia password si chiudono.
    for session in db.scalars(select(UserSession).where(UserSession.user_id == user_id)).all():
        db.delete(session)
    db.commit()
    return {"id": user.id, "login": user.login, "password": password}


# --- Programma dei nonni da file (PDF o Word) --------------------------------------------------

class PlanUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=11_000_000)


def _plan_out(plan: GrandparentPlan) -> dict:
    return {"id": plan.id, "filename": plan.filename, "status": plan.status, "notes": plan.notes,
            "source": plan.source, "created_at": plan.created_at,
            "items": [{**item, "summary": describe(item)} for item in plan.items or []]}


def _owned_plan(db: Session, ctx: Ctx, plan_id: str) -> GrandparentPlan:
    plan = db.get(GrandparentPlan, plan_id)
    if plan is None or plan.household_id != ctx.household_id:
        raise ApiError(404, "not_found", "Programma non trovato.")
    return plan


@router.post("/nonni/plans", status_code=201)
def upload_plan(data: PlanUpload, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Carica il file: Hermes lo legge in pochi istanti, poi il programma è da confermare."""
    try:
        raw = base64.b64decode(data.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(422, "invalid_file", "File non valido.") from None
    try:
        plan = create_plan(db, ctx.household_id, ctx.user_id, "app", data.filename, raw)
    except PlanError as exc:
        raise ApiError(422, "invalid_file", str(exc)) from None
    return _plan_out(plan)


@router.get("/nonni/plans")
def list_plans(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Programmi in lettura, da confermare o non letti (le ultime 24 ore per quelli falliti)."""
    rows = db.scalars(select(GrandparentPlan).where(
        GrandparentPlan.household_id == ctx.household_id,
        GrandparentPlan.status.in_(("reading", "pending", "failed")))
        .order_by(GrandparentPlan.created_at.desc())).all()
    recent = utcnow() - timedelta(days=1)
    return [_plan_out(p) for p in rows if p.status != "failed" or p.created_at >= recent]


@router.post("/nonni/plans/{plan_id}/apply")
def confirm_plan(plan_id: str, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    plan = _owned_plan(db, ctx, plan_id)
    try:
        return apply_plan(db, plan, ctx.user_id, utcnow())
    except PlanError as exc:
        raise ApiError(409, "plan_closed", str(exc)) from None


@router.post("/nonni/plans/{plan_id}/discard", status_code=204)
def discard_plan(plan_id: str, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    plan = _owned_plan(db, ctx, plan_id)
    if plan.status in ("reading", "pending", "failed"):
        plan.status = "discarded"
        db.commit()
