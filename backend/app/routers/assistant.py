"""Azioni strutturate prodotte dall'assistente, sempre validate dal backend."""

from fastapi import APIRouter, Depends, Header, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..crud import audit, ensure_member, idempotent_create
from ..db import get_db
from ..errors import validation_error
from ..models import Event, ShoppingItem, Task
from ..schemas import (ActionBatchIn, ActionBatchOut, CreatedAction, EventIn, ShoppingIn, TaskIn)
from ..security import Ctx, current

router = APIRouter(prefix="/assistant", tags=["assistant"])

ACTION_TYPES = {
    "event": (EventIn, Event),
    "task": (TaskIn, Task),
    "shopping": (ShoppingIn, ShoppingItem),
}


def create_actions(db: Session, ctx: Ctx, batch: ActionBatchIn) -> ActionBatchOut:
    validated = []
    for action in batch.actions:
        schema, model = ACTION_TYPES[action.kind]
        try:
            data = schema.model_validate(action.data).model_dump()
        except ValidationError as exc:
            raise validation_error(exc) from None
        if model is not ShoppingItem:
            ensure_member(db, ctx, data.get("member_id"))
        validated.append((action.kind, model, data))

    created = []
    for kind, model, data in validated:
        if model is Event:
            data["source"] = "assistant"
        obj = model(household_id=ctx.household_id, created_by=ctx.user_id, **data)
        db.add(obj)
        db.flush()
        audit(db, ctx, "create", obj, data)
        created.append(CreatedAction(kind=kind, id=obj.id))
    return ActionBatchOut(created=created)


@router.post("/actions", response_model=ActionBatchOut, status_code=201)
def post_actions(batch: ActionBatchIn, request: Request, ctx: Ctx = Depends(current),
                 db: Session = Depends(get_db), idempotency_key: str | None = Header(None)):
    return idempotent_create(db, ctx, request, idempotency_key,
                             lambda: create_actions(db, ctx, batch), ActionBatchOut)
