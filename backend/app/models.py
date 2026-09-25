"""Modello dati: sottoinsieme della specifica (docs/SPECIFICA_COMPLETA.md §8) per il primo rilascio."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Istanti sempre in UTC: SQLite non conserva il fuso, quindi si salva UTC e si rilegge come UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Istante senza fuso orario")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Rome")
    locale: Mapped[str] = mapped_column(String(16), default="it-IT")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}

    @property
    def bill_categories(self) -> list[str]:
        """Legge le categorie di bollette da settings con valore predefinito."""
        return list(self.settings.get("bill_categories", ["Bollette", "Auto e assicurazione", "Altro"]))


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    login: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class HouseholdUser(Base):
    __tablename__ = "household_users"

    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="adult")

    __table_args__ = (CheckConstraint("role IN ('admin', 'adult')", name="ck_household_users_role"),)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class HouseholdEntity:
    """Campi comuni a ogni oggetto della famiglia: appartenenza, autore, date, versione, eliminazione soft."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        # Ogni flush incrementa version e fallisce se nel frattempo un'altra richiesta l'ha cambiata.
        return {"version_id_col": cls.__table__.c.version}


class Member(HouseholdEntity, Base):
    __tablename__ = "members"

    display_name: Mapped[str] = mapped_column(String(80))
    relation: Mapped[str | None] = mapped_column(String(80))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Event(HouseholdEntity, Base):
    __tablename__ = "events"

    title: Mapped[str] = mapped_column(String(180))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
    source: Mapped[str] = mapped_column(String(40), default="manual")

    __table_args__ = (
        CheckConstraint(
            "(all_day AND start_date IS NOT NULL AND start_at IS NULL AND end_at IS NULL)"
            " OR (NOT all_day AND start_at IS NOT NULL AND start_date IS NULL AND end_date IS NULL)",
            name="ck_events_kind",
        ),
        CheckConstraint("end_at IS NULL OR end_at >= start_at", name="ck_events_end_at"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_events_end_date"),
        Index("ix_events_household_start_at", "household_id", "start_at"),
        Index("ix_events_household_start_date", "household_id", "start_date"),
    )


class Task(HouseholdEntity, Base):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    remind_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    repeat: Mapped[str | None] = mapped_column(String(10))
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
    status: Mapped[str] = mapped_column(String(10), default="open")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="ck_tasks_status"),
        CheckConstraint("repeat IS NULL OR repeat IN ('daily', 'weekly', 'monthly')", name="ck_tasks_repeat"),
        CheckConstraint("repeat IS NULL OR remind_at IS NOT NULL", name="ck_tasks_repeat_time"),
        Index("ix_tasks_household_status_due", "household_id", "status", "due_date"),
    )


class Bill(HouseholdEntity, Base):
    """Bolletta o costo di casa: creata subito dall'estrazione email, mai marcata pagata
    in automatico. Vedi docs/superpowers/specs/2026-09-25-bollette-costi-casa-design.md."""

    __tablename__ = "bills"

    category: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(180))
    supplier: Mapped[str | None] = mapped_column(String(180))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    due_date: Mapped[date | None] = mapped_column(Date)
    payment_state: Mapped[str] = mapped_column(String(20), default="da_pagare")
    source_sender: Mapped[str | None] = mapped_column(String(320))
    source_subject: Mapped[str | None] = mapped_column(String(500))
    found_reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    due_reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint("payment_state IN ('da_pagare', 'addebito_previsto', 'pagato')",
                        name="ck_bills_payment_state"),
        Index("ix_bills_household_payment_due", "household_id", "payment_state", "due_date"),
    )


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recipient_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (UniqueConstraint("task_id", "scheduled_at", name="uq_reminder_task_occurrence"),)


class ChannelLink(Base):
    __tablename__ = "channel_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    external_user_id: Mapped[str] = mapped_column(String(100))
    chat_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("platform", "external_user_id", name="uq_channel_external_user"),
        UniqueConstraint("user_id", "platform", name="uq_user_channel"),
    )


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"

    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    response: Mapped[str] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TelegramPending(Base):
    __tablename__ = "telegram_pending"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    original_text: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(String(1000))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class WorkerCursor(Base):
    __tablename__ = "worker_cursors"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class GoogleOAuthState(Base):
    __tablename__ = "google_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class GoogleConnection(Base):
    __tablename__ = "google_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    gmail_query: Mapped[str] = mapped_column(String(500), default="in:inbox")
    gmail_history_id: Mapped[str | None] = mapped_column(String(100))
    gmail_page_token: Mapped[str | None] = mapped_column(String(500))
    last_gmail_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GoogleCalendar(Base):
    __tablename__ = "google_calendars"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("google_connections.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(250))
    mode: Mapped[str] = mapped_column(String(10), default="full")
    outbound_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_token: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_google_calendar_connection_external"),
        CheckConstraint("mode IN ('full', 'busy')", name="ck_google_calendars_mode"),
    )


class EmailProcessed(Base):
    __tablename__ = "email_processed"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("google_connections.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("connection_id", "message_id", name="uq_email_processed_message"),)


class Proposal(HouseholdEntity, Base):
    __tablename__ = "proposals"

    connection_id: Mapped[str] = mapped_column(ForeignKey("google_connections.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(100))
    thread_id: Mapped[str] = mapped_column(String(100))
    item_index: Mapped[int] = mapped_column(Integer)
    sender: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    target_id: Mapped[str | None] = mapped_column(String(36))

    __table_args__ = (UniqueConstraint("connection_id", "message_id", "item_index", name="uq_proposal_email_item"),)


class EmailCreationNotice(Base):
    """Coda della notifica di controllo inviata dopo aver creato direttamente un
    appuntamento o un'attività da un'email (mai prima che il salvataggio sia confermato)."""

    __tablename__ = "email_creation_notices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(10))
    entity_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(String(500))
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        CheckConstraint("entity_type IN ('event', 'task')", name="ck_email_creation_notices_entity_type"),
    )


class CalendarEventLink(Base):
    __tablename__ = "calendar_event_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    calendar_id: Mapped[str] = mapped_column(ForeignKey("google_calendars.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True)
    external_id: Mapped[str] = mapped_column(String(500))
    etag: Mapped[str | None] = mapped_column(String(200))
    local_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="synced")
    remote_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_synced_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("calendar_id", "external_id", name="uq_calendar_external_event"),)


class ShoppingItem(HouseholdEntity, Base):
    __tablename__ = "shopping_items"

    label: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(60))
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    checked_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    changed_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class IdempotencyRecord(Base):
    """Risposta memorizzata per una Idempotency-Key: un nuovo tentativo non duplica la creazione."""

    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(200))
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)
