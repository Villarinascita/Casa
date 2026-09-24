from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Event, GoogleCalendar, GoogleConnection, User
from app.worker import run_google_once, run_once


def test_worker_saves_telegram_update_and_advances_cursor(luca, db_factory):
    code = luca.post("/api/v1/connections/telegram/start").json()["code"]
    updates = [{"update_id": 100, "message": {"message_id": 1, "from": {"id": 123},
                "chat": {"id": 123, "type": "private"}, "text": f"/link {code}"}}]

    class Messenger:
        sent = []

        def get_updates(self, offset):
            return [item for item in updates if item["update_id"] >= offset]

        def send(self, chat_id, text):
            self.sent.append((chat_id, text))

    messenger = Messenger()
    with db_factory() as db:
        run_once(db, messenger, lambda *_: {}, datetime(2026, 9, 24, tzinfo=timezone.utc))
        run_once(db, messenger, lambda *_: {}, datetime(2026, 9, 24, tzinfo=timezone.utc))
    assert len(messenger.sent) == 1
    assert messenger.sent[0][0] == "123"


def test_google_worker_runs_gmail_calendar_and_outbound_then_waits_ten_minutes(db_factory, seed, monkeypatch):
    from app import worker

    calls = []

    def fake_gmail(db, connection, service, analyze, now):
        calls.append("gmail")
        connection.last_gmail_sync_at = now
        db.commit()

    def fake_calendar(db, connection, calendar, service, now):
        calls.append("calendar")
        calendar.last_synced_at = now
        db.commit()

    def fake_push(db, connection, event, service):
        calls.append("push")

    monkeypatch.setattr(worker, "sync_gmail", fake_gmail)
    monkeypatch.setattr(worker, "sync_calendar", fake_calendar)
    monkeypatch.setattr(worker, "push_local_event", fake_push)
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        db.add(GoogleCalendar(connection_id=connection.id, external_id="personal", title="Personale"))
        db.add(Event(household_id=seed["Rossi"], created_by=user.id, title="Visita", all_day=False,
                     start_at=now))
        db.commit()
        run_google_once(db, object(), object(), now)
        run_google_once(db, object(), object(), now)
    assert calls == ["gmail", "calendar", "push"]
