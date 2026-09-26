"""Programma dei nonni da un file (PDF o Word) caricato dall'app o da Telegram: Hermes lo legge,
la famiglia conferma, gli impegni si creano assegnati ai nonni
(vedi docs/superpowers/specs/2026-09-27-programma-nonni-design.md)."""

import io
import logging
import re
import zipfile
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .hermes_client import HermesInvalidResponse, HermesUnavailable
from .models import Event, GrandparentPlan, Household, Member, utcnow

logger = logging.getLogger(__name__)
MAX_BYTES = 8_000_000
MAX_TEXT = 15_000
MAX_EVENTS = 500
SOURCE = "nonni"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class PlanError(ValueError):
    """Messaggio da mostrare così com'è a chi ha caricato il file."""


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > 10 * MAX_BYTES:
            raise PlanError("Il documento Word è troppo grande.")
        root = ElementTree.fromstring(archive.read(info))
    body = root.find(f"{_W}body")
    lines = []
    for block in (body if body is not None else []):
        if block.tag == f"{_W}p":
            lines.append("".join(t.text or "" for t in block.iter(f"{_W}t")))
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = ["".join(t.text or "" for t in cell.iter(f"{_W}t")).strip() for cell in row.iter(f"{_W}tc")]
                lines.append(" | ".join(cells))
    return "\n".join(line for line in lines if line.strip())


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:20])


def extract_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise PlanError("Il file è troppo grande (massimo 8 MB).")
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            text = _pdf_text(data)
        elif name.endswith(".docx"):
            text = _docx_text(data)
        elif name.endswith((".txt", ".md")):
            text = data.decode("utf-8", "replace")
        elif name.endswith(".doc"):
            raise PlanError("È un Word vecchio (.doc): aprilo e salvalo come .docx o PDF, poi ricaricalo.")
        else:
            raise PlanError("Carica un PDF o un Word (.docx).")
    except PlanError:
        raise
    except Exception as exc:
        raise PlanError("Non riesco ad aprire il file: è forse danneggiato o protetto da password?") from exc
    if not text.strip():
        raise PlanError("Nel file non c'è testo leggibile (forse è una foto o una scansione): "
                        "scrivilo in Word o esportalo come PDF con il testo.")
    return text[:MAX_TEXT]


def create_plan(db: Session, household_id: str, user_id: str, source: str, filename: str, data: bytes) -> GrandparentPlan:
    """Salva il testo del file: la lettura con Hermes la fa il worker (process_plans)."""
    text = extract_text(filename, data)
    plan = GrandparentPlan(household_id=household_id, created_by=user_id, source=source,
                           filename=(filename or "programma")[:200], text=text, status="reading")
    db.add(plan)
    db.commit()
    return plan


def school_year_end(today: date) -> date:
    return date(today.year + (1 if today.month >= 7 else 0), 6, 30)


_TIME = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


def _clock(value) -> str | None:
    match = _TIME.match(str(value or "").strip())
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def _day(value) -> str | None:
    try:
        return date.fromisoformat(str(value)).isoformat() if value else None
    except ValueError:
        return None


def normalize_items(raw: list, today: date) -> list[dict]:
    """Voci pulite: chi, cosa, giorno della settimana (1=lunedì) o data, orari, luogo, fino a quando."""
    items = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not str(entry.get("title") or "").strip() or not str(entry.get("who") or "").strip():
            continue
        weekday = entry.get("weekday")
        weekday = weekday if isinstance(weekday, int) and 1 <= weekday <= 7 else None
        when = _day(entry.get("date"))
        if not weekday and not when:
            continue
        items.append({"who": str(entry["who"]).strip()[:80], "title": str(entry["title"]).strip()[:180],
                      "weekday": None if when else weekday, "date": when,
                      "start": _clock(entry.get("start")), "end": _clock(entry.get("end")),
                      "place": (str(entry.get("place") or "").strip()[:300] or None),
                      "until": (_day(entry.get("until")) or school_year_end(today).isoformat()) if not when else None})
    return items


