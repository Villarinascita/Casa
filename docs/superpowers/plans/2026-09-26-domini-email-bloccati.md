# Domini email bloccati — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettere a Luca di indicare in Impostazioni i domini email da ignorare: le email future da quei domini vanno nel cestino di Gmail prima di qualsiasi analisi Hermes, quelle già in casella vengono spostate nel cestino in background.

**Architecture:** L'elenco sta in `household.settings["blocked_email_domains"]` (stesso meccanismo di `bill_categories`). Un modulo puro `email_domains.py` normalizza i domini e confronta l'header `From:`. `gmail_sync.ingest_message` salta Hermes e mette nel cestino le email bloccate. Una nuova tabella `email_domain_cleanups` tiene lo stato della pulizia retroattiva, eseguita dal worker a pagine da 50 tramite `email_cleanup.run_domain_cleanups`. Lo scope Google passa da `gmail.readonly` a `gmail.modify`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, httpx, pytest; frontend JS a moduli ES senza build.

## Global Constraints

- Sempre cestino Gmail (`POST .../messages/{id}/trash`), mai `messages.delete` né cancellazione permanente.
- Il confronto usa solo l'header `From:` (mai corpo o oggetto). Un dominio bloccato `d` corrisponde se il dominio del mittente è `d` oppure termina con `.d`.
- Un'email da dominio bloccato non viene mai passata a Hermes (nessuna chiamata `analyze`).
- Validazione domini: minuscole, spazi e punto finale tolti, niente `@`, almeno un punto, solo `[a-z0-9.-]`, max 253 caratteri, dedup, max 100 voci; un valore non valido → HTTP 422.
- Un 403 dal cestino (permesso mancante) non deve mai fermare la sincronizzazione: email segnata processata senza analisi, `connection.last_error` = `"Ricollega Google in Impostazioni per consentire lo spostamento nel cestino."`, pulizia retroattiva resta `running`.
- Rimuovere un dominio chiude (`done`) la sua pulizia, non ripristina nulla dal cestino.
- Stile: docstring/commenti in italiano, doppi apici in Python, apici singoli in JS, nessuna nuova dipendenza.
- Ogni task termina con `cd backend && uv run pytest -q` tutto verde.
- Spec: `docs/superpowers/specs/2026-09-26-domini-email-bloccati-design.md`.

---

## Task 1: Domini — normalizzazione, confronto mittente, campo della famiglia

**Files:**
- Create: `backend/app/email_domains.py`
- Create: `backend/tests/test_email_domains.py`
- Modify: `backend/app/schemas.py` (`HouseholdOut`, `HouseholdPatch`)
- Modify: `backend/app/routers/auth.py` (`household_out`, `update_household`)
- Test: `backend/tests/test_resources.py`

**Interfaces:**
- Produces: `normalize_domain(value: str) -> str` (ValueError se non valido), `sender_domain(from_header: str) -> str | None`, `is_blocked_sender(from_header: str, blocked_domains: Iterable[str]) -> bool` in `app.email_domains`. `HouseholdOut.blocked_email_domains: list[str]`, `HouseholdPatch.blocked_email_domains: list[str] | None`.

- [ ] **Step 1: Scrivere i test delle funzioni pure**

Crea `backend/tests/test_email_domains.py`:

```python
import pytest

from app.email_domains import is_blocked_sender, normalize_domain, sender_domain


def test_sender_domain_da_header_con_nome():
    assert sender_domain('"Octopus Energy" <Ciao@OctopusEnergy.it>') == "octopusenergy.it"


def test_sender_domain_senza_indirizzo():
    assert sender_domain("nessuno") is None
    assert sender_domain("") is None


@pytest.mark.parametrize("header,expected", [
    ("info@newsletter.com", True),
    ("Offerte <promo@offerte.newsletter.com>", True),
    ("x@notnewsletter.com", False),
    ("x@newsletter.com.evil.it", False),
    ("", False),
])
def test_is_blocked_sender(header, expected):
    assert is_blocked_sender(header, ["newsletter.com"]) is expected


def test_normalize_domain():
    assert normalize_domain("  News.COM. ") == "news.com"
    for bad in ["a@b.com", "nodot", "sp ace.com", "a..b.com", ""]:
        with pytest.raises(ValueError):
            normalize_domain(bad)
```

- [ ] **Step 2: Eseguire e verificare che fallisca**

Esegui: `cd backend && uv run pytest tests/test_email_domains.py -v`
Atteso: `ModuleNotFoundError: No module named 'app.email_domains'`

- [ ] **Step 3: Scrivere `backend/app/email_domains.py`**

```python
"""Domini email bloccati: normalizzazione e confronto con il mittente (solo header From)."""

import re
from collections.abc import Iterable
from email.utils import parseaddr

_DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$")


def normalize_domain(value: str) -> str:
    """Dominio in minuscolo, senza spazi né punto finale; ValueError se non accettabile."""
    domain = value.strip().lower().rstrip(".")
    if "@" in domain or not _DOMAIN.match(domain):
        raise ValueError(f"«{value}» non è un dominio valido (es. newsletter.com).")
    return domain


def sender_domain(from_header: str) -> str | None:
    address = parseaddr(from_header or "")[1].strip().lower()
    if "@" not in address:
        return None
    return address.rsplit("@", 1)[1].rstrip(".") or None


def is_blocked_sender(from_header: str, blocked_domains: Iterable[str]) -> bool:
    """Vero se il mittente appartiene a un dominio bloccato o a un suo sottodominio."""
    domain = sender_domain(from_header)
    if not domain:
        return False
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in blocked_domains)
```

