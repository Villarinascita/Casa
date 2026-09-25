import base64
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.gmail_sync import ingest_message, sync_gmail
from app.hermes_client import HermesInvalidResponse
from app.models import Bill, EmailCreationNotice, EmailProcessed, Event, GoogleConnection, Proposal, Task, User


def test_gmail_shopping_becomes_reviewable_proposal_once(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-1", "threadId": "thread-1", "snippet": "Prendi il latte",
                   "payload": {"headers": [{"name": "From", "value": "studio@example.com"},
                                           {"name": "Subject", "value": "Spesa"}],
                               "body": {"data": base64.urlsafe_b64encode(b"Prendi il latte").decode()}}}
        calls = []

        def analyze(text):
            calls.append(text)
            return {"actions": [{"kind": "shopping", "data": {"label": "Latte"}}], "bills": []}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 1
        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 0
        proposal = db.scalar(select(Proposal))
        assert proposal.status == "pending"
        assert proposal.sender == "studio@example.com"
        assert proposal.data["label"] == "Latte"
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

        assert ingest_message(db, connection, message, broken_analyze, "Europe/Rome") == 0
        assert db.scalar(select(EmailProcessed)).message_id == "mail-bad"
        assert db.scalar(select(Proposal)) is None
        # Al giro successivo il messaggio è già "seen": non richiama più analyze.
        calls = []
        assert ingest_message(db, connection, message,
                              lambda text: calls.append(text) or {"actions": []}, "Europe/Rome") == 0
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
                           lambda text: {"actions": [{"kind": "shopping", "data": {"label": "Latte"}}], "bills": []},
                           "Europe/Rome")
        assert count == 1
        assert connection.gmail_page_token == "next"
        assert "in:inbox from:market@example.com" in FakeService.api.calls[0][1]["q"]


def test_gmail_event_created_directly_with_notice(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-event", "threadId": "t", "snippet": "Riunione",
                   "payload": {"headers": [{"name": "From", "value": "segreteria@scuola.it"},
                                           {"name": "Subject", "value": "Riunione scuola"}],
                               "body": {"data": base64.urlsafe_b64encode(b"Riunione scuola").decode()}}}

        def analyze(text):
            return {"actions": [{"kind": "event", "data": {
                "title": "Riunione scuola", "start_at": "2026-10-03T17:00:00+02:00"}}], "bills": []}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 1
        assert db.scalar(select(Proposal)) is None
        event = db.scalar(select(Event))
        assert event.title == "Riunione scuola" and event.source == "gmail"
        notice = db.scalar(select(EmailCreationNotice))
        assert notice.entity_type == "event" and notice.entity_id == event.id
        assert notice.recipient_user_id == user.id
        assert "Riunione scuola" in notice.summary and "17:00" in notice.summary
        assert "segreteria@scuola.it" in notice.summary
        assert notice.sent_at is None


def test_gmail_task_created_directly_with_notice(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-task", "threadId": "t", "snippet": "Rinnovo bollo",
                   "payload": {"headers": [{"name": "From", "value": "aci@example.com"}],
                               "body": {"data": base64.urlsafe_b64encode(b"Rinnova il bollo").decode()}}}

        def analyze(text):
            return {"actions": [{"kind": "task", "data": {
                "title": "Rinnovare il bollo auto", "due_date": "2026-10-15"}}], "bills": []}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 1
        task = db.scalar(select(Task))
        assert task.title == "Rinnovare il bollo auto"
        notice = db.scalar(select(EmailCreationNotice))
        assert notice.entity_type == "task" and notice.entity_id == task.id


def test_gmail_bill_created_directly_with_amount(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-bill", "threadId": "t", "snippet": "Bolletta",
                   "payload": {"headers": [{"name": "From", "value": "bollette@enel.it"}],
                               "body": {"data": base64.urlsafe_b64encode("Bolletta luce 45,50€".encode()).decode()}}}

        def analyze(text):
            return {"actions": [], "bills": [{"category": "Bollette", "title": "Bolletta luce",
                                              "supplier": "Enel", "amount": 45.5, "due_date": "2026-10-10"}]}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 1
        bill = db.scalar(select(Bill))
        assert bill.title == "Bolletta luce" and bill.supplier == "Enel"
        assert bill.amount == Decimal("45.50")
        assert bill.payment_state == "da_pagare"
        assert bill.source_sender == "bollette@enel.it"
        assert bill.created_by == user.id


def test_gmail_bill_without_amount_is_not_created(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-no-amount", "threadId": "t", "snippet": "Bolletta",
                   "payload": {"headers": [], "body": {"data": base64.urlsafe_b64encode(b"Bolletta").decode()}}}

        def analyze(text):
            return {"actions": [], "bills": [{"category": "Bollette", "title": "Bolletta senza importo"}]}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 0
        assert db.scalar(select(Bill)) is None
        assert db.scalar(select(EmailProcessed)).message_id == "mail-no-amount"


