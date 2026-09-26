"""Elaborazione di aggiornamenti Telegram con identità ricavata dal canale."""

import hashlib
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .email_promotions import keep_command, keep_sender
from .models import ChannelLink, HouseholdUser, TelegramLinkCode, TelegramPending, TelegramUpdate, User, utcnow
from .routers.assistant import create_actions
from .schemas import ActionBatchIn
from .security import Ctx


def process_update(db: Session, update: dict[str, Any],
                   interpret: Callable[[str, Ctx], dict[str, Any]]) -> str:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if chat.get("type") != "private" or not sender.get("id") or chat.get("id") != sender.get("id"):
        return "Usa la chat privata del bot."
    text = (message.get("text") or "").strip()
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return "Messaggio non valido."
    previous = db.get(TelegramUpdate, update_id)
    if previous:
        return previous.response

    sender_id = str(sender["id"])
    if text.startswith("/link "):
        code = text[6:].strip()
        row = db.get(TelegramLinkCode, hashlib.sha256(code.encode()).hexdigest())
        if row is None or row.expires_at <= utcnow():
            return "Codice scaduto o non valido. Generane uno nuovo in Impostazioni."
        existing = db.scalar(select(ChannelLink).where(ChannelLink.platform == "telegram",
                                                      ChannelLink.external_user_id == sender_id))
        if existing and existing.user_id != row.user_id:
            return "Questo account Telegram è già collegato a un altro utente."
        user_link = db.scalar(select(ChannelLink).where(ChannelLink.platform == "telegram",
                                                       ChannelLink.user_id == row.user_id))
        if user_link and user_link is not existing:
            db.delete(user_link)
            db.flush()
        if existing is None:
            db.add(ChannelLink(household_id=row.household_id, user_id=row.user_id,
                               platform="telegram", external_user_id=sender_id, chat_id=sender_id))
        db.delete(row)
        reply = "Account Telegram collegato al gestionale."
    else:
        link = db.scalar(select(ChannelLink).where(ChannelLink.platform == "telegram",
                                                   ChannelLink.external_user_id == sender_id))
        if link is None:
            return "Collega Telegram dalle Impostazioni del gestionale e invia /link seguito dal codice."
        user = db.get(User, link.user_id)
        membership = db.get(HouseholdUser, (link.household_id, link.user_id))
        if user is None or user.disabled or membership is None:
            return "Account del gestionale non disponibile."
        if not text:
            return "Invia un messaggio di testo o vocale."
        ctx = Ctx(user_id=user.id, login=user.login, household_id=link.household_id, role=membership.role)
        pending = db.get(TelegramPending, user.id)
        if pending and pending.expires_at <= utcnow():
            db.delete(pending)
            pending = None
        kept = keep_command(db, link.household_id, text)
        if kept is not None:
            reply = keep_sender(db, link.household_id, kept)
            db.add(TelegramUpdate(update_id=update_id, response=reply))
            db.commit()
            return reply
        if text == "/cancel" and pending:
            db.delete(pending)
            reply = "Richiesta annullata."
            db.add(TelegramUpdate(update_id=update_id, response=reply))
            db.commit()
            return reply
        request_text = (f"Richiesta originale: {pending.original_text}\n"
                        f"Domanda: {pending.question}\nRisposta: {text}" if pending else text)
        result = interpret(request_text, ctx)
        if result.get("clarification"):
            reply = str(result["clarification"])[:1000]
            if pending:
                pending.original_text = request_text[:8000]
                pending.question = reply
                pending.expires_at = utcnow() + timedelta(minutes=30)
            else:
                db.add(TelegramPending(user_id=user.id, original_text=text[:8000], question=reply,
                                       expires_at=utcnow() + timedelta(minutes=30)))
        else:
            try:
                batch = ActionBatchIn.model_validate(result)
            except ValidationError:
                return "Non ho capito quali dati salvare. Riformula il messaggio."
            created = create_actions(db, ctx, batch)
            if pending:
                db.delete(pending)
            labels = [str(action.data.get("title") or action.data.get("label")) for action in batch.actions]
            reply = "Salvato: " + ", ".join(labels) + "."
    db.add(TelegramUpdate(update_id=update_id, response=reply))
    db.commit()
    return reply