- [ ] **Step 4: Eseguire e verificare che passi**

Esegui: `cd backend && uv run pytest tests/test_email_domains.py -v`
Atteso: `8 passed`

- [ ] **Step 5: Scrivere i test API**

Aggiungi in fondo a `backend/tests/test_resources.py`:

```python
def test_domini_bloccati_normalizzati(luca):
    household = luca.get("/api/v1/household").json()
    assert household["blocked_email_domains"] == []
    updated = luca.patch("/api/v1/household",
                         json={"blocked_email_domains": [" Newsletter.COM ", "newsletter.com"]},
                         headers={"If-Match": str(household["version"])})
    assert updated.status_code == 200, updated.text
    assert updated.json()["blocked_email_domains"] == ["newsletter.com"]


def test_domini_bloccati_rifiuta_valori_non_validi(luca):
    household = luca.get("/api/v1/household").json()
    for bad in ["tizio@gmail.com", "localhost", "news letter.com"]:
        response = luca.patch("/api/v1/household", json={"blocked_email_domains": [bad]},
                              headers={"If-Match": str(household["version"])})
        assert response.status_code == 422, bad
```

- [ ] **Step 6: Eseguire e verificare che falliscano**

Esegui: `cd backend && uv run pytest tests/test_resources.py -k domini_bloccati -v`
Atteso: FAIL (`KeyError: 'blocked_email_domains'`).

- [ ] **Step 7: Aggiornare `backend/app/schemas.py`**

In cima, accanto agli altri import `from ...`, aggiungi:

```python
from .email_domains import normalize_domain
```

Sostituisci il blocco `HouseholdOut`/`HouseholdPatch` con:

```python
class HouseholdOut(OutSchema):
    id: str
    name: str
    timezone: str
    version: int
    areas: list[str]
    bill_categories: list[str]
    blocked_email_domains: list[str]


class HouseholdPatch(Schema):
    name: Text(120) | None = None
    areas: list[Text(60)] | None = Field(default=None, max_length=30)
    bill_categories: list[Text(60)] | None = Field(default=None, max_length=30)
    blocked_email_domains: list[str] | None = Field(default=None, max_length=100)

    @field_validator("areas", "bill_categories")
    @classmethod
    def _unique_list(cls, value):
        return None if value is None else list(dict.fromkeys(value))

    @field_validator("blocked_email_domains")
    @classmethod
    def _valid_domains(cls, value):
        return None if value is None else list(dict.fromkeys(normalize_domain(item) for item in value))
```

- [ ] **Step 8: Aggiornare `backend/app/routers/auth.py`**

Sostituisci `household_out` con:

```python
def household_out(household: Household) -> HouseholdOut:
    settings = household.settings or {}
    return HouseholdOut(id=household.id, name=household.name, timezone=household.timezone,
                        version=household.version, areas=list(settings.get("areas", [])),
                        bill_categories=list(settings.get("bill_categories", DEFAULT_BILL_CATEGORIES)),
                        blocked_email_domains=list(settings.get("blocked_email_domains", [])))
```

In `update_household`, dopo il blocco `if data.bill_categories is not None: ...`, aggiungi:

```python
    if data.blocked_email_domains is not None:
        household.settings = {**(household.settings or {}), "blocked_email_domains": data.blocked_email_domains}
```

- [ ] **Step 9: Eseguire e verificare che passino, poi suite intera**

Esegui: `cd backend && uv run pytest tests/test_resources.py -k domini_bloccati -v` → `2 passed`
Esegui: `cd backend && uv run pytest -q` → tutto verde.

- [ ] **Step 10: Commit**

```bash
git add backend/app/email_domains.py backend/tests/test_email_domains.py backend/app/schemas.py backend/app/routers/auth.py backend/tests/test_resources.py
git commit -m "Aggiunge i domini email bloccati alla famiglia con validazione"
```

---

## Task 2: Tabella delle pulizie, avvio al salvataggio, endpoint di stato

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/20260926_01_domini_email_bloccati.py`
- Create: `backend/app/email_cleanup.py`
- Modify: `backend/app/schemas.py` (nuovo `EmailCleanupOut`)
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_resources.py`

**Interfaces:**
- Consumes: `HouseholdPatch.blocked_email_domains` (Task 1).
- Produces: modello `EmailDomainCleanup` (`id`, `household_id`, `connection_id`, `domain`, `status` `running|done`, `page_token`, `trashed_count`, `created_at`, `completed_at`); `queue_domain_cleanups(db, household_id: str, previous: Iterable[str], current: Iterable[str]) -> None` in `app.email_cleanup`; `GET /api/v1/household/email-cleanups` → lista di `{domain, status, trashed_count, created_at, completed_at}`.

- [ ] **Step 1: Scrivere il test**

Aggiungi in fondo a `backend/tests/test_resources.py`:

