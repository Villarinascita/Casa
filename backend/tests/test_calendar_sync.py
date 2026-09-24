from datetime import datetime, timezone

from sqlalchemy import select

from app.calendar_sync import apply_remote_event, push_local_event
from app.models import CalendarEventLink, Event, GoogleCalendar, GoogleConnection, User


def test_remote_work_event_imports_only_busy_details(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        calendar = GoogleCalendar(connection_id=connection.id, external_id="work", title="Lavoro", mode="busy")
        db.add(calendar)
        db.flush()
        remote = {"id": "visit-1", "etag": '"v1"', "summary": "Paziente Mario Rossi",
                  "description": "Dati clinici", "location": "Studio", "status": "confirmed",
                  "start": {"dateTime": "2026-09-29T15:00:00+02:00"},
                  "end": {"dateTime": "2026-09-29T16:00:00+02:00"}}
        apply_remote_event(db, connection, calendar, remote)
        db.commit()
        event = db.scalar(select(Event))
        assert event.title == "Occupato"
        assert event.notes is None
        assert event.location == "Studio"
        assert db.scalar(select(CalendarEventLink)).etag == '"v1"'


def test_remote_change_after_local_edit_creates_conflict(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        calendar = GoogleCalendar(connection_id=connection.id, external_id="personal", title="Personale", mode="full")
        db.add(calendar)
        db.flush()
        remote = {"id": "event-1", "etag": '"v1"', "summary": "Palestra", "status": "confirmed",
                  "start": {"dateTime": "2026-09-29T15:00:00+02:00"},
                  "end": {"dateTime": "2026-09-29T16:00:00+02:00"}}
        apply_remote_event(db, connection, calendar, remote)
        db.commit()
        event = db.scalar(select(Event))
        event.title = "Palestra spostata"
        db.commit()
        apply_remote_event(db, connection, calendar, {**remote, "etag": '"v2"', "summary": "Nuoto"})
        db.commit()
        link = db.scalar(select(CalendarEventLink))
        assert link.status == "conflict"
        assert event.title == "Palestra spostata"
        assert link.remote_payload["title"] == "Nuoto"


def test_local_event_is_created_on_default_google_calendar(db_factory, seed):
    class FakeService:
        def access_token(self, connection):
            return "access"

        class api:
            @staticmethod
            def post(url, token, body):
                assert url.endswith("/calendars/personal/events")
                assert body["summary"] == "Palestra"
                return {"id": body["id"], "etag": '"v1"'}

    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        calendar = GoogleCalendar(connection_id=connection.id, external_id="personal", title="Personale",
                                  mode="full", outbound_default=True)
        db.add(calendar)
        event = Event(household_id=seed["Rossi"], created_by=user.id, title="Palestra",
                      start_at=datetime(2026, 9, 29, 15, tzinfo=timezone.utc), all_day=False)
        db.add(event)
        db.commit()
        assert push_local_event(db, connection, event, FakeService()) == "created"
        assert db.scalar(select(CalendarEventLink)).event_id == event.id


def test_user_can_resolve_conflict_by_accepting_google_version(luca, db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        calendar = GoogleCalendar(connection_id=connection.id, external_id="personal", title="Personale", mode="full")
        db.add(calendar)
        db.flush()
        apply_remote_event(db, connection, calendar, {"id": "event-1", "etag": '"v1"', "summary": "Palestra",
                                                   "status": "confirmed", "start": {"dateTime": "2026-09-29T15:00:00+02:00"}})
        db.commit()
        event = db.scalar(select(Event))
        event.title = "Locale"
        db.commit()
        apply_remote_event(db, connection, calendar, {"id": "event-1", "etag": '"v2"', "summary": "Google",
                                                   "status": "confirmed", "start": {"dateTime": "2026-09-29T15:00:00+02:00"}})
        db.commit()
        link_id = db.scalar(select(CalendarEventLink)).id
    response = luca.post(f"/api/v1/calendar/conflicts/{link_id}/resolve", json={"choice": "google"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "synced"
    assert luca.get("/api/v1/events").json()[0]["title"] == "Google"