def test_gmail_no_notice_if_message_transaction_fails(db_factory, seed):
    """Un evento valido seguito da un'attività non valida nello stesso messaggio: tutto o niente."""
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-mixed", "threadId": "t", "snippet": "x",
                   "payload": {"headers": [], "body": {"data": base64.urlsafe_b64encode(b"x").decode()}}}

        def analyze(text):
            return {"actions": [
                {"kind": "event", "data": {"title": "Valido", "start_at": "2026-10-03T17:00:00+02:00"}},
                {"kind": "task", "data": {"title": ""}},  # title vuoto: fallisce la validazione
            ], "bills": []}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 0
        assert db.scalar(select(Event)) is None
        assert db.scalar(select(EmailCreationNotice)) is None
        assert db.scalar(select(EmailProcessed)).message_id == "mail-mixed"


def test_gmail_event_with_bogus_member_id_still_creates_event_and_marks_processed(db_factory, seed):
    """Root cause del finding §1: un member_id inventato dal modello non deve far fallire
    il flush (FK) né lasciare il messaggio permanentemente non processato."""
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-bogus-member", "threadId": "t", "snippet": "Riunione",
                   "payload": {"headers": [{"name": "From", "value": "segreteria@scuola.it"}],
                               "body": {"data": base64.urlsafe_b64encode(b"Riunione scuola").decode()}}}

        def analyze(text):
            return {"actions": [{"kind": "event", "data": {
                "title": "Riunione scuola", "start_at": "2026-10-03T17:00:00+02:00",
                "member_id": "does-not-exist"}}], "bills": []}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 1
        event = db.scalar(select(Event))
        assert event is not None and event.member_id is None
        assert db.scalar(select(EmailProcessed)).message_id == "mail-bogus-member"


def test_gmail_bad_bill_is_skipped_without_affecting_other_bill_in_same_message(db_factory, seed):
    """Finding §2: una voce bolletta malformata non deve travolgere le altre bollette dello
    stesso messaggio."""
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-two-bills", "threadId": "t", "snippet": "Bollette",
                   "payload": {"headers": [], "body": {"data": base64.urlsafe_b64encode(b"Bollette").decode()}}}

        def analyze(text):
            return {"actions": [], "bills": [
                {"category": "Bollette", "title": "Malformata", "amount": 10, "currency": "EUR"},
                {"category": "Bollette", "title": "Valida", "amount": 20},
            ]}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 1
        bill = db.scalar(select(Bill))
        assert bill.title == "Valida"
        assert db.scalar(select(EmailProcessed)).message_id == "mail-two-bills"


def test_gmail_past_dated_event_creates_no_notice_but_still_creates_event(db_factory, seed):
    """Finding §3: un evento di backfill con data ormai passata non deve accodare la
    notifica Telegram di controllo, ma va comunque creato."""
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.commit()
        message = {"id": "mail-old-event", "threadId": "t", "snippet": "Vecchia riunione",
                   "payload": {"headers": [{"name": "From", "value": "segreteria@scuola.it"}],
                               "body": {"data": base64.urlsafe_b64encode(b"Vecchia riunione").decode()}}}

        def analyze(text):
            return {"actions": [{"kind": "event", "data": {
                "title": "Vecchia riunione", "start_at": "2026-01-03T17:00:00+01:00"}}], "bills": []}

        now = datetime(2026, 9, 25, tzinfo=timezone.utc)
        assert ingest_message(db, connection, message, analyze, "Europe/Rome", now) == 1
        event = db.scalar(select(Event))
        assert event is not None and event.title == "Vecchia riunione"
        assert db.scalar(select(EmailCreationNotice)) is None


def test_gmail_duplicate_proposal_does_not_stall_ingestion(db_factory, seed):
    """Una Proposal duplicata (stesso connection_id/message_id/item_index, es. da una
    ri-scansione dopo aver azzerato email_processed) non deve bloccare per sempre il
    messaggio: l'errore di vincolo di unicità va gestito, il messaggio segnato processato."""
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id,
                                      email="luca@gmail.com", refresh_token_encrypted="encrypted")
        db.add(connection)
        db.flush()
        # Una Proposal già esistente per lo stesso messaggio/indice, come capiterebbe
        # ri-scansionando un'email già proposta in passato.
        db.add(Proposal(household_id=seed["Rossi"], created_by=user.id, connection_id=connection.id,
                        message_id="mail-dup", thread_id="t", item_index=0,
                        kind="shopping", data={"label": "Latte"}))
        db.commit()

        message = {"id": "mail-dup", "threadId": "t", "snippet": "Prendi il latte",
                   "payload": {"headers": [], "body": {"data": base64.urlsafe_b64encode(b"Latte").decode()}}}

        def analyze(text):
            return {"actions": [{"kind": "shopping", "data": {"label": "Latte"}}], "bills": []}

        assert ingest_message(db, connection, message, analyze, "Europe/Rome") == 0
        assert db.scalar(select(EmailProcessed).where(EmailProcessed.message_id == "mail-dup")) is not None
        # Al giro successivo non lo ritenta.
        calls = []
        assert ingest_message(db, connection, message,
                              lambda text: calls.append(text) or {"actions": []}, "Europe/Rome") == 0
        assert calls == []