```python
from sqlalchemy import select

from app.models import GoogleConnection, User


def _connect_google(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        db.add(GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                refresh_token_encrypted="x"))
        db.commit()


def test_bloccare_un_dominio_avvia_la_pulizia_solo_per_i_nuovi(luca, db_factory, seed):
    _connect_google(db_factory, seed)
    household = luca.get("/api/v1/household").json()
    first = luca.patch("/api/v1/household", json={"blocked_email_domains": ["a.com"]},
                       headers={"If-Match": str(household["version"])}).json()
    second = luca.patch("/api/v1/household", json={"blocked_email_domains": ["a.com", "b.com"]},
                        headers={"If-Match": str(first["version"])}).json()
    cleanups = luca.get("/api/v1/household/email-cleanups").json()
    assert sorted(c["domain"] for c in cleanups) == ["a.com", "b.com"]
    assert all(c["status"] == "running" and c["trashed_count"] == 0 for c in cleanups)
    luca.patch("/api/v1/household", json={"blocked_email_domains": ["b.com"]},
               headers={"If-Match": str(second["version"])})
    by_domain = {c["domain"]: c for c in luca.get("/api/v1/household/email-cleanups").json()}
    assert by_domain["a.com"]["status"] == "done" and by_domain["a.com"]["completed_at"]
    assert by_domain["b.com"]["status"] == "running"
```

- [ ] **Step 2: Eseguire e verificare che fallisca**

Esegui: `cd backend && uv run pytest tests/test_resources.py -k avvia_la_pulizia -v`
Atteso: FAIL (404 su `/household/email-cleanups`).

- [ ] **Step 3: Modello in `backend/app/models.py`**

Subito dopo la classe `EmailCreationNotice`, aggiungi:

```python
class EmailDomainCleanup(Base):
    """Pulizia retroattiva (cestino Gmail) delle email già in casella da un dominio appena bloccato."""

    __tablename__ = "email_domain_cleanups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("google_connections.id"), index=True)
    domain: Mapped[str] = mapped_column(String(253))
    status: Mapped[str] = mapped_column(String(10), default="running")
    page_token: Mapped[str | None] = mapped_column(String(500))
    trashed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (CheckConstraint("status IN ('running', 'done')", name="ck_email_domain_cleanups_status"),)
```

- [ ] **Step 4: Migrazione `backend/alembic/versions/20260926_01_domini_email_bloccati.py`**

```python
"""Pulizia retroattiva delle email dei domini bloccati.

Revision ID: 20260926_01
Revises: 20260925_01
"""

from alembic import op
import sqlalchemy as sa

from app.models import UTCDateTime

revision = "20260926_01"
down_revision = "20260925_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("email_domain_cleanups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("google_connections.id"), nullable=False),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("page_token", sa.String(500)),
        sa.Column("trashed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("completed_at", UTCDateTime()),
        sa.CheckConstraint("status IN ('running', 'done')", name="ck_email_domain_cleanups_status"))
    op.create_index("ix_email_domain_cleanups_household_id", "email_domain_cleanups", ["household_id"])
    op.create_index("ix_email_domain_cleanups_connection_id", "email_domain_cleanups", ["connection_id"])


def downgrade() -> None:
    op.drop_table("email_domain_cleanups")
```

- [ ] **Step 5: Creare `backend/app/email_cleanup.py`**

```python
"""Pulizia retroattiva delle email dei domini bloccati (cestino Gmail, mai cancellazione)."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EmailDomainCleanup, GoogleConnection, utcnow


def queue_domain_cleanups(db: Session, household_id: str, previous: Iterable[str], current: Iterable[str]) -> None:
    """Avvia una pulizia per ogni dominio appena aggiunto; chiude quelle dei domini tolti."""
    previous, current = set(previous), set(current)
    connections = db.scalars(select(GoogleConnection).where(GoogleConnection.household_id == household_id)).all()
    for domain in sorted(current - previous):
        for connection in connections:
            db.add(EmailDomainCleanup(household_id=household_id, connection_id=connection.id, domain=domain))
    removed = previous - current
    if removed:
        for row in db.scalars(select(EmailDomainCleanup).where(
                EmailDomainCleanup.household_id == household_id, EmailDomainCleanup.status == "running",
                EmailDomainCleanup.domain.in_(removed))).all():
            row.status = "done"
            row.completed_at = utcnow()
```

- [ ] **Step 6: Schema `EmailCleanupOut` in `backend/app/schemas.py`**

Subito dopo `MeOut`, aggiungi:

```python
class EmailCleanupOut(OutSchema):
    domain: str
    status: str
    trashed_count: int
    created_at: datetime
    completed_at: datetime | None
```

- [ ] **Step 7: Collegare in `backend/app/routers/auth.py`**

Import (modifica le righe esistenti):

```python
from ..email_cleanup import queue_domain_cleanups
from ..models import EmailDomainCleanup, Household, HouseholdUser, User
from ..schemas import DEFAULT_BILL_CATEGORIES, EmailCleanupOut, HouseholdOut, HouseholdPatch, LoginIn, MeOut
```

In `update_household`, sostituisci il blocco aggiunto al Task 1 con:

```python
    if data.blocked_email_domains is not None:
        previous = list((household.settings or {}).get("blocked_email_domains", []))
        household.settings = {**(household.settings or {}), "blocked_email_domains": data.blocked_email_domains}
        queue_domain_cleanups(db, household.id, previous, data.blocked_email_domains)
```

In fondo al file aggiungi:

```python
@router.get("/household/email-cleanups", response_model=list[EmailCleanupOut])
def list_email_cleanups(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    return db.scalars(select(EmailDomainCleanup).where(EmailDomainCleanup.household_id == ctx.household_id)
                      .order_by(EmailDomainCleanup.created_at.desc())).all()
```

- [ ] **Step 8: Eseguire il test e la suite**

Esegui: `cd backend && uv run pytest tests/test_resources.py -k avvia_la_pulizia -v` → `1 passed`
Esegui: `cd backend && uv run pytest -q` → tutto verde.

