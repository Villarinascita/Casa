from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..bill_taxonomy import learn
from ..crud import Resource, audit, build_router, commit
from ..db import get_db
from ..errors import ApiError
from ..models import Bill, Event, Household, Member, ShoppingItem, Task, utcnow
from ..schemas import (BillIn, BillOut, BillPatch, EventIn, EventOut, EventPatch, MemberIn, MemberOut, MemberPatch,
                       ShoppingIn, ShoppingOut, ShoppingPatch, TaskIn, TaskOut, TaskPatch)
from ..security import Ctx, current


def _member_extras(obj: Member, extras: dict, ctx: Ctx) -> dict:
    if "archived" in extras and extras["archived"] is not None and extras["archived"] != obj.archived:
        obj.archived = extras["archived"]
        return {"archived": obj.archived}
    return {}


def _task_extras(obj: Task, extras: dict, ctx: Ctx) -> dict:
    status = extras.get("status")
    if status is None or status == obj.status:
        return {}
    obj.status = status
    obj.completed_at = utcnow() if status == "done" else None
    obj.completed_by = ctx.user_id if status == "done" else None
    return {"status": status}


def _shopping_extras(obj: ShoppingItem, extras: dict, ctx: Ctx) -> dict:
    checked = extras.get("checked")
    if checked is None or checked == (obj.checked_at is not None):
        return {}
    obj.checked_at = utcnow() if checked else None
    obj.checked_by = ctx.user_id if checked else None
    return {"checked": checked}


def _bill_extras(obj: Bill, extras: dict, ctx: Ctx) -> dict:
    state = extras.get("payment_state")
    if state is None or state == obj.payment_state:
        return {}
    obj.payment_state = state
    return {"payment_state": state}


def _bill_learned(db: Session, obj: Bill, changed: dict, ctx: Ctx) -> None:
    """Categoria corretta a mano: quel fornitore da ora va sempre lì."""
    if "category" not in changed and "subcategory" not in changed:
        return
    household = db.get(Household, ctx.household_id)
    settings = learn(household.settings, obj.supplier, obj.category, obj.subcategory)
    if settings is not None:
        household.settings = settings


members = build_router("/members", Resource(
    Member, MemberIn, MemberPatch, MemberOut, extra_fields=("archived",), apply_extras=_member_extras,
    order_by=(Member.sort_order,), references_member=False))

tasks = build_router("/tasks", Resource(
    Task, TaskIn, TaskPatch, TaskOut, extra_fields=("status",), apply_extras=_task_extras))

shopping = build_router("/shopping/items", Resource(
    ShoppingItem, ShoppingIn, ShoppingPatch, ShoppingOut, extra_fields=("checked",),
    apply_extras=_shopping_extras, references_member=False))

bills = build_router("/bills", Resource(
    Bill, BillIn, BillPatch, BillOut, extra_fields=("payment_state",), apply_extras=_bill_extras,
    after_update=_bill_learned,
    order_by=(Bill.due_date,), references_member=False))

events = build_router("/events", Resource(Event, EventIn, EventPatch, EventOut), custom_list=True)


@events.get("", response_model=list[EventOut])
def list_events(ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                start: date | None = Query(None, alias="from", description="Primo giorno incluso (ora locale)"),
                end: date | None = Query(None, alias="to", description="Giorno escluso (ora locale)")):
    """Appuntamenti che si sovrappongono all'intervallo di giorni locali [from, to)."""
    query = select(Event).where(Event.household_id == ctx.household_id, Event.deleted_at.is_(None))
    if start or end:
        if start and end and end <= start:
            raise ApiError(422, "validation_error", "L'intervallo di date non è valido.")
        tz = ZoneInfo(db.get(Household, ctx.household_id).timezone)
        # I confini dei giorni locali si convertono in UTC per ciascun giorno: gestisce i cambi d'ora.
        to_utc = lambda d: datetime.combine(d, time.min, tz).astimezone(timezone.utc)  # noqa: E731
        timed, all_day = [~Event.all_day], [Event.all_day]
        if end:
            timed.append(Event.start_at < to_utc(end))
            all_day.append(Event.start_date < end)
        if start:
            timed.append(func.coalesce(Event.end_at, Event.start_at) >= to_utc(start))
            all_day.append(func.coalesce(Event.end_date, Event.start_date) >= start)
        query = query.where(or_(and_(*timed), and_(*all_day)))
    return db.scalars(query.order_by(Event.start_date, Event.start_at)).all()


@shopping.post("/clear-checked", response_model=list[ShoppingOut])
def clear_checked(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Toglie dalla lista le voci già spuntate (eliminazione soft, recuperabile)."""
    items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == ctx.household_id,
                                                  ShoppingItem.deleted_at.is_(None),
                                                  ShoppingItem.checked_at.is_not(None))).all()
    now = utcnow()
    for item in items:
        item.deleted_at = now
        audit(db, ctx, "delete", item)
    commit(db)
    return items


routers: list[APIRouter] = [members, events, tasks, shopping, bills]
