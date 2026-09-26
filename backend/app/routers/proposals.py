"""Revisione umana delle informazioni estratte dalle email."""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..crud import audit, check_version, commit, get_owned
from ..db import get_db
from ..errors import ApiError
from ..models import Event, Proposal, utcnow
from ..schemas import ActionBatchIn, AssistantAction, EntityOut
from ..security import Ctx, current
from .assistant import create_actions

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ProposalOut(EntityOut):
    sender: str | None
    subject: str | None
    snippet: str | None
    message_id: str
    kind: str
    data: dict
    status: str
    target_id: str | None


class ReviewIn(BaseModel):
    decision: Literal["accept", "reject"]


class RejectStaleIn(BaseModel):
    days: int = Field(default=30, ge=7)


STALE_DAYS = 30


def _pending(ctx: Ctx):
    return (Proposal.household_id == ctx.household_id, Proposal.deleted_at.is_(None),
            Proposal.status == "pending")


@router.get("", response_model=list[ProposalOut])
def list_proposals(status: Literal["pending", "accepted", "rejected"] | None = None,
                   ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    query = select(Proposal).where(Proposal.household_id == ctx.household_id, Proposal.deleted_at.is_(None))
    if status:
        query = query.where(Proposal.status == status)
    return db.scalars(query.order_by(Proposal.created_at.desc()).limit(200)).all()


@router.get("/summary")
def summary(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Quante proposte aspettano una decisione e quante sono ferme da più di 30 giorni."""
    cutoff = utcnow() - timedelta(days=STALE_DAYS)
    pending = db.scalar(select(func.count()).select_from(Proposal).where(*_pending(ctx)))
    stale = db.scalar(select(func.count()).select_from(Proposal).where(*_pending(ctx),
                                                                       Proposal.created_at < cutoff))
    return {"pending": pending, "stale": stale}


@router.post("/reject-stale")
def reject_stale(data: RejectStaleIn, ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    """Ignora in blocco le proposte in attesa più vecchie di `days` giorni (arretrati)."""
    cutoff = utcnow() - timedelta(days=data.days)
    stale = db.scalars(select(Proposal).where(*_pending(ctx), Proposal.created_at < cutoff)).all()
    for proposal in stale:
        proposal.status = "rejected"
        audit(db, ctx, "review", proposal, {"status": "rejected", "bulk": True})
    commit(db)
    return {"rejected": len(stale)}


@router.post("/{proposal_id}/review", response_model=ProposalOut)
def review(proposal_id: str, data: ReviewIn, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
           if_match: str | None = Header(None)):
    proposal = get_owned(db, Proposal, ctx, proposal_id)
    check_version(proposal, if_match)
    if proposal.status != "pending":
        if proposal.status == ("accepted" if data.decision == "accept" else "rejected"):
            return proposal
        raise ApiError(409, "already_reviewed", "Questa proposta è già stata verificata.")
    if data.decision == "accept":
        batch = ActionBatchIn(actions=[AssistantAction(kind=proposal.kind, data=proposal.data)])
        created = create_actions(db, ctx, batch).created[0]
        proposal.target_id = created.id
        proposal.status = "accepted"
        if proposal.kind == "event":
            db.get(Event, created.id).source = "gmail"
    else:
        proposal.status = "rejected"
    audit(db, ctx, "review", proposal, {"status": proposal.status, "target_id": proposal.target_id})
    commit(db)
    return proposal
