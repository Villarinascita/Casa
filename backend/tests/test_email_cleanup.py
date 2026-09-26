import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.email_cleanup import TRASH_PERMISSION_MESSAGE, run_domain_cleanups, trash_message
from app.models import EmailDomainCleanup, GoogleConnection, User

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


INSUFFICIENT_PERMISSIONS_BODY = {
    "error": {"errors": [{"reason": "insufficientPermissions"}]},
}
RATE_LIMIT_BODY = {
    "error": {"errors": [{"reason": "rateLimitExceeded"}]},
}


class FakeApi:
    def __init__(self, pages, senders, status=None, status_body=None, fail_on=()):
        self.pages = pages
        self.senders = senders
        self.status = status
        self.status_body = status_body if status_body is not None else INSUFFICIENT_PERMISSIONS_BODY
        self.fail_on = set(fail_on)
        self.trashed = []
        self.list_params = []

    def get(self, url, token, params=None):
        if url.endswith("/messages"):
            self.list_params.append(params)
            return self.pages.pop(0)
        message_id = url.rsplit("/", 1)[1]
        if message_id in self.fail_on:
            raise RuntimeError(f"errore di rete su {message_id}")
        return {"payload": {"headers": [{"name": "From", "value": self.senders[message_id]}]}}

    def post(self, url, token, body):
        if self.status:
            request = httpx.Request("POST", url)
            content = json.dumps(self.status_body).encode() if self.status_body is not None else b""
            raise httpx.HTTPStatusError(str(self.status), request=request,
                                        response=httpx.Response(self.status, request=request, content=content))
        self.trashed.append(url.rsplit("/", 2)[1])
        return {}


class FakeService:
    def __init__(self, api):
        self.api = api

    def access_token(self, connection):
        return "token"


def _cleanup(db, seed, domain="news.com"):
    user = db.scalar(select(User).where(User.login == "luca"))
    connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="luca@gmail.com",
                                  refresh_token_encrypted="x")
    db.add(connection)
    db.flush()
    db.add(EmailDomainCleanup(household_id=seed["Rossi"], connection_id=connection.id, domain=domain))
    db.commit()
    return connection


def test_pulizia_sposta_solo_il_dominio_esatto_e_si_chiude(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}, {"id": "m2"}]}, {"messages": []}],
                      {"m1": "Promo <a@offerte.news.com>", "m2": "b@notnews.com"})
        service = FakeService(api)
        assert run_domain_cleanups(db, service, NOW) == 1
        row = db.scalar(select(EmailDomainCleanup))
        assert api.trashed == ["m1"]
        assert api.list_params[0]["q"] == "in:inbox from:news.com"
        # ha spostato un'email: resta "running" e riparte dall'inizio al prossimo giro
        assert row.status == "running" and row.trashed_count == 1 and row.page_token is None
        assert run_domain_cleanups(db, service, NOW) == 0
        assert "pageToken" not in api.list_params[1]
        assert row.status == "done" and row.completed_at == NOW


def test_pulizia_riparte_dallinizio_dopo_aver_spostato_email(db_factory, seed):
    """Se una pagina sposta almeno un'email, il giro successivo riparte dall'inizio della
    ricerca invece di seguire nextPageToken, per non saltare messaggi su un set che si restringe."""
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}], "nextPageToken": "p2"}, {"messages": []}],
                      {"m1": "a@news.com"})
        service = FakeService(api)
        run_domain_cleanups(db, service, NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token is None
        run_domain_cleanups(db, service, NOW)
        assert "pageToken" not in api.list_params[1]
        assert row.status == "done" and row.trashed_count == 1


def test_pulizia_segue_il_segnalibro_se_la_pagina_non_sposta_nulla(db_factory, seed):
    """Se una pagina non trova corrispondenze esatte ma Gmail offre altre pagine, si segue
    nextPageToken; quando non ci sono più pagine e non si è spostato nulla, la pulizia finisce."""
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}], "nextPageToken": "p2"}, {"messages": [{"id": "m2"}]}],
                      {"m1": "a@notnews.com", "m2": "b@notnews.com"})
        service = FakeService(api)
        run_domain_cleanups(db, service, NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token == "p2"
        run_domain_cleanups(db, service, NOW)
        assert api.list_params[1]["pageToken"] == "p2"
        assert row.status == "done" and row.trashed_count == 0


def test_pulizia_senza_permesso_resta_in_corso_e_avvisa(db_factory, seed):
    with db_factory() as db:
        connection = _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}]}], {"m1": "a@news.com"}, status=403)
        assert run_domain_cleanups(db, FakeService(api), NOW) == 0
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.trashed_count == 0
        assert db.get(GoogleConnection, connection.id).last_error == TRASH_PERMISSION_MESSAGE


def test_trash_message_ignora_email_gia_sparita():
    trash_message(FakeService(FakeApi([], {}, status=404)), "token", "m1")


def test_errore_su_un_messaggio_non_blocca_gli_altri(db_factory, seed):
    """spec §6/§8: un errore (non-403) su un messaggio non deve fermare la pulizia degli altri."""
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}, {"id": "m2"}]}],
                      {"m1": "a@news.com", "m2": "b@news.com"}, fail_on={"m1"})
        assert run_domain_cleanups(db, FakeService(api), NOW) == 1
        row = db.scalar(select(EmailDomainCleanup))
        assert api.trashed == ["m2"]
        # m1 è fallito ma non ha bloccato m2: resta "running" (ha spostato qualcosa, riparte dall'inizio)
        assert row.status == "running" and row.trashed_count == 1


def test_403_per_limite_di_velocita_non_diventa_permesso_mancante():
    """Un 403 di rate limit (rateLimitExceeded) non è un permesso mancante: va ritentato,
    non convertito in TrashNotPermitted."""
    api = FakeApi([], {}, status=403, status_body=RATE_LIMIT_BODY)
    with pytest.raises(httpx.HTTPStatusError):
        trash_message(FakeService(api), "token", "m1")
