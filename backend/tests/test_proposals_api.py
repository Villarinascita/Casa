from datetime import timedelta

from sqlalchemy import select

from app.models import AuditEntry, GoogleConnection, Proposal, User, utcnow


def _proposals(db_factory, seed, specs):
    """specs: (famiglia, giorni fa, stato). Ritorna gli id nell'ordine."""
    ids = []
    with db_factory() as db:
        connections = {}
        for household, login in (("Rossi", "luca"), ("Bianchi", "marco")):
            user = db.scalar(select(User).where(User.login == login))
            connection = GoogleConnection(household_id=seed[household], user_id=user.id,
                                          email=f"{login}@gmail.com", refresh_token_encrypted="x")
            db.add(connection)
            db.flush()
            connections[household] = (connection, user)
        for index, (household, days_ago, status) in enumerate(specs):
            connection, user = connections[household]
            proposal = Proposal(household_id=seed[household], created_by=user.id, connection_id=connection.id,
                                message_id=f"m{index}", thread_id="t", item_index=0, kind="shopping",
                                data={"label": f"Voce {index}"}, status=status,
                                created_at=utcnow() - timedelta(days=days_ago))
            db.add(proposal)
            db.flush()
            ids.append(proposal.id)
        db.commit()
    return ids


def test_elenco_filtrato_per_stato(luca, db_factory, seed):
    pending, accepted = _proposals(db_factory, seed, [("Rossi", 1, "pending"), ("Rossi", 1, "accepted")])
    assert [p["id"] for p in luca.get("/api/v1/proposals?status=pending").json()] == [pending]
    assert {p["id"] for p in luca.get("/api/v1/proposals").json()} == {pending, accepted}


def test_riepilogo_conta_solo_la_famiglia(luca, db_factory, seed):
    _proposals(db_factory, seed, [("Rossi", 1, "pending"), ("Rossi", 40, "pending"), ("Rossi", 50, "rejected"),
                                  ("Bianchi", 60, "pending")])
    assert luca.get("/api/v1/proposals/summary").json() == {"pending": 2, "stale": 1}


def test_ignora_le_piu_vecchie(luca, marco, db_factory, seed):
    recent, old, old_accepted, other = _proposals(
        db_factory, seed, [("Rossi", 5, "pending"), ("Rossi", 31, "pending"), ("Rossi", 45, "accepted"),
                           ("Bianchi", 60, "pending")])
    response = luca.post("/api/v1/proposals/reject-stale", json={"days": 30})
    assert response.status_code == 200, response.text
    assert response.json() == {"rejected": 1}
    with db_factory() as db:
        status = {p.id: p.status for p in db.scalars(select(Proposal))}
        assert status == {recent: "pending", old: "rejected", old_accepted: "accepted", other: "pending"}
        entry = db.scalar(select(AuditEntry).where(AuditEntry.entity_id == old))
        assert entry.changed_fields == {"status": "rejected", "bulk": True}
    assert luca.get("/api/v1/proposals/summary").json() == {"pending": 1, "stale": 0}


def test_ignora_le_piu_vecchie_rifiuta_soglie_troppo_basse(luca, seed):
    assert luca.post("/api/v1/proposals/reject-stale", json={"days": 3}).status_code == 422
