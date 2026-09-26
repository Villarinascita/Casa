import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import habits
from app.dedup import similarity
from app.gmail_sync import ingest_message
from app.models import EmailFeedback, Event, GoogleConnection, Proposal, Task, User

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("a,b", [
    ("Inizio allenamenti GIOCAGYM", "GIOCA GYM 2026/27: inizio allenamenti (settimana del 14/09)"),
    ("Inizio allenamenti GIOCAGYM", "Inizio allenamenti corso GIOCA GYM 4-5 anni - Polisportiva Nazareno"),
    ("ASILO NIDO MATILDE", "MATILDE ASILO NIDO"),
    ("GIARDINIERE ORE 8 E 200", "GIARDINIERE ORE 8, POTATURA ALBICOCCO E 200"),
    ("Rinnova il dominio mariachiaramarchesini.eu", "Rinnovare dominio mariachiaramarchesini.eu (Register SpA)"),
])
def test_stesso_impegno_scritto_diversamente(a, b):
    assert similarity(a, b) >= 0.85


@pytest.mark.parametrize("a,b", [
    ("PILATES ORE 9-11", "ORE 11 OSTETRICA"),
    ("Rinnova dominio mariachiaramarchesini.info", "Rinnova dominio mariachiaramarchesini.eu"),
    ("Dentista Meri", "Nuoto Sofia"),
    ("Aggiorna il metodo di pagamento per l'ordine Amazon 404-5344434-0819503 (pagamento rifiutato)",
     "Aggiornare il metodo di pagamento per l'ordine Amazon 404-3108009-4813105"),
])
def test_impegni_diversi(a, b):
    assert similarity(a, b) < 0.85


def _connection(db, seed):
    user = db.scalar(select(User).where(User.login == "luca"))
    connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                  refresh_token_encrypted="x")
    db.add(connection)
    db.commit()
    return connection


def _message(message_id, sender="Polisportiva <info@nazareno.it>"):
    return {"id": message_id, "threadId": "t", "labelIds": ["INBOX"], "snippet": "x",
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": "Avviso"}],
                        "body": {"data": base64.urlsafe_b64encode(b"x").decode()}}}


def _event(title, start_at=None, start_date=None):
    data = {"title": title}
    data.update({"start_at": start_at} if start_at else {"all_day": True, "start_date": start_date})
    return {"actions": [{"kind": "event", "data": data}]}


def _google_event(db, seed, title, **fields):
    db.add(Event(household_id=seed["Rossi"], title=title, source="google", **fields))
    db.commit()