- [ ] **Step 9: Verificare la migrazione (PowerShell, da `backend/`)**

```powershell
$env:INSIEME_DATABASE_URL = "sqlite:///$PWD/../.local/migration-check.db"
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
Remove-Item "$PWD/../.local/migration-check.db"
Remove-Item Env:\INSIEME_DATABASE_URL
```
Atteso: nessun errore.

- [ ] **Step 10: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/20260926_01_domini_email_bloccati.py backend/app/email_cleanup.py backend/app/schemas.py backend/app/routers/auth.py backend/tests/test_resources.py
git commit -m "Avvia la pulizia retroattiva quando si blocca un dominio"
```

---

## Task 3: Cestino Gmail e giro di pulizia retroattiva

**Files:**
- Modify: `backend/app/email_cleanup.py`
- Create: `backend/tests/test_email_cleanup.py`

**Interfaces:**
- Consumes: `EmailDomainCleanup` (Task 2), `is_blocked_sender` (Task 1), `service.api.get(url, token, params)`, `service.api.post(url, token, body)`, `service.access_token(connection)` (esistenti in `app.google`).
- Produces: `TRASH_PERMISSION_MESSAGE: str`, `class TrashNotPermitted(Exception)`, `trash_message(service, token: str, message_id: str) -> None` (403 → `TrashNotPermitted`, 404 ignorato), `run_domain_cleanups(db: Session, service, now: datetime) -> int` (email spostate nel giro).

- [ ] **Step 1: Scrivere i test**

Crea `backend/tests/test_email_cleanup.py`:

```python
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.email_cleanup import TRASH_PERMISSION_MESSAGE, run_domain_cleanups, trash_message
from app.models import EmailDomainCleanup, GoogleConnection, User

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


class FakeApi:
    def __init__(self, pages, senders, status=None):
        self.pages = pages
        self.senders = senders
        self.status = status
        self.trashed = []
        self.list_params = []

    def get(self, url, token, params=None):
        if url.endswith("/messages"):
            self.list_params.append(params)
            return self.pages.pop(0)
        return {"payload": {"headers": [{"name": "From", "value": self.senders[url.rsplit("/", 1)[1]]}]}}

    def post(self, url, token, body):
        if self.status:
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError(str(self.status), request=request,
                                        response=httpx.Response(self.status, request=request))
        self.trashed.append(url.rsplit("/", 2)[1])
        return {}


class FakeService:
    def __init__(self, api):
        self.api = api

    def access_token(self, connection):
        return "token"


def _cleanup(db, seed, domain="news.com"):
    user = db.scalar(select(User).where(User.login == "luca"))
    connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                  refresh_token_encrypted="x")
    db.add(connection)
    db.flush()
    db.add(EmailDomainCleanup(household_id=seed["Rossi"], connection_id=connection.id, domain=domain))
    db.commit()
    return connection


def test_pulizia_sposta_solo_il_dominio_esatto_e_si_chiude(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}, {"id": "m2"}]}],
                      {"m1": "Promo <a@offerte.news.com>", "m2": "b@notnews.com"})
        assert run_domain_cleanups(db, FakeService(api), NOW) == 1
        row = db.scalar(select(EmailDomainCleanup))
        assert api.trashed == ["m1"]
        assert api.list_params[0]["q"] == "in:inbox from:news.com"
        assert row.status == "done" and row.trashed_count == 1 and row.completed_at == NOW


def test_pulizia_su_piu_giri_usa_il_segnalibro(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}], "nextPageToken": "p2"}, {"messages": [{"id": "m2"}]}],
                      {"m1": "a@news.com", "m2": "b@news.com"})
        service = FakeService(api)
        run_domain_cleanups(db, service, NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token == "p2"
        run_domain_cleanups(db, service, NOW)
        assert api.list_params[1]["pageToken"] == "p2"
        assert row.status == "done" and row.trashed_count == 2


def test_pulizia_senza_permesso_resta_in_corso_e_avvisa(db_factory, seed):
    with db_factory() as db:
        connection = _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}]}], {"m1": "a@news.com"}, status=403)
        assert run_domain_cleanups(db, FakeService(api), NOW) == 0
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.trashed_count == 0
        assert db.get(GoogleConnection, connection.id).last_error == TRASH_PERMISSION_MESSAGE


def test_trash_message_ignora_email_gia_sparita():
    trash_message(FakeService(FakeApi([], {}, status=404)), "token", "m1")
```

- [ ] **Step 2: Eseguire e verificare che fallisca**

Esegui: `cd backend && uv run pytest tests/test_email_cleanup.py -v`
Atteso: `ImportError: cannot import name 'TRASH_PERMISSION_MESSAGE'`.

- [ ] **Step 3: Completare `backend/app/email_cleanup.py`**

Sostituisci il contenuto del file con:

```python
"""Pulizia retroattiva delle email dei domini bloccati (cestino Gmail, mai cancellazione)."""

import logging
from collections.abc import Iterable
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .email_domains import is_blocked_sender
from .models import EmailDomainCleanup, GoogleConnection, utcnow

logger = logging.getLogger(__name__)

GMAIL_MESSAGES = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
TRASH_PERMISSION_MESSAGE = "Ricollega Google in Impostazioni per consentire lo spostamento nel cestino."


class TrashNotPermitted(Exception):
    """Gmail rifiuta il cestino (403): la connessione ha solo il permesso di lettura."""


