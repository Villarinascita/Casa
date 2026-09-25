from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field, field_validator, model_validator

Text = lambda n: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=n)]  # noqa: E731
OptText = lambda n: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=n)]  # noqa: E731


def _blank_to_none(value):
    return None if isinstance(value, str) and not value.strip() else value


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EntityOut(OutSchema):
    id: str
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


# --- Autenticazione e famiglia ---------------------------------------------------------------


class LoginIn(Schema):
    login: Text(80)
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


DEFAULT_BILL_CATEGORIES = ["Bollette", "Auto e assicurazione", "Altro"]


class HouseholdOut(OutSchema):
    id: str
    name: str
    timezone: str
    version: int
    areas: list[str]
    bill_categories: list[str]


class HouseholdPatch(Schema):
    name: Text(120) | None = None
    areas: list[Text(60)] | None = Field(default=None, max_length=30)
    bill_categories: list[Text(60)] | None = Field(default=None, max_length=30)

    @field_validator("areas", "bill_categories")
    @classmethod
    def _unique_list(cls, value):
        return None if value is None else list(dict.fromkeys(value))


class MeOut(BaseModel):
    user_id: str
    login: str
    role: str
    household: HouseholdOut


# --- Familiari -------------------------------------------------------------------------------


class MemberIn(Schema):
    display_name: Text(80)
    relation: OptText(80) = None
    sort_order: int = 0

    _blank = field_validator("relation", mode="before")(_blank_to_none)


class MemberPatch(Schema):
    display_name: Text(80) | None = None
    relation: OptText(80) = None
    sort_order: int | None = None
    archived: bool | None = None


class MemberOut(EntityOut):
    display_name: str
    relation: str | None
    user_id: str | None
    sort_order: int
    archived: bool


# --- Appuntamenti ----------------------------------------------------------------------------


class EventIn(Schema):
    title: Text(180)
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: OptText(300) = None
    notes: OptText(2000) = None
    member_id: str | None = None

    _blank = field_validator("location", "notes", "member_id", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _coherent_times(self):
        if self.all_day:
            # Evento per tutto il giorno: solo date, nessuna conversione in mezzanotte UTC.
            self.start_at = self.end_at = None
            if self.start_date is None:
                raise ValueError("Indica la data dell'appuntamento.")
            if self.end_date is not None and self.end_date < self.start_date:
                raise ValueError("La data di fine precede quella di inizio.")
        else:
            self.start_date = self.end_date = None
            if self.start_at is None:
                raise ValueError("Indica data e ora di inizio.")
            for value in (self.start_at, self.end_at):
                if value is not None and value.tzinfo is None:
                    raise ValueError("Gli orari devono includere il fuso orario.")
            self.start_at = self.start_at.astimezone(timezone.utc)
            self.end_at = self.end_at and self.end_at.astimezone(timezone.utc)
            if self.end_at is not None and self.end_at < self.start_at:
                raise ValueError("L'ora di fine precede quella di inizio.")
        return self


class EventPatch(Schema):
    title: Text(180) | None = None
    all_day: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: OptText(300) = None
    notes: OptText(2000) = None
    member_id: str | None = None


class EventOut(EntityOut):
    title: str
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None
    location: str | None
    notes: str | None
    member_id: str | None
    source: str


# --- Attività --------------------------------------------------------------------------------


class TaskIn(Schema):
    title: Text(180)
    notes: OptText(2000) = None
    due_date: date | None = None
    remind_at: datetime | None = None
    repeat: Literal["daily", "weekly", "monthly"] | None = None
    member_id: str | None = None

    _blank = field_validator("notes", "member_id", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _valid_reminder(self):
        if self.repeat and self.remind_at is None:
            raise ValueError("Indica quando ricordare l'attività ricorrente.")
        if self.remind_at is not None:
            if self.remind_at.tzinfo is None:
                raise ValueError("L'ora del promemoria deve includere il fuso orario.")
            self.remind_at = self.remind_at.astimezone(timezone.utc)
        return self


class TaskPatch(Schema):
    title: Text(180) | None = None
    notes: OptText(2000) = None
    due_date: date | None = None
    remind_at: datetime | None = None
    repeat: Literal["daily", "weekly", "monthly"] | None = None
    member_id: str | None = None
    status: Literal["open", "done"] | None = None


class TaskOut(EntityOut):
    title: str
    notes: str | None
    due_date: date | None
    remind_at: datetime | None
    repeat: str | None
    member_id: str | None
    status: str
    completed_at: datetime | None


# --- Spesa -----------------------------------------------------------------------------------


class ShoppingIn(Schema):
    label: Text(120)
    quantity: OptText(40) = None
    category: OptText(60) = None

    _blank = field_validator("quantity", "category", mode="before")(_blank_to_none)


class ShoppingPatch(Schema):
    label: Text(120) | None = None
    quantity: OptText(40) = None
    category: OptText(60) = None
    checked: bool | None = None


class ShoppingOut(EntityOut):
    label: str
    quantity: str | None
    category: str | None
    checked_at: datetime | None

    @computed_field
    @property
    def checked(self) -> bool:
        return self.checked_at is not None


# --- Bollette e costi di casa ----------------------------------------------------------------


class BillIn(Schema):
    category: Text(60)
    title: Text(180)
    supplier: OptText(180) = None
    amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    due_date: date | None = None

    _blank = field_validator("supplier", mode="before")(_blank_to_none)


class BillPatch(Schema):
    category: Text(60) | None = None
    title: Text(180) | None = None
    supplier: OptText(180) = None
    amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    due_date: date | None = None
    payment_state: Literal["da_pagare", "addebito_previsto", "pagato"] | None = None


class BillOut(EntityOut):
    category: str
    title: str
    supplier: str | None
    amount: Decimal | None
    currency: str
    due_date: date | None
    payment_state: str
    source_sender: str | None
    source_subject: str | None


# --- Importazione dal prototipo locale -------------------------------------------------------


class LegacyItem(BaseModel):
    type: Literal["event", "task", "shopping"]
    title: str
    date: str | None = None
    time: str | None = None
    person: str | None = None
    note: str | None = None
    done: bool = False


class LegacyImportIn(BaseModel):
    members: list[str] = Field(default_factory=list, max_length=100)
    items: list[LegacyItem] = Field(default_factory=list, max_length=5000)
    areas: list[str] = Field(default_factory=list, max_length=30)


class LegacyImportOut(BaseModel):
    members_created: int
    events: int
    tasks: int
    shopping: int
    skipped: list[str]


class AssistantAction(Schema):
    kind: Literal["event", "task", "shopping"]
    data: dict[str, Any]


class ActionBatchIn(Schema):
    actions: list[AssistantAction] = Field(min_length=1, max_length=20)


class CreatedAction(OutSchema):
    kind: str
    id: str


class ActionBatchOut(OutSchema):
    created: list[CreatedAction]