def test_doppione_scritto_diversamente_non_si_crea(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _google_event(db, seed, "Inizio allenamenti GIOCAGYM", all_day=True, start_date=date(2026, 9, 14))
        ingest_message(db, connection, _message("m1"),
                       lambda t: _event("GIOCA GYM 2026/27: inizio allenamenti", start_date="2026-09-14"),
                       "Europe/Rome", NOW)
        assert len(db.scalars(select(Event)).all()) == 1 and db.scalar(select(Proposal)) is None


def test_stesso_impegno_orario_vicino_si_scarta(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _google_event(db, seed, "GIARDINIERE ORE 8.00 E 200",
                      start_at=datetime(2026, 9, 24, 7, tzinfo=timezone.utc),
                      end_at=datetime(2026, 9, 24, 8, tzinfo=timezone.utc))
        ingest_message(db, connection, _message("m1"),
                       lambda t: _event("GIARDINIERE ORE 8, POTATURA ALBICOCCO E 200", "2026-09-24T08:30:00+02:00"),
                       "Europe/Rome", NOW)
        assert len(db.scalars(select(Event)).all()) == 1 and db.scalar(select(Proposal)) is None


def test_stesso_impegno_orario_diverso_va_in_da_controllare(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _google_event(db, seed, "Giardiniere Silvestre", start_at=datetime(2026, 9, 24, 7, tzinfo=timezone.utc))
        ingest_message(db, connection, _message("m1"),
                       lambda t: _event("Giardiniere Silvestre potatura", "2026-09-24T15:00:00+02:00"),
                       "Europe/Rome", NOW)
        assert len(db.scalars(select(Event)).all()) == 1
        proposal = db.scalar(select(Proposal))
        assert proposal.kind == "event" and "alle 09:00" in proposal.snippet


def test_caso_dubbio_decide_hermes(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _google_event(db, seed, "LIONE", all_day=True, start_date=date(2026, 10, 31))
        asked = []

        def judge(title, existing):
            asked.append((title, existing))
            return 0

        ingest_message(db, connection, _message("m1"),
                       lambda t: _event("Volo per Lione da Venezia", start_date="2026-10-31"), "Europe/Rome", NOW,
                       judge=judge)
        assert asked == [("Volo per Lione da Venezia", ["LIONE"])]
        assert len(db.scalars(select(Event)).all()) == 1


def test_giorni_diversi_non_sono_doppioni(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _google_event(db, seed, "ASILO NIDO MATILDE", start_at=datetime(2026, 10, 2, 6, tzinfo=timezone.utc))
        ingest_message(db, connection, _message("m1"),
                       lambda t: _event("MATILDE ASILO NIDO", "2026-10-07T08:00:00+02:00"), "Europe/Rome", NOW)
        assert len(db.scalars(select(Event)).all()) == 2


def test_attivita_simile_non_si_duplica_e_segna_la_provenienza(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        ingest_message(db, connection, _message("m1"), lambda t: {"actions": [
            {"kind": "task", "data": {"title": "Rinnova il dominio mariachiaramarchesini.eu"}}]}, "Europe/Rome", NOW)
        ingest_message(db, connection, _message("m2"), lambda t: {"actions": [
            {"kind": "task", "data": {"title": "Rinnovare dominio mariachiaramarchesini.eu (Register SpA)"}}]},
            "Europe/Rome", NOW)
        tasks = db.scalars(select(Task)).all()
        assert len(tasks) == 1
        assert tasks[0].source == "gmail" and tasks[0].source_sender == "Polisportiva <info@nazareno.it>"


def test_eliminare_registra_lo_scarto_e_annulla_lo_toglie(luca, db_factory, seed):
    with db_factory() as db:
        event = Event(household_id=seed["Rossi"], title="Webinar AI", source="gmail",
                      source_sender="news@webinar.com", start_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc))
        db.add(event)
        db.commit()
        event_id, version = event.id, event.version
    deleted = luca.delete(f"/api/v1/events/{event_id}", headers={"If-Match": str(version)})
    assert deleted.status_code == 200, deleted.text
    with db_factory() as db:
        feedback = db.scalar(select(EmailFeedback))
        assert (feedback.title, feedback.verdict, feedback.sender) == ("Webinar AI", "discarded", "news@webinar.com")
    restored = luca.post(f"/api/v1/events/{event_id}/restore", headers={"If-Match": str(deleted.json()["version"])})
    assert restored.status_code == 200
    with db_factory() as db:
        assert db.scalar(select(EmailFeedback)) is None


def test_eliminare_cose_inserite_a_mano_non_insegna_nulla(luca, db_factory, seed):
    created = luca.post("/api/v1/tasks", json={"title": "Comprare il pane"}).json()
    luca.delete(f"/api/v1/tasks/{created['id']}", headers={"If-Match": str(created["version"])})
    with db_factory() as db:
        assert db.scalar(select(EmailFeedback)) is None


def test_mittente_scartato_sempre_non_propone_piu_nulla(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        for i in range(3):
            habits.record(db, seed["Rossi"], "event", f"Evento {i}", "Banca <news@banca.it>", "discarded")
        db.commit()
        assert habits.always_discarded(db, seed["Rossi"], "Altra <info@banca.it>")
        ingest_message(db, connection, _message("m1", "Banca <eventi@banca.it>"),
                       lambda t: _event("Convegno finanza", "2026-11-03T18:00:00+01:00"), "Europe/Rome", NOW)
        assert db.scalar(select(Event)) is None
        habits.record(db, seed["Rossi"], "event", "Appuntamento consulente", "news@banca.it", "kept")
        db.commit()
        assert not habits.always_discarded(db, seed["Rossi"], "news@banca.it")


def test_esempi_per_hermes_e_prompt(db_factory, seed):
    import httpx
    from app.hermes_client import HermesClient
    with db_factory() as db:
        habits.record(db, seed["Rossi"], "event", "Webinar Twilio", None, "discarded")
        habits.record(db, seed["Rossi"], "task", "Pagare la mensa", None, "kept")
        db.commit()
        examples = habits.examples(db, seed["Rossi"])
    assert examples == {"discarded": ["Webinar Twilio"], "kept": ["Pagare la mensa"]}
    captured = {}

    def respond(request):
        captured["body"] = request.content.decode("unicode_escape")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"actions":[]}'}}]})

    HermesClient("http://h", "k", "m", httpx.Client(transport=httpx.MockTransport(respond))).analyze_email(
        "x", "Europe/Rome", "m", ["Altro"], examples=examples)
    assert "Webinar Twilio" in captured["body"] and "Pagare la mensa" in captured["body"]


def test_same_event_legge_la_risposta_di_hermes():
    import httpx
    from app.hermes_client import HermesClient
    replies = iter(['{"same": 1}', '{"same": null}', 'non json'])
    client = HermesClient("http://h", "k", "m", httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]}))))
    assert client.same_event("Volo Lione", ["Nuoto", "LIONE"], "m") == 1
    assert client.same_event("Volo Lione", ["Nuoto"], "m") is None
    assert client.same_event("Volo Lione", ["Nuoto"], "m") is None