def trash_message(service, token: str, message_id: str) -> None:
    """Sposta un'email nel cestino di Gmail (recuperabile 30 giorni). Mai cancellazione permanente."""
    try:
        service.api.post(f"{GMAIL_MESSAGES}/{message_id}/trash", token, {})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise TrashNotPermitted(TRASH_PERMISSION_MESSAGE) from exc
        if exc.response.status_code == 404:
            return  # già sparita: niente da fare
        raise


def queue_domain_cleanups(db: Session, household_id: str, previous: Iterable[str], current: Iterable[str]) -> None:
    """Avvia una pulizia per ogni dominio appena aggiunto; chiude quelle dei domini tolti."""
    previous, current = set(previous), set(current)
    connections = db.scalars(select(GoogleConnection).where(GoogleConnection.household_id == household_id)).all()
    for domain in sorted(current - previous):
        for connection in connections:
            db.add(EmailDomainCleanup(household_id=household_id, connection_id=connection.id, domain=domain))
    removed = previous - current
    if removed:
        for row in db.scalars(select(EmailDomainCleanup).where(
                EmailDomainCleanup.household_id == household_id, EmailDomainCleanup.status == "running",
                EmailDomainCleanup.domain.in_(removed))).all():
            row.status = "done"
            row.completed_at = utcnow()


def _sender(service, token: str, message_id: str) -> str:
    meta = service.api.get(f"{GMAIL_MESSAGES}/{message_id}", token,
                           {"format": "metadata", "metadataHeaders": "From"})
    return next((h.get("value", "") for h in meta.get("payload", {}).get("headers", [])
                 if h.get("name", "").lower() == "from"), "")


def run_domain_cleanups(db: Session, service, now: datetime) -> int:
    """Una pagina (max 50) per ogni pulizia in corso; ritorna quante email ha spostato nel cestino."""
    moved = 0
    for row in db.scalars(select(EmailDomainCleanup).where(EmailDomainCleanup.status == "running")).all():
        connection = db.get(GoogleConnection, row.connection_id)
        if connection is None:
            row.status, row.completed_at = "done", now
            db.commit()
            continue
        try:
            token = service.access_token(connection)
            params = {"q": f"in:inbox from:{row.domain}", "maxResults": 50}
            if row.page_token:
                params["pageToken"] = row.page_token
            page = service.api.get(GMAIL_MESSAGES, token, params)
            for item in page.get("messages", []):
                # La ricerca Gmail «from:» è per sottostringa: si verifica il dominio esatto.
                if not is_blocked_sender(_sender(service, token, item["id"]), [row.domain]):
                    continue
                trash_message(service, token, item["id"])
                row.trashed_count += 1
                moved += 1
                db.commit()
        except TrashNotPermitted:
            connection.last_error = TRASH_PERMISSION_MESSAGE
            db.commit()
            continue
        except Exception:
            db.rollback()
            logger.exception("Pulizia del dominio %s interrotta; riprova al prossimo giro", row.domain)
            continue
        row.page_token = page.get("nextPageToken")
        if not row.page_token:
            row.status, row.completed_at = "done", now
        db.commit()
    return moved
```

- [ ] **Step 4: Eseguire e verificare che passino, poi suite**

Esegui: `cd backend && uv run pytest tests/test_email_cleanup.py -v` → `4 passed`
Esegui: `cd backend && uv run pytest -q` → tutto verde.

- [ ] **Step 5: Commit**

```bash
git add backend/app/email_cleanup.py backend/tests/test_email_cleanup.py
git commit -m "Aggiunge il cestino Gmail e il giro di pulizia dei domini bloccati"
```

---

## Task 4: Email future da domini bloccati — cestino prima dell'analisi, scope Google

**Files:**
- Modify: `backend/app/gmail_sync.py`
- Modify: `backend/app/google.py` (`SCOPES`)
- Test: `backend/tests/test_gmail_proposals.py`, `backend/tests/test_google.py`

**Interfaces:**
- Consumes: `is_blocked_sender` (Task 1), `trash_message`, `TrashNotPermitted`, `TRASH_PERMISSION_MESSAGE` (Task 3).
- Produces: `ingest_message(db, connection, message, analyze, timezone_name, now=None, blocked_domains: Sequence[str] = (), trash: Callable[[str], None] | None = None) -> int`; `sync_gmail(db, connection, service, analyze, timezone_name, now=None, blocked_domains: Sequence[str] = ()) -> int` (imposta `connection.last_error = TRASH_PERMISSION_MESSAGE` se un cestino ha dato 403, altrimenti `None`).

- [ ] **Step 1: Scrivere i test**

Aggiungi in fondo a `backend/tests/test_gmail_proposals.py`:

```python
from app.email_cleanup import TRASH_PERMISSION_MESSAGE, TrashNotPermitted


def _blocked_message(message_id, sender):
    return {"id": message_id, "threadId": "t", "snippet": "Offerte",
            "payload": {"headers": [{"name": "From", "value": sender}],
                        "body": {"data": base64.urlsafe_b64encode(b"Sconti").decode()}}}


def _connection(db, seed):
    user = db.scalar(select(User).where(User.login == "luca"))
    connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                  email="luca@gmail.com", refresh_token_encrypted="encrypted")
    db.add(connection)
    db.commit()
    return connection


