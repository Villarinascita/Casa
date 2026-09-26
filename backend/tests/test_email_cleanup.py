import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.email_cleanup import TRASH_PERMISSION_MESSAGE, TrashNotPermitted, run_domain_cleanups, trash_message
from app.models import EmailDomainCleanup, GoogleConnection, User

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


INSUFFICIENT_PERMISSIONS_BODY = {
    "error": {"errors": [{"reason": "insufficientPermissions"}]},
}
RATE_LIMIT_BODY = {
    "error": {"status": "PERMISSION_DENIED", "errors": [{"reason": "rateLimitExceeded", "message": "limite"}]},
}


class FakeApi:
    def __init__(self, pages, senders, status=None, status_body=None, fail_on=(), trash_fail=None,
                 empty_body=False):
        self.pages = pages
        self.senders = senders
        self.status = status
        self.status_body = status_body if status_body is not None else INSUFFICIENT_PERMISSIONS_BODY
        self.empty_body = empty_body
        self.fail_on = set(fail_on)
        self.trash_fail = dict(trash_fail or {})  # message_id -> (status, body|None)
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

    def _raise_status(self, url, status, body):
        request = httpx.Request("POST", url)
        content = json.dumps(body).encode() if body is not None else b""
        raise httpx.HTTPStatusError(str(status), request=request,
                                    response=httpx.Response(status, request=request, content=content))

    def post(self, url, token, body):
        message_id = url.rsplit("/", 2)[1]
        if message_id in self.trash_fail:
            status, fail_body = self.trash_fail[message_id]
            self._raise_status(url, status, fail_body)
        if self.status:
            fail_body = None if self.empty_body else self.status_body
            self._raise_status(url, self.status, fail_body)
        self.trashed.append(message_id)
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
    assert trash_message(FakeService(FakeApi([], {}, status=404)), "token", "m1") is False


def test_404_non_conta_come_trashed_e_permette_di_completare(db_factory, seed):
    """spec #2: un 404 (email già sparita) non conta come trashed né come fallimento;
    la pulizia può comunque concludersi se non ci sono altre pagine."""
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}]}], {"m1": "a@news.com"}, trash_fail={"m1": (404, None)})
        assert run_domain_cleanups(db, FakeService(api), NOW) == 0
        row = db.scalar(select(EmailDomainCleanup))
        assert row.trashed_count == 0
        assert row.status == "done" and row.completed_at == NOW


def test_errore_transitorio_sullultima_pagina_non_segna_fatta(db_factory, seed):
    """spec #1: un errore transitorio (5xx/429) sull'unico messaggio di una pagina senza
    nextPageToken non deve marcare la pulizia come conclusa né far seguire il segnalibro:
    la riga resta "running" con page_token invariato, e un giro successivo che riesce
    completa normalmente."""
    with db_factory() as db:
        _cleanup(db, seed)
        request = httpx.Request("POST", "https://gmail.googleapis.com/x")
        error = httpx.HTTPStatusError("503", request=request,
                                      response=httpx.Response(503, request=request))
        api = FakeApi([{"messages": [{"id": "m1"}]}], {"m1": "a@news.com"})

        original_post = api.post
        calls = {"n": 0}

        def flaky_post(url, token, body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise error
            return original_post(url, token, body)

        api.post = flaky_post
        assert run_domain_cleanups(db, FakeService(api), NOW) == 0
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token is None and row.trashed_count == 0

        api.pages.append({"messages": [{"id": "m1"}]})
        assert run_domain_cleanups(db, FakeService(api), NOW) == 1
        assert "pageToken" not in api.list_params[1]
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token is None and row.trashed_count == 1


def test_permesso_negato_dopo_alcuni_trashed_riparte_dallinizio(db_factory, seed):
    """spec #3: se TrashNotPermitted arriva dopo che la pagina aveva già spostato email,
    si rispetta comunque la regola "trashed >= 1 -> riparte dall'inizio" (page_token=None)."""
    with db_factory() as db:
        connection = _cleanup(db, seed)
        row = db.scalar(select(EmailDomainCleanup))
        row.page_token = "p1"  # pulizia già a metà paginazione prima di questo giro
        db.commit()
        api = FakeApi([{"messages": [{"id": "m1"}, {"id": "m2"}]}],
                      {"m1": "a@news.com", "m2": "b@news.com"},
                      trash_fail={"m2": (403, INSUFFICIENT_PERMISSIONS_BODY)})
        assert run_domain_cleanups(db, FakeService(api), NOW) == 1
        row = db.scalar(select(EmailDomainCleanup))
        assert api.trashed == ["m1"]
        assert row.status == "running" and row.trashed_count == 1 and row.page_token is None
        assert db.get(GoogleConnection, connection.id).last_error == TRASH_PERMISSION_MESSAGE


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
    """Un 403 di rate limit (rateLimitExceeded, anche con status PERMISSION_DENIED nel corpo)
    non è un permesso mancante: va ritentato, non convertito in TrashNotPermitted."""
    api = FakeApi([], {}, status=403, status_body=RATE_LIMIT_BODY)
    with pytest.raises(httpx.HTTPStatusError):
        trash_message(FakeService(api), "token", "m1")


def test_403_con_corpo_non_interpretabile_diventa_permesso_mancante():
    """Un 403 con corpo vuoto/non-JSON è imparseable: per prudenza si tratta come permesso
    mancante (TrashNotPermitted), non come rate limit."""
    api = FakeApi([], {}, status=403, empty_body=True)
    with pytest.raises(TrashNotPermitted):
        trash_message(FakeService(api), "token", "m1")


def test_pagina_con_errore_non_segue_il_segnalibro_al_primo_giro(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}], "nextPageToken": "p2"}], {}, fail_on={"m1"})
        run_domain_cleanups(db, FakeService(api), NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token is None and row.failed_runs == 1


def test_messaggio_sempre_in_errore_fa_saltare_la_pagina_dopo_tre_giri(db_factory, seed):
    """Un messaggio che fallisce a ogni giro non deve bloccare la pulizia delle pagine successive."""
    with db_factory() as db:
        _cleanup(db, seed)
        failing_page = {"messages": [{"id": "m1"}], "nextPageToken": "p2"}
        api = FakeApi([dict(failing_page) for _ in range(3)] + [{"messages": [{"id": "m2"}]}],
                      {"m2": "b@news.com"}, fail_on={"m1"})
        service = FakeService(api)
        for expected_failures in (1, 2):
            run_domain_cleanups(db, service, NOW)
            row = db.scalar(select(EmailDomainCleanup))
            assert row.status == "running" and row.page_token is None and row.failed_runs == expected_failures
        run_domain_cleanups(db, service, NOW)
        assert row.page_token == "p2" and row.failed_runs == 0
        assert run_domain_cleanups(db, service, NOW) == 1
        assert api.list_params[3]["pageToken"] == "p2" and api.trashed == ["m2"]


def test_messaggio_sempre_in_errore_sullultima_pagina_chiude_la_pulizia(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}]} for _ in range(3)], {}, fail_on={"m1"})
        service = FakeService(api)
        for _ in range(3):
            run_domain_cleanups(db, service, NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "done" and row.completed_at == NOW and row.trashed_count == 0


def test_un_progresso_azzera_i_giri_falliti(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}]}, {"messages": [{"id": "m1"}, {"id": "m2"}]}],
                      {"m2": "b@news.com"}, fail_on={"m1"})
        service = FakeService(api)
        run_domain_cleanups(db, service, NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.failed_runs == 1
        run_domain_cleanups(db, service, NOW)
        assert row.failed_runs == 0 and row.trashed_count == 1 and row.status == "running"