def process_plans(db: Session, read: Callable[[str, list[str], date], dict], now: datetime,
                  notify: Callable[[GrandparentPlan, str], None] | None = None) -> int:
    """Fa leggere a Hermes i programmi appena caricati; un errore lascia il programma «failed» con il motivo."""
    done = 0
    for plan in db.scalars(select(GrandparentPlan).where(GrandparentPlan.status == "reading")).all():
        household = db.get(Household, plan.household_id)
        tz = ZoneInfo(household.timezone)
        members = [m.display_name for m in db.scalars(select(Member).where(
            Member.household_id == household.id, Member.archived.is_(False), Member.deleted_at.is_(None)))]
        try:
            result = read(plan.text, members, now.astimezone(tz).date())
            plan.items = normalize_items(result.get("items"), now.astimezone(tz).date())
            plan.notes = (str(result.get("notes") or "").strip()[:1000] or None)
            plan.status = "pending" if plan.items else "failed"
            if not plan.items:
                plan.notes = plan.notes or "Non ho trovato impegni con giorno e nonno: controlla il file."
        except HermesUnavailable as exc:
            if not isinstance(exc, HermesInvalidResponse):
                db.rollback()
                continue  # Hermes momentaneamente non raggiungibile: si riprova al prossimo giro
            logger.exception("Programma dei nonni non leggibile")
            db.rollback()
            plan = db.get(GrandparentPlan, plan.id)
            plan.status, plan.notes = "failed", "Hermes non è riuscito a capire il file: prova a scriverlo più semplice."
        except Exception:
            logger.exception("Lettura del programma dei nonni non riuscita")
            db.rollback()
            plan = db.get(GrandparentPlan, plan.id)
            plan.status, plan.notes = "failed", "Hermes non è riuscito a leggere il file: riprova tra poco."
        db.commit()
        done += 1
        if notify:
            try:
                notify(plan, summary(plan))
            except Exception:
                logger.exception("Avviso del programma dei nonni non inviato")
    return done


DAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def describe(item: dict) -> str:
    when = (f"ogni {DAYS[item['weekday'] - 1]}" if item.get("weekday")
            else date.fromisoformat(item["date"]).strftime("%d/%m"))
    hours = f" {item['start']}" + (f"–{item['end']}" if item.get("end") else "") if item.get("start") else ""
    until = f" (fino al {date.fromisoformat(item['until']).strftime('%d/%m/%Y')})" if item.get("until") else ""
    place = f" · {item['place']}" if item.get("place") else ""
    return f"{item['who']} · {when}{hours} · {item['title']}{place}{until}"


def summary(plan: GrandparentPlan) -> str:
    if plan.status == "failed":
        return f"Non sono riuscito a leggere «{plan.filename}»: {plan.notes}"
    lines = "\n".join(f"• {describe(i)}" for i in plan.items[:25])
    more = f"\n…e altri {len(plan.items) - 25}" if len(plan.items) > 25 else ""
    notes = f"\n\nDa verificare: {plan.notes}" if plan.notes else ""
    return f"Ho letto «{plan.filename}». Ecco il programma dei nonni:\n{lines}{more}{notes}"


def _occurrences(item: dict, today: date) -> list[date]:
    if item.get("date"):
        day = date.fromisoformat(item["date"])
        return [day] if day >= today else []
    until = date.fromisoformat(item["until"])
    first = today + timedelta(days=(item["weekday"] - 1 - today.weekday()) % 7)
    return [first + timedelta(weeks=w) for w in range(0, max(0, (until - first).days) // 7 + 1)]


def apply_plan(db: Session, plan: GrandparentPlan, user_id: str, now: datetime) -> dict:
    """Crea i nonni mancanti e gli impegni; quelli futuri di un programma precedente si sostituiscono."""
    if plan.status != "pending":
        raise PlanError("Questo programma è già stato confermato o scartato.")
    household = db.get(Household, plan.household_id)
    tz = ZoneInfo(household.timezone)
    today = now.astimezone(tz).date()
    members = {m.display_name.strip().lower(): m for m in db.scalars(select(Member).where(
        Member.household_id == household.id, Member.archived.is_(False), Member.deleted_at.is_(None)))}
    created_members = []
    for who in dict.fromkeys(i["who"] for i in plan.items):
        if who.lower() not in members:
            member = Member(household_id=household.id, display_name=who,
                            relation="nonna" if who.lower().startswith("nonna") else "nonno", sort_order=50)
            db.add(member)
            db.flush()
            members[who.lower()] = member
            created_members.append(who)
    grandparents = list(dict.fromkeys([*((household.settings or {}).get("grandparent_members") or []),
                                       *(members[i["who"].lower()].id for i in plan.items)]))
    household.settings = {**(household.settings or {}), "grandparent_members": grandparents}
    replaced = 0
    for event in db.scalars(select(Event).where(Event.household_id == household.id, Event.source == SOURCE,
                                                Event.deleted_at.is_(None))).all():
        start = event.start_date if event.all_day else event.start_at.astimezone(tz).date()
        if start >= today:
            event.deleted_at = utcnow()
            replaced += 1
    created = 0
    for item in plan.items:
        member = members[item["who"].lower()]
        for day in _occurrences(item, today):
            if created >= MAX_EVENTS:
                break
            event = Event(household_id=household.id, created_by=user_id, title=item["title"],
                          location=item.get("place"), member_id=member.id, source=SOURCE)
            if item.get("start"):
                start = datetime.combine(day, time.fromisoformat(item["start"]), tzinfo=tz)
                event.start_at = start
                event.end_at = (datetime.combine(day, time.fromisoformat(item["end"]), tzinfo=tz)
                                if item.get("end") and item["end"] > item["start"] else None)
            else:
                event.all_day, event.start_date = True, day
            db.add(event)
            created += 1
    plan.status, plan.applied_at = "applied", utcnow()
    db.commit()
    return {"created": created, "replaced": replaced, "new_members": created_members}