def test_gmail_dominio_bloccato_va_nel_cestino_senza_analisi(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        calls, trashed = [], []
        message = _blocked_message("mail-news", "Promo <promo@offerte.newsletter.com>")
        assert ingest_message(db, connection, message, lambda text: calls.append(text) or {"actions": []},
                              "Europe/Rome", blocked_domains=["newsletter.com"], trash=trashed.append) == 0
        assert calls == [] and trashed == ["mail-news"]
        assert db.scalar(select(EmailProcessed)).message_id == "mail-news"


def test_gmail_dominio_bloccato_senza_permesso_non_blocca(db_factory, seed):
    def forbidden(message_id):
        raise TrashNotPermitted("403")

    with db_factory() as db:
        connection = _connection(db, seed)
        calls = []
        message = _blocked_message("mail-news", "promo@newsletter.com")
        assert ingest_message(db, connection, message, lambda text: calls.append(text) or {"actions": []},
                              "Europe/Rome", blocked_domains=["newsletter.com"], trash=forbidden) == 0
        assert calls == []
        assert db.scalar(select(EmailProcessed)).message_id == "mail-news"


def test_gmail_dominio_simile_non_bloccato_viene_analizzato(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        calls, trashed = [], []
        message = _blocked_message("mail-ok", "x@notnewsletter.com")
        ingest_message(db, connection, message, lambda text: calls.append(text) or {"actions": []},
                       "Europe/Rome", blocked_domains=["newsletter.com"], trash=trashed.append)
        assert len(calls) == 1 and trashed == []


def test_sync_gmail_segnala_permesso_mancante(db_factory, seed):
    class FakeService:
        def access_token(self, connection):
            return "access"

        class api:
            @staticmethod
            def get(url, token, params=None):
                if url.endswith("/messages"):
                    return {"messages": [{"id": "mail-news"}]}
                return _blocked_message("mail-news", "promo@newsletter.com")

            @staticmethod
            def post(url, token, body):
                request = httpx.Request("POST", url)
                raise httpx.HTTPStatusError("403", request=request, response=httpx.Response(403, request=request))

    with db_factory() as db:
        connection = _connection(db, seed)
        sync_gmail(db, connection, FakeService(), lambda text: {"actions": []}, "Europe/Rome",
                   blocked_domains=["newsletter.com"])
        assert connection.last_error == TRASH_PERMISSION_MESSAGE
        assert db.scalar(select(EmailProcessed)).message_id == "mail-news"
```

Aggiungi anche `import httpx` tra gli import in cima al file.

Aggiungi in fondo a `backend/tests/test_google.py`:

```python
def test_scope_gmail_consente_il_cestino_ma_non_la_sola_lettura():
    from app.google import SCOPES
    assert "https://www.googleapis.com/auth/gmail.modify" in SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" not in SCOPES
```

- [ ] **Step 2: Eseguire e verificare che falliscano**

Esegui: `cd backend && uv run pytest tests/test_gmail_proposals.py tests/test_google.py -k "bloccato or permesso or scope" -v`
Atteso: FAIL (`TypeError: ingest_message() got an unexpected keyword argument 'blocked_domains'`, scope assert).

- [ ] **Step 3: Scope in `backend/app/google.py`**

Sostituisci la riga `"https://www.googleapis.com/auth/gmail.readonly",` con:

```python
    "https://www.googleapis.com/auth/gmail.modify",
```

- [ ] **Step 4: Aggiornare `backend/app/gmail_sync.py`**

Import: sostituisci `from collections.abc import Callable` con `from collections.abc import Callable, Sequence` e aggiungi dopo gli import `from .hermes_client ...`:

```python
from .email_cleanup import TRASH_PERMISSION_MESSAGE, TrashNotPermitted, trash_message
from .email_domains import is_blocked_sender
```

Firma di `ingest_message`:

```python
def ingest_message(db: Session, connection: GoogleConnection, message: dict,
                   analyze: Callable[[str], dict], timezone_name: str, now: datetime | None = None,
                   blocked_domains: Sequence[str] = (), trash: Callable[[str], None] | None = None) -> int:
```

Subito dopo la riga `headers = {item.get("name", "").lower(): ...}` (prima di `sender = headers.get("from", "")[:320]`), inserisci:

```python
    if blocked_domains and is_blocked_sender(headers.get("from", ""), blocked_domains):
        # Dominio bloccato: nessuna analisi Hermes (nessun costo), l'email va nel cestino.
        if trash is not None:
            try:
                trash(message_id)
            except TrashNotPermitted:
                pass  # resta in casella; sync_gmail chiede di ricollegare Google
        db.add(EmailProcessed(connection_id=connection.id, message_id=message_id))
        db.commit()
        return 0
```

Sostituisci l'intera funzione `sync_gmail` con:

```python
def sync_gmail(db: Session, connection: GoogleConnection, service,
               analyze: Callable[[str], dict], timezone_name: str, now: datetime | None = None,
               blocked_domains: Sequence[str] = ()) -> int:
    """Scorre i messaggi che corrispondono ai filtri; riprende dalle pagine incomplete."""
    now = now or datetime.now(timezone.utc)
    since = connection.last_gmail_sync_at - timedelta(days=1) if connection.last_gmail_sync_at else now - timedelta(days=365)
    query = f"{connection.gmail_query} after:{since:%Y/%m/%d}".strip()
    params = {"q": query, "maxResults": 50}
    if connection.gmail_page_token:
        params["pageToken"] = connection.gmail_page_token
    token = service.access_token(connection)
    permission_missing = False

    def trash(message_id: str) -> None:
        nonlocal permission_missing
        try:
            trash_message(service, token, message_id)
        except TrashNotPermitted:
            permission_missing = True
            raise

    page = service.api.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", token, params)
    created = 0
    for item in page.get("messages", []):
        message = service.api.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}", token,
            {"format": "full"})
        created += ingest_message(db, connection, message, analyze, timezone_name, now,
                                  blocked_domains=blocked_domains, trash=trash)
    connection.gmail_page_token = page.get("nextPageToken")
    if not connection.gmail_page_token:
        connection.last_gmail_sync_at = now
    connection.last_error = TRASH_PERMISSION_MESSAGE if permission_missing else None
    db.commit()
    return created
