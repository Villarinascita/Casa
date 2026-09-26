import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.email_cleanup import TrashNotPermitted
from app.email_promotions import dispatch_promo_summaries, is_promotion_to_trash, keep_sender
from app.gmail_sync import ingest_message
from app.models import (ChannelLink, EmailAutoTrash, EmailDomainCleanup, EmailProcessed, GoogleConnection,
                        Household, User)
from app.telegram import process_update

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
PROMO = {"actions": [], "bills": [], "promo": True}


def _message(message_id="m1", sender="Temu <temu@eu.temuemail.com>", unsubscribe=True, labels=("INBOX",)):
    headers = [{"name": "From", "value": sender}, {"name": "Subject", "value": "Sconti -90%"}]
    if unsubscribe:
        headers.append({"name": "List-Unsubscribe", "value": "<mailto:unsub@temu.com>"})
    return {"id": message_id, "threadId": "t", "labelIds": list(labels), "snippet": "Sconti",
            "payload": {"headers": headers, "body": {"data": base64.urlsafe_b64encode(b"Sconti").decode()}}}


def _connection(db, seed):
    user = db.scalar(select(User).where(User.login == "luca"))
    connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                  refresh_token_encrypted="x")
    db.add(connection)
    db.commit()
    return connection


def _headers(message):
    return {h["name"].lower(): h["value"] for h in message["payload"]["headers"]}


@pytest.mark.parametrize("message,promo,created,kept,expected", [
    (_message(), True, 0, [], True),
    (_message(), False, 0, [], False),                                   # Hermes: non è pubblicità
    (_message(unsubscribe=False), True, 0, [], False),                   # nessun segnale di massa
    (_message(unsubscribe=False, labels=("CATEGORY_PROMOTIONS",)), True, 0, [], True),
    (_message(), True, 1, [], False),                                    # ha prodotto qualcosa
    (_message(labels=("INBOX", "STARRED")), True, 0, [], False),
    (_message(labels=("INBOX", "IMPORTANT")), True, 0, [], False),
    (_message(), True, 0, ["temuemail.com"], False),                     # mittente da tenere
])
def test_regola_di_decisione(message, promo, created, kept, expected):
    assert is_promotion_to_trash(message, _headers(message), promo, created, kept) is expected