def test_proposte_insegnano(luca, db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = _connection(db, seed)
        proposal = Proposal(household_id=seed["Rossi"], created_by=user.id, connection_id=connection.id,
                            message_id="m9", thread_id="t", item_index=0, kind="event", sender="scuola@x.it",
                            data={"title": "Colloquio", "start_at": "2026-10-01T15:00:00+02:00"})
        db.add(proposal)
        db.commit()
        proposal_id, version = proposal.id, proposal.version
    response = luca.post(f"/api/v1/proposals/{proposal_id}/review", json={"decision": "accept"},
                         headers={"If-Match": str(version)})
    assert response.status_code == 200, response.text
    with db_factory() as db:
        feedback = db.scalar(select(EmailFeedback))
        assert (feedback.title, feedback.verdict) == ("Colloquio", "kept")
        event = db.scalar(select(Event))
        assert event.source == "gmail" and event.source_sender == "scuola@x.it"


def test_costi_ricevuta_pagata_e_doppione(db_factory, seed):
    from app.models import Bill
    with db_factory() as db:
        connection = _connection(db, seed)
        receipt = {"actions": [], "bills": [{"category": "Altro", "title": "Pagamento Netflix", "supplier": "Netflix",
                                              "amount": 6.99, "due_date": "2026-09-25", "payment_state": "pagato"}]}
        again = {"actions": [], "bills": [{"category": "Altro", "title": "Abbonamento Netflix settembre",
                                            "supplier": "NETFLIX SERVICES ITA", "amount": 6.99, "due_date": "2026-09-26"}]}
        ingest_message(db, connection, _message("m1"), lambda t: receipt, "Europe/Rome", NOW)
        ingest_message(db, connection, _message("m2"), lambda t: again, "Europe/Rome", NOW)
        bills = db.scalars(select(Bill)).all()
        assert len(bills) == 1 and bills[0].payment_state == "pagato"


def test_costi_diversi_stesso_importo_restano(db_factory, seed):
    from app.models import Bill
    with db_factory() as db:
        connection = _connection(db, seed)
        for i, (title, supplier) in enumerate([("Bolletta luce", "Octopus"), ("Rata assicurazione", "Prima")]):
            ingest_message(db, connection, _message(f"m{i}"), lambda t, a=title, b=supplier: {"actions": [], "bills": [
                {"category": "Altro", "title": a, "supplier": b, "amount": 62.22, "due_date": "2026-09-10"}]},
                "Europe/Rome", NOW)
        assert len(db.scalars(select(Bill)).all()) == 2


def test_eliminare_un_costo_dalle_email_insegna(luca, db_factory, seed):
    from app.models import Bill
    with db_factory() as db:
        bill = Bill(household_id=seed["Rossi"], category="Altro", title="Preventivo scheda caldaia", amount=440,
                    source_sender="Mantec <info@mantec.it>")
        db.add(bill)
        db.commit()
        bill_id, version = bill.id, bill.version
    assert luca.delete(f"/api/v1/bills/{bill_id}", headers={"If-Match": str(version)}).status_code == 200
    with db_factory() as db:
        feedback = db.scalar(select(EmailFeedback))
        assert (feedback.kind, feedback.title) == ("bill", "Preventivo scheda caldaia")


def test_prompt_esclude_preventivi():
    import httpx
    from app.hermes_client import HermesClient
    captured = {}

    def respond(request):
        captured["body"] = __import__("json").loads(request.content)["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"actions":[]}'}}]})

    HermesClient("http://h", "k", "m", httpx.Client(transport=httpx.MockTransport(respond))).analyze_email(
        "x", "Europe/Rome", "m", ["Altro"])
    for phrase in ("preventivi", "costi condizionati", "opzioni alternative", "«pagato» se l'email è una ricevuta"):
        assert phrase in captured["body"], phrase
