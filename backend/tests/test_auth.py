from fastapi.testclient import TestClient

from app.main import app
from conftest import PASSWORD, make_client


def test_senza_sessione_401(seed):
    response = make_client().get("/api/v1/events")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthenticated"
    assert body["request_id"]


def test_login_me_logout(seed):
    client = make_client("luca")
    me = client.get("/api/v1/me").json()
    assert me["login"] == "luca"
    assert me["household"]["name"] == "Rossi"
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_cookie_httponly_samesite(seed):
    response = make_client().post("/api/v1/auth/login", json={"login": "luca", "password": PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_password_errata(seed):
    response = make_client().post("/api/v1/auth/login", json={"login": "luca", "password": "sbagliata"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_limite_tentativi(seed):
    client = make_client()
    for _ in range(8):
        client.post("/api/v1/auth/login", json={"login": "luca", "password": "sbagliata"})
    response = client.post("/api/v1/auth/login", json={"login": "luca", "password": PASSWORD})
    assert response.status_code == 429


def test_csrf_header_obbligatorio(seed):
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"login": "luca", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["code"] == "csrf"


def test_csrf_origine_estranea(luca):
    response = luca.post("/api/v1/tasks", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    same = luca.post("/api/v1/tasks", json={"title": "x"}, headers={"Origin": "http://testserver"})
    assert same.status_code == 201


def test_api_inesistente_json(luca):
    response = luca.get("/api/v1/non-esiste")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_cambio_password(luca):
    from tests.conftest import PASSWORD, make_client
    wrong = luca.post("/api/v1/auth/password", json={"current": "sbagliata", "new": "nuova-password-lunga"})
    assert wrong.status_code == 400
    short = luca.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "corta"})
    assert short.status_code == 422
    assert luca.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "nuova-password-lunga"}).status_code == 204
    fresh = make_client()
    assert fresh.post("/api/v1/auth/login", json={"login": "luca", "password": PASSWORD}).status_code == 401
    assert fresh.post("/api/v1/auth/login", json={"login": "luca", "password": "nuova-password-lunga"}).status_code == 200
