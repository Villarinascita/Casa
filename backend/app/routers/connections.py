"""Collegamento verificato degli account di messaggistica."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ChannelLink, TelegramLinkCode, utcnow
from ..security import Ctx, current

router = APIRouter(prefix="/connections", tags=["connections"])


@router.post("/telegram/start")
def start_telegram(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    code = secrets.token_urlsafe(12)
    db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.user_id == ctx.user_id))
    db.add(TelegramLinkCode(code_hash=hashlib.sha256(code.encode()).hexdigest(),
                            household_id=ctx.household_id, user_id=ctx.user_id,
                            expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    return {"code": code, "expires_in_seconds": 600}


@router.get("/telegram")
def telegram_status(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    link = db.scalar(select(ChannelLink).where(ChannelLink.user_id == ctx.user_id,
                                               ChannelLink.platform == "telegram"))
    return {"connected": link is not None}


@router.delete("/telegram", status_code=204)
def disconnect_telegram(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    db.execute(delete(ChannelLink).where(ChannelLink.user_id == ctx.user_id,
                                         ChannelLink.platform == "telegram"))
    db.commit()
