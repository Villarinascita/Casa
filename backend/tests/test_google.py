from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.google import GoogleService
from app.models import CalendarEventLink, EmailProcessed, Event, GoogleCalendar, GoogleConnection, GoogleOAuthState, Proposal, User
from app.main import app
from app.routers.google_connections import get_service
from app.security import Ctx


def test_google_oauth_state_binds_account_and_encrypts_refresh_token(db_factory, seed):
    class FakeApi:
        def exchange_code(self, code, redirect_uri):
            assert code == "google-code"
            return {"access_token": "access", "refresh_token": "secret-refresh"}

        def profile(self, access_token):
            return {"emailAddress": "luca@gmail.com"}

    key = "wVAlSzz5RaOEhYrG_tn3M_UFGxE8DnfNBUoUxgS2k2M="
    service = GoogleService("client", "secret", "https://insieme.example/api/v1/connections/google/callback", key,
                            FakeApi())
    with db_factory() as db:
        ctx = Ctx(db.scalar(select(User).where(User.login == "luca")).id, "luca", seed["Rossi"], "admin")
        url = service.start(db, ctx)
        state = parse_qs(urlparse(url).query)["state"][0]
        connection = service.finish(db, state, "google-code")
        assert connection.email == "luca@gmail.com"
        assert connection.refresh_token_encrypted != "secret-refresh"
        assert service.refresh_token(connection) == "secret-refresh"
        assert db.scalar(select(GoogleOAuthState)) is None


def test_calendar_selection_rejects_busy_as_outbound_default(luca, db_factory, seed):
    class FakeService:
        def access_token(self, connection):
            return "access"

        class api:
            @staticmethod
            def get(url, token):
                return {"items": [{"id": "work", "summary": "Lavoro", "accessRole": "owner"}]}

    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        db.add(GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                refresh_token_encrypted="encrypted"))
        db.commit()
    app.dependency_overrides[get_service] = lambda: FakeService()
    try:
        response = luca.put("/api/v1/connections/google/calendars", json=[
            {"id": "work", "title": "Lavoro", "mode": "busy", "outbound_default": True}])
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_calendar_selection_rejects_readonly_as_outbound_default(luca, db_factory, seed):
    class FakeService:
        def access_token(self, connection):
            return "access"

        class api:
            @staticmethod
            def get(url, token):
                return {"items": [{"id": "shared", "summary": "Condiviso", "accessRole": "reader"}]}

    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        db.add(GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                refresh_token_encrypted="encrypted"))
        db.commit()
    app.dependency_overrides[get_service] = lambda: FakeService()
    try:
        response = luca.put("/api/v1/connections/google/calendars", json=[
            {"id": "shared", "title": "Condiviso", "mode": "full", "outbound_default": True}])
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_disconnect_removes_google_records_without_deleting_local_event(luca, db_factory, seed):
    from datetime import datetime, timezone

    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        calendar = GoogleCalendar(connection_id=connection.id, external_id="personal", title="Personale")
        event = Event(household_id=seed["Rossi"], created_by=user.id, title="Visita", all_day=False,
                      start_at=datetime(2026, 9, 29, tzinfo=timezone.utc))
        db.add_all([calendar, event])
        db.flush()
        db.add(CalendarEventLink(calendar_id=calendar.id, event_id=event.id,
                                 external_id="remote-1", local_version=event.version))
        db.add(EmailProcessed(connection_id=connection.id, message_id="mail-1"))
        db.add(Proposal(household_id=seed["Rossi"], created_by=user.id, connection_id=connection.id,
                        message_id="mail-1", thread_id="thread-1", item_index=0,
                        kind="task", data={"title": "Comprare latte"}))
        db.commit()
    response = luca.delete("/api/v1/connections/google")
    assert response.status_code == 204, response.text
    with db_factory() as db:
        assert db.scalar(select(GoogleConnection)) is None
        assert db.scalar(select(GoogleCalendar)) is None
        assert db.scalar(select(CalendarEventLink)) is None
        assert db.scalar(select(EmailProcessed)) is None
        assert db.scalar(select(Proposal)) is None
        assert db.scalar(select(Event)).title == "Visita"


def test_scope_gmail_consente_il_cestino_ma_non_la_sola_lettura():
    from app.google import SCOPES
    assert "https://www.googleapis.com/auth/gmail.modify" in SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" not in SCOPES