def test_pubblicita_va_nel_cestino_e_si_registra(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        trashed = []
        ingest_message(db, connection, _message(), lambda text: PROMO, "Europe/Rome", NOW,
                       trash=trashed.append, auto_trash_promotions=True)
        row = db.scalar(select(EmailAutoTrash))
        assert trashed == ["m1"]
        assert row.sender == "temu@eu.temuemail.com" and row.subject == "Sconti -90%"
        assert row.recipient_user_id == connection.user_id and row.reported_at is None
        assert db.scalar(select(EmailProcessed)).message_id == "m1"


def test_impostazione_spenta_o_promo_non_booleano_non_cestina(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        trashed = []
        ingest_message(db, connection, _message("m1"), lambda text: PROMO, "Europe/Rome", NOW,
                       trash=trashed.append, auto_trash_promotions=False)
        ingest_message(db, connection, _message("m2"), lambda text: {"actions": [], "promo": "true"},
                       "Europe/Rome", NOW, trash=trashed.append, auto_trash_promotions=True)
        assert trashed == [] and db.scalar(select(EmailAutoTrash)) is None


def test_bolletta_in_email_pubblicitaria_non_cestina(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        trashed = []
        result = {"actions": [], "promo": True,
                  "bills": [{"category": "Bollette", "title": "Luce", "amount": 50.0}]}
        ingest_message(db, connection, _message(), lambda text: result, "Europe/Rome", NOW,
                       trash=trashed.append, auto_trash_promotions=True)
        assert trashed == []


def test_senza_permesso_non_registra(db_factory, seed):
    def forbidden(message_id):
        raise TrashNotPermitted("403")

    with db_factory() as db:
        connection = _connection(db, seed)
        ingest_message(db, connection, _message(), lambda text: PROMO, "Europe/Rome", NOW,
                       trash=forbidden, auto_trash_promotions=True)
        assert db.scalar(select(EmailAutoTrash)) is None
        assert db.scalar(select(EmailProcessed)).message_id == "m1"


def _trashed(db, connection, sender, when):
    db.add(EmailAutoTrash(household_id=connection.household_id, connection_id=connection.id,
                          recipient_user_id=connection.user_id, message_id=sender + str(when),
                          sender=sender, subject="x", trashed_at=when))
    db.commit()


def _link_telegram(db, connection):
    db.add(ChannelLink(household_id=connection.household_id, user_id=connection.user_id,
                       platform="telegram", external_user_id="123", chat_id="123"))
    db.commit()


def test_riepilogo_dopo_sette_giorni_con_conteggi(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _link_telegram(db, connection)
        _trashed(db, connection, "temu@eu.temuemail.com", NOW - timedelta(days=6))
        sent = []
        assert dispatch_promo_summaries(db, lambda chat, text: sent.append((chat, text)), NOW) == 0
        _trashed(db, connection, "temu@eu.temuemail.com", NOW - timedelta(days=7))
        _trashed(db, connection, "insieme@newsletter.conad.com", NOW - timedelta(days=1))
        assert dispatch_promo_summaries(db, lambda chat, text: sent.append((chat, text)), NOW) == 1
        chat, text = sent[0]
        assert chat == "123"
        assert "3 email" in text and "eu.temuemail.com 2" in text and "newsletter.conad.com 1" in text
        assert all(row.reported_at == NOW for row in db.scalars(select(EmailAutoTrash)))
        assert dispatch_promo_summaries(db, lambda chat, text: sent.append((chat, text)), NOW) == 0


def test_riepilogo_senza_telegram_non_parte(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _trashed(db, connection, "temu@eu.temuemail.com", NOW - timedelta(days=8))
        assert dispatch_promo_summaries(db, lambda chat, text: None, NOW) == 0
        assert db.scalar(select(EmailAutoTrash)).reported_at is None


def test_tieni_con_parola_trova_il_dominio_e_lo_toglie_dai_bloccati(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        household = db.get(Household, seed["Rossi"])
        household.settings = {**household.settings, "blocked_email_domains": ["newsletter.conad.com"]}
        db.add(EmailDomainCleanup(household_id=household.id, connection_id=connection.id,
                                  domain="newsletter.conad.com"))
        db.commit()
        _trashed(db, connection, "insieme@newsletter.conad.com", NOW)
        reply = keep_sender(db, seed["Rossi"], "Conad")
        household = db.get(Household, seed["Rossi"])
        assert "newsletter.conad.com" in reply
        assert household.settings["kept_email_senders"] == ["newsletter.conad.com"]
        assert household.settings["blocked_email_domains"] == []
        assert db.scalar(select(EmailDomainCleanup)).status == "done"


def test_tieni_ambiguo_o_sconosciuto_chiede_il_dominio(db_factory, seed):
    with db_factory() as db:
        connection = _connection(db, seed)
        _trashed(db, connection, "a@news.shop-uno.it", NOW)
        _trashed(db, connection, "b@news.shop-due.it", NOW)
        assert "Ho trovato" in keep_sender(db, seed["Rossi"], "shop")
        assert "dominio preciso" in keep_sender(db, seed["Rossi"], "boh")
        assert "kept_email_senders" not in db.get(Household, seed["Rossi"]).settings


def test_tieni_dominio_esplicito_da_telegram(luca, db_factory, seed):
    code = luca.post("/api/v1/connections/telegram/start").json()["code"]
    with db_factory() as db:
        process_update(db, {"update_id": 1, "message": {"from": {"id": 123},
            "chat": {"id": 123, "type": "private"}, "text": f"/link {code}"}}, lambda *_: {})
        reply = process_update(db, {"update_id": 2, "message": {"from": {"id": 123},
            "chat": {"id": 123, "type": "private"}, "text": "Tieni Promo@Amazon.it"}},
            lambda *_: pytest.fail("non deve passare da Hermes"))
        assert "promo@amazon.it" in reply
        assert db.get(Household, seed["Rossi"]).settings["kept_email_senders"] == ["promo@amazon.it"]


def test_api_impostazioni_e_elenco(luca, anna, marco, db_factory, seed):
    household = luca.get("/api/v1/household").json()
    assert household["auto_trash_promotions"] is True and household["kept_email_senders"] == []
    updated = luca.patch("/api/v1/household", json={"auto_trash_promotions": False,
                                                    "kept_email_senders": [" Conad.COM "]},
                         headers={"If-Match": str(household["version"])})
    assert updated.status_code == 200, updated.text
    assert updated.json()["auto_trash_promotions"] is False
    assert updated.json()["kept_email_senders"] == ["conad.com"]
    bad = luca.patch("/api/v1/household", json={"kept_email_senders": ["non valido"]},
                     headers={"If-Match": str(updated.json()["version"])})
    assert bad.status_code == 422
    with db_factory() as db:
        connection = _connection(db, seed)
        _trashed(db, connection, "temu@eu.temuemail.com", NOW)
    listed = luca.get("/api/v1/household/auto-trashed").json()
    assert [row["sender"] for row in listed] == ["temu@eu.temuemail.com"]
    assert marco.get("/api/v1/household/auto-trashed").json() == []