```

- [ ] **Step 5: Eseguire e verificare che passino, poi suite**

Esegui: `cd backend && uv run pytest tests/test_gmail_proposals.py tests/test_google.py -v` → tutto passa.
Esegui: `cd backend && uv run pytest -q` → tutto verde.

- [ ] **Step 6: Commit**

```bash
git add backend/app/gmail_sync.py backend/app/google.py backend/tests/test_gmail_proposals.py backend/tests/test_google.py
git commit -m "Le email dei domini bloccati vanno nel cestino senza analisi; scope gmail.modify"
```

---

## Task 5: Collegare nel worker

**Files:**
- Modify: `backend/app/worker.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `sync_gmail(..., blocked_domains=...)` (Task 4), `run_domain_cleanups(db, service, now)` (Task 3).
- Produces: `run_google_once` passa `blocked_domains` letti da `household.settings["blocked_email_domains"]`; non sovrascrive `connection.last_error` impostato da `sync_gmail` quando non c'è errore Gmail; `main()` esegue `run_domain_cleanups` isolato.

- [ ] **Step 1: Aggiornare i fake esistenti e scrivere i test**

In `backend/tests/test_worker.py` cambia le due firme:

```python
    def fake_gmail(db, connection, service, analyze, timezone_name, now, blocked_domains=()):
```

```python
    def failing_gmail(db, connection, service, analyze, timezone_name, now, blocked_domains=()):
```

Aggiungi `Household` all'import esistente da `app.models`, poi in fondo al file:

```python
def test_google_worker_passa_i_domini_bloccati_e_conserva_l_avviso(db_factory, seed, monkeypatch):
    from app import worker

    seen = []

    def fake_gmail(db, connection, service, analyze, timezone_name, now, blocked_domains=()):
        seen.append(list(blocked_domains))
        connection.last_gmail_sync_at = now
        connection.last_error = "Ricollega Google"
        db.commit()

    monkeypatch.setattr(worker, "sync_gmail", fake_gmail)
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    with db_factory() as db:
        household = db.get(Household, seed["Rossi"])
        household.settings = {**(household.settings or {}), "blocked_email_domains": ["news.com"]}
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        run_google_once(db, object(), object(), now)
        assert seen == [["news.com"]]
        assert db.get(GoogleConnection, connection.id).last_error == "Ricollega Google"
```

- [ ] **Step 2: Eseguire e verificare che fallisca**

Esegui: `cd backend && uv run pytest tests/test_worker.py -v`
Atteso: il nuovo test FAIL (`seen == [[]]` oppure `last_error` sovrascritto a `None`).

- [ ] **Step 3: Aggiornare `backend/app/worker.py`**

Import: aggiungi `from .email_cleanup import run_domain_cleanups` (in ordine alfabetico, prima di `from .email_notices ...`).

In `run_google_once`, sostituisci:

```python
                categories = list((household.settings or {}).get("bill_categories", DEFAULT_BILL_CATEGORIES))
                sync_gmail(db, connection, service,
                           lambda text: hermes_email.analyze_email(
                               text, timezone_name, settings.hermes_email_model, categories),
                           timezone_name, now)
```

con:

```python
                categories = list((household.settings or {}).get("bill_categories", DEFAULT_BILL_CATEGORIES))
                blocked = list((household.settings or {}).get("blocked_email_domains", []))
                sync_gmail(db, connection, service,
                           lambda text: hermes_email.analyze_email(
                               text, timezone_name, settings.hermes_email_model, categories),
                           timezone_name, now, blocked_domains=blocked)
```

Sempre in `run_google_once`, sostituisci la riga:

```python
            connection.last_error = gmail_error
```

con:

```python
            if gmail_error:
                # Senza errore Gmail si lascia l'esito scritto da sync_gmail (es. «ricollega Google»).
                connection.last_error = gmail_error
```

In `main()`, dopo `dispatch_email_creation_notices(db, messenger.send, datetime.now(timezone.utc))`, aggiungi (stessa indentazione):

```python
                    try:
                        run_domain_cleanups(db, google, datetime.now(timezone.utc))
                    except Exception:
                        db.rollback()
                        logger.exception("Pulizia dei domini bloccati fallita; nuovo tentativo al prossimo giro")
```

- [ ] **Step 4: Eseguire e verificare che passino, poi suite**

