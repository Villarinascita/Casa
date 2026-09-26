"""Riconoscimento dei doppioni tra appuntamenti e attività scritti in modo diverso
(vedi docs/superpowers/specs/2026-09-26-doppioni-e-abitudini-design.md §2)."""

import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Event, Task

SAME = 0.85
DOUBTFUL = 0.34
SAME_TASK = 0.85
TIME_TOLERANCE = timedelta(minutes=60)
_STOP = {
    "a", "ad", "al", "alla", "alle", "allo", "agli", "ai", "con", "da", "dal", "dalla", "dei", "del", "della",
    "delle", "di", "e", "ed", "gli", "i", "il", "in", "la", "le", "lo", "nel", "nella", "per", "su", "tra",
    "un", "una", "uno", "o", "ore", "h", "appuntamento", "evento", "inizio", "the", "and", "of",
}


def _stem(word: str) -> str:
    return word[:6]


def words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    # «8.00» e «8» sono la stessa ora: gli zeri da soli non contano.
    return [w for w in re.findall(r"[a-z0-9]+", plain) if w not in _STOP and w.strip("0")]


def _bag(text: str) -> tuple[set[str], int]:
    """Radici delle parole più le coppie consecutive unite («gioca gym» → «giocagym»)."""
    ws = words(text)
    bag = {_stem(w) for w in ws} | {_stem(a + b) for a, b in zip(ws, ws[1:])}
    return bag, len({_stem(w) for w in ws})


def _identifiers(text: str) -> set[str]:
    """Numeri di almeno 5 cifre (ordini, contratti, pratiche); gli anni come 2026 non contano."""
    return {n for n in re.findall(r"\d+", text or "") if len(n) >= 5}


def _significant(stem: str) -> bool:
    return len(stem) >= 4 and not stem.isdigit()


def _size(text: str) -> int:
    return _bag(text)[1]


def similarity(a: str, b: str) -> float:
    """Quota delle parole del titolo più corto presenti anche nell'altro (ordine indifferente).
    Numeri identificativi diversi (ordine, contratto, pratica) indicano cose diverse."""
    ids_a, ids_b = _identifiers(a), _identifiers(b)
    if ids_a and ids_b and not ids_a & ids_b:
        return 0.0
    bag_a, n_a = _bag(a)
    bag_b, n_b = _bag(b)
    common = bag_a & bag_b
    if not n_a or not n_b or not any(_significant(s) for s in common):
        return 0.0
    return min(1.0, len(common) / min(n_a, n_b))


def _local_day(event_data: dict, tz: ZoneInfo) -> date | None:
    if event_data.get("all_day"):
        return event_data.get("start_date")
    start = event_data.get("start_at")
    return start.astimezone(tz).date() if start else None


def events_on_day(db: Session, household_id: str, day: date, tz: ZoneInfo) -> list[Event]:
    start = datetime.combine(day - timedelta(days=1), datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=3)
    rows = db.scalars(select(Event).where(
        Event.household_id == household_id, Event.deleted_at.is_(None),
        or_(Event.start_at.between(start, end),
            Event.start_date.between(day - timedelta(days=31), day)))).all()
    found = []
    for event in rows:
        if event.all_day:
            if event.start_date <= day <= (event.end_date or event.start_date):
                found.append(event)
        elif event.start_at.astimezone(tz).date() == day:
            found.append(event)
    return found


def find_same_event(db: Session, household_id: str, data: dict, tz: ZoneInfo,
                    judge=None) -> tuple[Event | None, bool]:
    """(evento già presente o None, True se è lo stesso ma con un orario diverso)."""
    day = _local_day(data, tz)
    if day is None:
        return None, False
    candidates = events_on_day(db, household_id, day, tz)
    scored = sorted(((similarity(data.get("title", ""), e.title), e) for e in candidates),
                    key=lambda pair: pair[0], reverse=True)
    # Titoli di una sola parola («LIONE») sono troppo vaghi per decidere da soli: caso dubbio.
    title = data.get("title", "")
    match = next((e for score, e in scored if score >= SAME and
                  (min(_size(title), _size(e.title)) >= 2 or _bag(title)[0] == _bag(e.title)[0])), None)
    if match is None and judge is not None:
        doubtful = [e for score, e in scored if score >= DOUBTFUL and e is not match]
        if doubtful:
            try:
                index = judge(data.get("title", ""), [e.title for e in doubtful])
            except Exception:
                index = None
            if isinstance(index, int) and 0 <= index < len(doubtful):
                match = doubtful[index]
    if match is None:
        return None, False
    new_start = data.get("start_at")
    if new_start and not data.get("all_day") and not match.all_day and match.start_at:
        return match, abs(new_start - match.start_at) > TIME_TOLERANCE
    return match, False


def find_same_task(db: Session, household_id: str, title: str) -> Task | None:
    open_tasks = db.scalars(select(Task).where(Task.household_id == household_id, Task.deleted_at.is_(None),
                                               Task.status == "open")).all()
    return next((t for t in open_tasks if similarity(title, t.title) >= SAME_TASK), None)
