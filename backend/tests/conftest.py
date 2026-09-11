import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db, make_engine
from app.main import app
from app.models import Household, HouseholdUser, Member, User
from app.security import hash_password, login_limiter

PASSWORD = "password-di-prova"


@pytest.fixture
def db_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    login_limiter.failures.clear()
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def seed(db_factory):
    """Due famiglie: «rossi» con due adulti, «bianchi» con un adulto."""
    with db_factory() as db:
        ids = {}
        for name, logins in (("Rossi", ["luca", "anna"]), ("Bianchi", ["marco"])):
            household = Household(name=name, settings={"areas": ["Auto"]})
            db.add(household)
            db.flush()
            ids[name] = household.id
            member = Member(household_id=household.id, display_name=f"Mamma {name}")
            db.add(member)
            for login in logins:
                user = User(login=login, password_hash=hash_password(PASSWORD))
                db.add(user)
                db.flush()
                db.add(HouseholdUser(household_id=household.id, user_id=user.id, role="admin"))
            db.flush()
            ids[f"member_{name}"] = member.id
        db.commit()
    return ids


def make_client(login: str | None = None) -> TestClient:
    client = TestClient(app, base_url="http://testserver", headers={"X-Requested-With": "insieme"})
    if login:
        response = client.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})
        assert response.status_code == 200, response.text
    return client


@pytest.fixture
def luca(seed):
    return make_client("luca")


@pytest.fixture
def anna(seed):
    return make_client("anna")


@pytest.fixture
def marco(seed):
    return make_client("marco")
