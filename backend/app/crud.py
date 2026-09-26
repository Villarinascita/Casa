"""Operazioni comuni sugli oggetti della famiglia e fabbrica dei router CRUD."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from . import habits
from .db import get_db
from .errors import ApiError, validation_error
from .models import AuditEntry, IdempotencyRecord, Member, utcnow
from .security import Ctx, current

CONFLICT_MESSAGE = "L'elemento è stato modificato su un altro dispositivo. Ricarica e riprova."


def get_owned(db: Session, model: type, ctx: Ctx, entity_id: str, *, include_deleted: bool = False):
    obj = db.get(model, entity_id)
    if obj is None or obj.household_id != ctx.household_id or (obj.deleted_at is not None and not include_deleted):
        raise ApiError(404, "not_found", "Elemento non trovato.")
    return obj


def check_version(obj, if_match: str | None) -> None:
    if if_match is None:
        raise ApiError(428, "version_required", "Manca la versione dell'elemento (If-Match).")
    try:
        expected = int(if_match.strip().removeprefix("W/").strip('"'))
    except ValueError:
        raise ApiError(400, "invalid_version", "Versione non valida.") from None
    if expected != obj.version:
        raise ApiError(409, "version_conflict", CONFLICT_MESSAGE)


def ensure_member(db: Session, ctx: Ctx, member_id: str | None) -> None:
    """Impedisce riferimenti a familiari di un'altra famiglia o eliminati."""
    if member_id is None:
        return
    member = db.get(Member, member_id)
    if member is None or member.household_id != ctx.household_id or member.deleted_at is not None:
        raise ApiError(422, "validation_error", "Familiare non valido.", {"member_id": "Familiare non valido."})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def audit(db: Session, ctx: Ctx, action: str, obj, changed: dict[str, Any] | None = None) -> None:
    db.add(AuditEntry(household_id=ctx.household_id, actor_id=ctx.user_id, action=action,
                      entity_type=obj.__tablename__, entity_id=obj.id,
                      changed_fields={k: _jsonable(v) for k, v in (changed or {}).items()}))


def commit(db: Session) -> None:
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise ApiError(409, "version_conflict", CONFLICT_MESSAGE) from None
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "integrity_error", "Dati in conflitto con quelli già salvati.") from None


def revalidate(schema: type[BaseModel], obj, changes: dict[str, Any]) -> BaseModel:
    """Applica una modifica parziale all'oggetto e rivalida lo stato completo risultante."""
    current_values = {name: getattr(obj, name) for name in schema.model_fields}
    try:
        return schema.model_validate({**current_values, **changes})
    except ValidationError as exc:
        raise validation_error(exc) from None


def assign(obj, values: dict[str, Any]) -> dict[str, Any]:
    changed = {}
    for name, value in values.items():
        if getattr(obj, name) != value:
            setattr(obj, name, value)
            changed[name] = value
    return changed


def idempotent_create(db: Session, ctx: Ctx, request: Request, key: str | None,
                      produce: Callable[[], Any], out: type[BaseModel]) -> JSONResponse:
    """Crea l'oggetto una sola volta per Idempotency-Key; i tentativi successivi ricevono la stessa risposta."""
    scope = f"{request.method} {request.url.path}"
    if key:
        if len(key) > 120:
            raise ApiError(400, "invalid_idempotency_key", "Idempotency-Key troppo lunga.")
        previous = _stored_response(db, ctx, key, scope)
        if previous:
            return previous
    body = out.model_validate(produce()).model_dump(mode="json")
    if key:
        db.add(IdempotencyRecord(user_id=ctx.user_id, key=key, scope=scope, status_code=201, response_body=body))
    try:
        commit(db)
    except ApiError:
        # Due tentativi concorrenti con la stessa chiave: vince il primo, il secondo ne riceve la risposta.
        previous = key and _stored_response(db, ctx, key, scope)
        if previous:
            return previous
        raise
    return JSONResponse(body, status_code=201)


