import base64

from sqlalchemy import select

from app.gmail_sync import ingest_message, sync_gmail
from app.hermes_client import HermesInvalidResponse
from app.models import EmailProcessed, GoogleConnection, Proposal, User


def test_gmail_message_becomes_reviewable_proposal_once(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-1", "threadId": "thread-1", "snippet": "Visita martedì",
                   "payload": {"headers": [{"name": "From", "value": "studio@example.com"},
                                           {"name": "Subject", "value": "Visita"}],
                               "body": {"data": base64.urlsafe_b64encode(b"Visita martedi ore 15").decode()}}}
        calls = []

        def analyze(text):
            calls.append(text)
            return {"actions": [{"kind": "event", "data": {
                "title": "Visita", "start_at": "2026-09-29T15:00:00+02:00"}}]}

        assert ingest_message(db, connection, message, analyze) == 1
        assert ingest_message(db, connection, message, analyze) == 0
        proposal = db.scalar(select(Proposal))
        assert proposal.status == "pending"
        assert proposal.sender == "studio@example.com"
        assert proposal.data["title"] == "Visita"
        assert len(calls) == 1
        assert db.scalar(select(EmailProcessed)).message_id == "mail-1"


def test_gmail_message_with_invalid_hermes_response_is_marked_processed_once(db_factory, seed):
    """Un contenuto inutilizzabile per questo messaggio non deve farlo ritentare a ogni giro."""
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-bad", "threadId": "thread-bad", "snippet": "Testo confuso",
                   "payload": {"headers": [], "body": {"data": base64.urlsafe_b64encode(b"Testo confuso").decode()}}}

        def broken_analyze(text):
            raise HermesInvalidResponse("Hermes non ha restituito proposte valide per questo messaggio")

        assert ingest_message(db, connection, message, broken_analyze) == 0
        assert db.scalar(select(EmailProcessed)).message_id == "mail-bad"
        assert db.scalar(select(Proposal)) is None
        # Al giro successivo il messaggio è già "seen": non richiama più analyze.
        calls = []
        assert ingest_message(db, connection, message,
                              lambda text: calls.append(text) or {"actions": []}) == 0
        assert calls == []


def test_accepting_proposal_creates_event_once(luca, db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        proposal = Proposal(household_id=seed["Rossi"], created_by=user.id, connection_id=connection.id,
                            message_id="mail-2", thread_id="thread-2", item_index=0,
                            kind="event", data={"title": "Visita", "start_at": "2026-09-29T15:00:00+02:00"})
        db.add(proposal)
        db.commit()
        proposal_id, version = proposal.id, proposal.version
    first = luca.post(f"/api/v1/proposals/{proposal_id}/review", json={"decision": "accept"},
                      headers={"If-Match": str(version)})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "accepted"
    assert len(luca.get("/api/v1/events").json()) == 1
    again = luca.post(f"/api/v1/proposals/{proposal_id}/review", json={"decision": "accept"},
                      headers={"If-Match": str(first.json()["version"])})
    assert again.status_code == 200
    assert len(luca.get("/api/v1/events").json()) == 1


def test_gmail_sync_uses_query_and_advances_page_cursor(db_factory, seed):
    class FakeService:
        def access_token(self, connection):
            return "access"

        class api:
            calls = []

            @classmethod
            def get(cls, url, token, params=None):
                cls.calls.append((url, params))
                if url.endswith("/messages"):
                    return {"messages": [{"id": "mail-3"}], "nextPageToken": "next"}
                return {"id": "mail-3", "threadId": "thread-3", "snippet": "Latte",
                        "payload": {"headers": [], "body": {"data": "TGF0dGU="}}}

    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted",
                                      gmail_query="in:inbox from:market@example.com")
        db.add(connection)
        db.commit()
        count = sync_gmail(db, connection, FakeService(),
                           lambda text: {"actions": [{"kind": "shopping", "data": {"label": "Latte"}}]})
        assert count == 1
        assert connection.gmail_page_token == "next"
        assert "in:inbox from:market@example.com" in FakeService.api.calls[0][1]["q"]