Esegui: `cd backend && uv run pytest tests/test_worker.py -v` → tutto passa.
Esegui: `cd backend && uv run pytest -q` → tutto verde.

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker.py backend/tests/test_worker.py
git commit -m "Collega i domini bloccati e la pulizia retroattiva nel worker"
```

---

## Task 6: Frontend — sezione "Email da ignorare"

**Files:**
- Modify: `frontend/js/views/impostazioni.js`
- Modify: `frontend/sw.js`

**Interfaces:**
- Consumes: `state.household.blocked_email_domains` (Task 1), `GET /api/v1/household/email-cleanups` (Task 2), `updateHousehold` (esistente in `store.js`).

- [ ] **Step 1: Sezione nel `render()`**

In `frontend/js/views/impostazioni.js`, subito dopo la `</section>` che chiude la sezione `Categorie dei costi` (quella con `<form id="bill-categories">`) e prima della sezione `I vostri dati`, inserisci:

```javascript
    <section class="module">
      ${sectionHead('Email da ignorare')}
      <p>Le email da questi domini finiscono nel cestino di Gmail (recuperabili per 30 giorni) senza essere analizzate. Aggiungendo un dominio si spostano nel cestino anche quelle già in casella.</p>
      <form id="blocked-domains">
        <div class="checks">${(state.household?.blocked_email_domains || []).map((d) => html`<label class="setting-check"><input type="checkbox" name="domain" value="${d}" checked>${d}</label>`)}</div>
        <div class="quick-add">
          <label class="grow"><span>Aggiungi un dominio</span><input name="custom" maxlength="253" placeholder="Es. newsletter.com"></label>
          <button type="submit" class="primary">Salva i domini</button>
        </div>
      </form>
      <div id="email-cleanups" aria-live="polite"></div>
    </section>
```

- [ ] **Step 2: Gestori nel `mount(root)`**

Subito dopo la riga `loadConflicts(root).catch((err) => { $('#calendar-conflicts', root).textContent = err.message; });`, aggiungi:

```javascript
  loadCleanups(root).catch((err) => { $('#email-cleanups', root).textContent = err.message; });
```

Subito dopo il blocco `$('#bill-categories', root).addEventListener('submit', ...)` (che termina con `});`), aggiungi:

```javascript
  $('#blocked-domains', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const blocked_email_domains = $$('[name=domain]:checked', form).map((i) => i.value);
    const custom = form.elements.custom.value.trim();
    if (custom) blocked_email_domains.push(custom);
    try {
      await updateHousehold({ blocked_email_domains });
      toast('Domini salvati.');
    } catch (err) { toast(err.message); }
  });
```

- [ ] **Step 3: Funzione di stato**

Subito prima di `async function loadConflicts(root) {`, aggiungi:

```javascript
const CLEANUP_LABELS = { running: 'in corso', done: 'completata' };

async function loadCleanups(root) {
  const box = $('#email-cleanups', root);
  if (!box) return;
  const cleanups = await api('GET', '/household/email-cleanups');
  box.innerHTML = cleanups.length ? String(html`<ul>${cleanups.map((c) => html`<li>${c.domain}: pulizia ${CLEANUP_LABELS[c.status] || c.status}, ${c.trashed_count} email nel cestino</li>`)}</ul>`) : '';
}
```

- [ ] **Step 4: Versione del service worker**

In `frontend/sw.js` cambia `const VERSION = '5';` in `const VERSION = '6';`.

- [ ] **Step 5: Verifica sintattica**

Esegui (PowerShell, dalla root): `Get-ChildItem frontend -Recurse -Filter *.js | % { node --check $_.FullName }`
Atteso: nessun output.

- [ ] **Step 6: Commit**

Solo questi due file (nella cartella ci sono altre modifiche frontend non legate a questo lavoro: non includerle).

```bash
git add frontend/js/views/impostazioni.js frontend/sw.js
git commit -m "Impostazioni: sezione Email da ignorare con stato della pulizia"
```

---

## Task 7: Rilascio sul NAS e nuovo permesso Google (operativo, eseguito dal controller)

**Files:** nessuno.

- [ ] **Step 1: Google Cloud Console**: nella schermata di consenso OAuth (Accesso ai dati) aggiungere lo scope `https://www.googleapis.com/auth/gmail.modify` (l'app resta in modalità test, Luca è già utente di test).
- [ ] **Step 2: Deploy**: pacchetto, upload, `compose build api`, `compose -f compose.yaml -f compose.hermes.yaml --profile integrations up -d`; verificare `alembic current` = `20260926_01 (head)` e health 200.
- [ ] **Step 3:** Luca usa "Ricollega Google (aggiorna i permessi)" in Impostazioni — NON Scollega; e ricollegare PRIMA di bloccare domini.
- [ ] **Step 4: Verifica**: `GET /household` contiene `blocked_email_domains`; aggiungere un dominio di prova indicato da Luca e controllare che `GET /household/email-cleanups` mostri la pulizia avanzare e che `last_error` non contenga l'avviso di permesso.

---

## Self-Review

- **Copertura spec:** §1 → Task 4, 3, 5; §2 permesso → Task 4 (scope), 3/4 (403), 7; §3 dati → Task 1, 2; §4 corrispondenza → Task 1; §5 email future → Task 4; §6 pulizia → Task 2, 3, 5; §7 API/frontend → Task 1, 2, 6; §8 test → in ogni task; §9 fuori scopo → nessun task lo tocca.
- **Coerenza firme:** `sync_gmail(..., timezone_name, now=None, blocked_domains=())` coerente tra Task 4 e i fake del Task 5; `run_domain_cleanups(db, service, now)` coerente tra Task 3 e 5; `queue_domain_cleanups(db, household_id, previous, current)` definita nel Task 2 e mantenuta identica nel file riscritto al Task 3.
- **Nota:** la sovrascrittura di `last_error` nel worker cambia leggermente il comportamento: se in un giro Gmail non viene eseguito (meno di 10 minuti) e Calendar va bene, un errore precedente resta visibile fino alla prossima sincronizzazione Gmail. Accettato: serve a non cancellare l'avviso «ricollega Google».
