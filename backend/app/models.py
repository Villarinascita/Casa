"""Modello dati: sottoinsieme della specifica (docs/SPECIFICA_COMPLETA.md §8) per il primo rilascio."""

import uuid
from datetime import date, datetime, timezone
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
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
    status: Mapped[str] = mapped_column(String(10), default="open")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="ck_tasks_status"),
        Index("ix_tasks_household_status_due", "household_id", "status", "due_date"),
    )


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
