"""Importazione una tantum dei dati del prototipo locale (localStorage «insieme-v1»)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crud import audit, idempotent_create
from ..db import get_db
from ..models import Event, Household, Member, ShoppingItem, Task, utcnow
from ..schemas import LegacyImportIn, LegacyImportOut
from ..security import Ctx, current

router = APIRouter(tags=["import"])


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.post("/import/local", response_model=LegacyImportOut, status_code=201)
def import_local(data: LegacyImportIn, request: Request, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                 idempotency_key: str | None = Header(None)):
    def produce():
        household = db.get(Household, ctx.household_id)
        tz = ZoneInfo(household.timezone)
        existing = db.scalars(select(Member).where(Member.household_id == ctx.household_id,
                                                   Member.deleted_at.is_(None))).all()
        by_name = {m.display_name.casefold(): m for m in existing}
        created = 0

        def member_for(name: str | None) -> Member | None:
            nonlocal created
            name = (name or "").strip()[:80]
            if not name:
                return None
            if name.casefold() not in by_name:
                member = Member(household_id=ctx.household_id, created_by=ctx.user_id, display_name=name,
                                sort_order=len(by_name))
                db.add(member)
                db.flush()
                by_name[name.casefold()] = member
                created += 1
            return by_name[name.casefold()]

        for name in data.members:
            member_for(name)

        counts = {"events": 0, "tasks": 0, "shopping": 0}
        skipped: list[str] = []
        for item in data.items:
            title = item.title.strip()[:180]
            if not title:
                continue
            member = member_for(item.person)
            member_id = member.id if member else None
            day, at = _parse_date(item.date), _parse_time(item.time)
            note = (item.note or "").strip() or None
            if item.type == "event":
                if day is None:
                    skipped.append(title)
                    continue
                if at is None:
                    obj = Event(all_day=True, start_date=day)
                else:
                    obj = Event(all_day=False, start_at=datetime.combine(day, at, tz))
                obj.title, obj.location, obj.member_id, obj.source = title, note, member_id, "import-local"
                counts["events"] += 1
            elif item.type == "task":
                notes = " · ".join(filter(None, [item.time, note])) or None
                obj = Task(title=title, notes=notes, due_date=day, member_id=member_id,
                           status="done" if item.done else "open", completed_at=utcnow() if item.done else None)
                counts["tasks"] += 1
            else:
                obj = ShoppingItem(label=title[:120], quantity=None, checked_at=utcnow() if item.done else None)
                counts["shopping"] += 1
            obj.household_id, obj.created_by = ctx.household_id, ctx.user_id
            db.add(obj)

        areas = [a.strip()[:60] for a in data.areas if a.strip()]
        if areas:
            current_areas = list((household.settings or {}).get("areas", []))
            household.settings = {**(household.settings or {}),
                                  "areas": list(dict.fromkeys(current_areas + areas))[:30]}
        db.flush()
        audit(db, ctx, "import", household, {"members": created, **counts})
        return LegacyImportOut(members_created=created, skipped=skipped, **counts)

    return idempotent_create(db, ctx, request, idempotency_key, produce, LegacyImportOut)
