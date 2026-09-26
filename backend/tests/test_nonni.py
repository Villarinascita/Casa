from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Event, Household, Member, Task, UserSession
from tests.conftest import make_client


def _nonna(db_factory, seed):
    with db_factory() as db:
        nonna = Member(household_id=seed["Rossi"], display_name="Nonna Anna", relation="nonna")
        db.add(nonna)
        db.flush()
        household = db.get(Household, seed["Rossi"])
        household.settings = {**household.settings, "grandparent_members": [nonna.id]}
        monday = date.today() - timedelta(days=date.today().weekday())
        start = datetime.combine(monday + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=14, minutes=30)
        db.add(Event(household_id=seed["Rossi"], title="Prendere Matilde a ginnastica", start_at=start,
                     location="Palestra Nazareno", member_id=nonna.id))
        db.add(Event(household_id=seed["Rossi"], title="Riunione di Luca", start_at=start))  # non è dei nonni
        db.add(Task(household_id=seed["Rossi"], title="Portare il cambio all'asilo", due_date=monday + timedelta(days=3),
                    member_id=nonna.id))
        db.commit()
        return nonna.id, monday


def _login_nonna(luca):
    created = luca.post("/api/v1/household/users", json={"login": " Nonna.Anna "})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["login"] == "nonna.anna" and len(body["password"]) == 14
    client = make_client()
    logged = client.post("/api/v1/auth/login", json={"login": "nonna.anna", "password": body["password"]})
    assert logged.status_code == 200 and logged.json()["role"] == "nonno"
    return client, body


def test_la_nonna_vede_solo_la_sua_settimana(luca, db_factory, seed):
    _, monday = _nonna(db_factory, seed)
    client, _ = _login_nonna(luca)
    week = client.get("/api/v1/nonni/week").json()
    assert week["start"] == monday.isoformat() and week["who"] == ["Nonna Anna"]
    tuesday, thursday = week["days"][1], week["days"][3]
    assert tuesday["name"] == "Martedì"
    assert [i["title"] for i in tuesday["items"]] == ["Prendere Matilde a ginnastica"]
    assert tuesday["items"][0]["place"] == "Palestra Nazareno" and tuesday["items"][0]["time"]
    assert [i["title"] for i in thursday["items"]] == ["Portare il cambio all'asilo"]
    next_week = client.get(f"/api/v1/nonni/week?start={(monday + timedelta(days=7)).isoformat()}").json()
    assert all(not d["items"] for d in next_week["days"])


def test_la_nonna_non_vede_nient_altro(luca, db_factory, seed):
    _nonna(db_factory, seed)
    client, _ = _login_nonna(luca)
    for path in ("/api/v1/events", "/api/v1/bills", "/api/v1/household", "/api/v1/proposals", "/api/v1/household/users"):
        assert client.get(path).status_code == 403, path
    assert client.post("/api/v1/tasks", json={"title": "x"}).status_code == 403
    assert client.get("/api/v1/me").status_code == 200


def test_accesso_ricordato_sei_mesi(luca, db_factory, seed):
    _login_nonna(luca)
    with db_factory() as db:
        sessions = db.scalars(select(UserSession)).all()
        longest = max(s.expires_at for s in sessions)
        assert longest - datetime.now(timezone.utc) > timedelta(days=170)


def test_solo_l_amministratore_gestisce_gli_accessi(luca, anna, marco, db_factory, seed):
    with db_factory() as db:
        from app.models import HouseholdUser, User
        anna_id = db.scalar(select(User.id).where(User.login == "anna"))
        db.get(HouseholdUser, (seed["Rossi"], anna_id)).role = "adult"
        db.commit()
    assert anna.post("/api/v1/household/users", json={"login": "nonno.piero"}).status_code == 403
    assert luca.post("/api/v1/household/users", json={"login": "luca"}).status_code == 409
    assert luca.post("/api/v1/household/users", json={"login": "nonno piero!"}).status_code == 422


def test_nuova_password_chiude_gli_accessi_aperti(luca, db_factory, seed):
    client, body = _login_nonna(luca)
    reset = luca.post(f"/api/v1/household/users/{body['id']}/password")
    assert reset.status_code == 200 and reset.json()["password"] != body["password"]
    assert client.get("/api/v1/me").status_code == 401
    users = luca.get("/api/v1/household/users").json()
    assert {"login": "nonna.anna", "role": "nonno"}.items() <= next(u for u in users if u["login"] == "nonna.anna").items()


def test_impostazione_dei_nonni(luca, db_factory, seed):
    household = luca.get("/api/v1/household").json()
    assert household["grandparent_members"] == []
    member = seed["member_Rossi"]
    updated = luca.patch("/api/v1/household", json={"grandparent_members": [member]},
                         headers={"If-Match": str(household["version"])})
    assert updated.status_code == 200 and updated.json()["grandparent_members"] == [member]