def _stored_response(db: Session, ctx: Ctx, key: str, scope: str) -> JSONResponse | None:
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.user_id == ctx.user_id,
                                                       IdempotencyRecord.key == key))
    if record is None:
        return None
    if record.scope != scope:
        raise ApiError(422, "idempotency_key_reused", "Idempotency-Key già usata per un'altra operazione.")
    return JSONResponse(record.response_body, status_code=record.status_code)


@dataclass
class Resource:
    """Descrive una risorsa CRUD: modello, schemi e regole specifiche."""

    model: type
    create_schema: type[BaseModel]
    patch_schema: type[BaseModel]
    out_schema: type[BaseModel]
    # Campi della patch che non sono colonne dirette (es. "checked", "status", "archived").
    extra_fields: tuple[str, ...] = ()
    apply_extras: Callable[[Any, dict[str, Any], Ctx], dict[str, Any]] = lambda obj, extras, ctx: {}
    order_by: tuple = ()
    references_member: bool = True


def build_router(prefix: str, res: Resource, *, custom_list: bool = False) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[prefix.strip("/")])
    Out = res.out_schema
    Create = res.create_schema
    Patch = res.patch_schema

    if not custom_list:
        @router.get("", response_model=list[Out])
        def list_items(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
            query = select(res.model).where(res.model.household_id == ctx.household_id,
                                            res.model.deleted_at.is_(None))
            return db.scalars(query.order_by(*res.order_by, res.model.created_at)).all()

    @router.post("", response_model=Out, status_code=201)
    def create_item(data: Create, request: Request, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                    idempotency_key: str | None = Header(None)):
        def produce():
            values = data.model_dump()
            if res.references_member:
                ensure_member(db, ctx, values.get("member_id"))
            obj = res.model(household_id=ctx.household_id, created_by=ctx.user_id, **values)
            db.add(obj)
            db.flush()
            audit(db, ctx, "create", obj, values)
            return obj
        return idempotent_create(db, ctx, request, idempotency_key, produce, Out)

    @router.get("/{item_id}", response_model=Out)
    def get_item(item_id: str, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
        return get_owned(db, res.model, ctx, item_id)

    @router.patch("/{item_id}", response_model=Out)
    def update_item(item_id: str, data: Patch, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                    if_match: str | None = Header(None)):
        obj = get_owned(db, res.model, ctx, item_id)
        check_version(obj, if_match)
        changes = data.model_dump(exclude_unset=True)
        extras = {name: changes.pop(name) for name in res.extra_fields if name in changes}
        merged = revalidate(Create, obj, changes).model_dump()
        if res.references_member and "member_id" in changes:
            ensure_member(db, ctx, merged.get("member_id"))
        changed = assign(obj, merged)
        changed |= res.apply_extras(obj, extras, ctx)
        if changed:
            audit(db, ctx, "update", obj, changed)
            commit(db)
        return obj

    @router.delete("/{item_id}", response_model=Out)
    def delete_item(item_id: str, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                    if_match: str | None = Header(None)):
        """Eliminazione soft: l'elemento resta recuperabile con /restore (tasto «Annulla»)."""
        obj = get_owned(db, res.model, ctx, item_id)
        check_version(obj, if_match)
        obj.deleted_at = utcnow()
        audit(db, ctx, "delete", obj)
        habits.on_delete(db, obj)
        commit(db)
        return obj

    @router.post("/{item_id}/restore", response_model=Out)
    def restore_item(item_id: str, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                     if_match: str | None = Header(None)):
        obj = get_owned(db, res.model, ctx, item_id, include_deleted=True)
        check_version(obj, if_match)
        if obj.deleted_at is not None:
            obj.deleted_at = None
            audit(db, ctx, "restore", obj)
            habits.on_restore(db, obj)
            commit(db)
        return obj

    return router
