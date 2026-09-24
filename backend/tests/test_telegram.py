from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import ChannelLink, TelegramUpdate, User
from app.telegram import process_update


def test_clarification_reuses_original_request(luca, db_factory):
    code = luca.post("/api/v1/connections/telegram/start").json()["code"]
    with db_factory() as db:
        process_update(db, {"update_id": 100, "message": {"from": {"id": 123},
            "chat": {"id": 123, "type": "private"}, "text": f"/link {code}"}}, lambda *_: {})
        seen = []

        def interpret(text, ctx):
            seen.append(text)
            if len(seen) == 1:
                return {"clarification": "A che ora?"}
            return {"actions": [{"kind": "event", "data": {
                "title": "Palestra", "start_at": "2026-09-29T15:00:00+02:00"}}]}

        first = process_update(db, {"update_id": 101, "message": {"from": {"id": 123},
            "chat": {"id": 123, "type": "private"}, "text": "Palestra martedì"}}, interpret)
        second = process_update(db, {"update_id": 102, "message": {"from": {"id": 123},
            "chat": {"id": 123, "type": "private"}, "text": "Alle 15"}}, interpret)
    assert first == "A che ora?"
    assert second.startswith("Salvato:")
    assert "Palestra martedì" in seen[1]
    assert "Alle 15" in seen[1]


def test_link_code_binds_real_telegram_sender(luca, db_factory):
    started = luca.post("/api/v1/connections/telegram/start")
    assert started.status_code == 200, started.text
    code = started.json()["code"]
    update = {"update_id": 41, "message": {"message_id": 4, "from": {"id": 123},
              "chat": {"id": 123, "type": "private"}, "text": f"/link {code}"}}
    with db_factory() as db:
        assert "collegato" in process_update(db, update, lambda *_: {})
        link = db.scalar(select(ChannelLink).where(ChannelLink.external_user_id == "123"))
        assert link.user_id == db.scalar(select(User).where(User.login == "luca")).id


def test_unlinked_sender_cannot_create_actions(seed, db_factory):
    update = {"update_id": 42, "message": {"message_id": 5, "from": {"id": 456},
              "chat": {"id": 456, "type": "private"}, "text": "Aggiungi latte"}}
    with db_factory() as db:
        assert "Collega" in process_update(db, update, lambda *_: {"actions": [
            {"kind": "shopping", "data": {"label": "Latte"}}]})
        assert db.get(TelegramUpdate, 42) is None


def test_telegram_action_is_not_duplicated_on_retry(luca, db_factory):
    code = luca.post("/api/v1/connections/telegram/start").json()["code"]
    link_update = {"update_id": 43, "message": {"message_id": 6, "from": {"id": 123},
                   "chat": {"id": 123, "type": "private"}, "text": f"/link {code}"}}
    command = {"update_id": 44, "message": {"message_id": 7, "from": {"id": 123},
               "chat": {"id": 123, "type": "private"}, "text": "Aggiungi latte"}}
    with db_factory() as db:
        process_update(db, link_update, lambda *_: {})
        calls = []

        def interpret(text, ctx):
            calls.append(text)
            return {"actions": [{"kind": "shopping", "data": {"label": "Latte"}}]}

        first = process_update(db, command, interpret)
        assert "Latte" in first
        assert process_update(db, command, interpret) == first
        assert calls == ["Aggiungi latte"]
    assert len(luca.get("/api/v1/shopping/items").json()) == 1
