from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.email_cleanup import TRASH_PERMISSION_MESSAGE, run_domain_cleanups, trash_message
from app.models import EmailDomainCleanup, GoogleConnection, User

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


class FakeApi:
    def __init__(self, pages, senders, status=None):
        self.pages = pages
        self.senders = senders
        self.status = status
        self.trashed = []
        self.list_params = []

    def get(self, url, token, params=None):
        if url.endswith("/messages"):
            self.list_params.append(params)
            return self.pages.pop(0)
        return {"payload": {"headers": [{"name": "From", "value": self.senders[url.rsplit("/", 1)[1]]}]}}

    def post(self, url, token, body):
        if self.status:
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError(str(self.status), request=request,
                                        response=httpx.Response(self.status, request=request))
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
        api = FakeApi([{"messages": [{"id": "m1"}, {"id": "m2"}]}],
                      {"m1": "Promo <a@offerte.news.com>", "m2": "b@notnews.com"})
        assert run_domain_cleanups(db, FakeService(api), NOW) == 1
        row = db.scalar(select(EmailDomainCleanup))
        assert api.trashed == ["m1"]
        assert api.list_params[0]["q"] == "in:inbox from:news.com"
        assert row.status == "done" and row.trashed_count == 1 and row.completed_at == NOW


def test_pulizia_su_piu_giri_usa_il_segnalibro(db_factory, seed):
    with db_factory() as db:
        _cleanup(db, seed)
        api = FakeApi([{"messages": [{"id": "m1"}], "nextPageToken": "p2"}, {"messages": [{"id": "m2"}]}],
                      {"m1": "a@news.com", "m2": "b@news.com"})
        service = FakeService(api)
        run_domain_cleanups(db, service, NOW)
        row = db.scalar(select(EmailDomainCleanup))
        assert row.status == "running" and row.page_token == "p2"
        run_domain_cleanups(db, service, NOW)
        assert api.list_params[1]["pageToken"] == "p2"
        assert row.status == "done" and row.trashed_count == 2


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
