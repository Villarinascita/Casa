import pytest

from app.schemas import BillIn


def create(client, path, payload, **headers):
    response = client.post(f"/api/v1/{path}", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, path, obj, payload):
    return client.patch(f"/api/v1/{path}/{obj['id']}", json=payload, headers={"If-Match": str(obj["version"])})


def test_dati_condivisi_tra_adulti(luca, anna):
    create(luca, "shopping/items", {"label": "Pile", "quantity": "4"})
    items = anna.get("/api/v1/shopping/items").json()
    assert [(i["label"], i["quantity"], i["checked"]) for i in items] == [("Pile", "4", False)]


def test_isolamento_famiglie(luca, marco, seed):
    task = create(luca, "tasks", {"title": "Chiamare il tecnico"})
    assert marco.get("/api/v1/tasks").json() == []
    assert marco.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert patch(marco, "tasks", task, {"title": "x"}).status_code == 404
    # Non si può assegnare un familiare di un'altra famiglia.
    response = marco.post("/api/v1/tasks", json={"title": "x", "member_id": seed["member_Rossi"]})
    assert response.status_code == 422
    assert "member_id" in response.json()["field_errors"]


def test_conflitto_di_versione(luca, anna):
    item = create(luca, "shopping/items", {"label": "Latte"})
    first = patch(luca, "shopping/items", item, {"checked": True})
    assert first.status_code == 200 and first.json()["checked"] and first.json()["version"] == 2
    stale = patch(anna, "shopping/items", item, {"label": "Latte intero"})
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    assert anna.get(f"/api/v1/shopping/items/{item['id']}").json()["label"] == "Latte"


def test_versione_obbligatoria(luca):
    item = create(luca, "tasks", {"title": "x"})
    assert luca.patch(f"/api/v1/tasks/{item['id']}", json={"title": "y"}).status_code == 428


def test_idempotenza(luca):
    first = create(luca, "tasks", {"title": "Prenotare visita"}, **{"Idempotency-Key": "abc"})
    again = create(luca, "tasks", {"title": "Prenotare visita"}, **{"Idempotency-Key": "abc"})
    assert first["id"] == again["id"]
    assert len(luca.get("/api/v1/tasks").json()) == 1
    reused = luca.post("/api/v1/shopping/items", json={"label": "x"}, headers={"Idempotency-Key": "abc"})
    assert reused.status_code == 422


def test_completamento_attivita(luca):
    task = create(luca, "tasks", {"title": "Rinnovare bollo", "due_date": "2026-10-01"})
    done = patch(luca, "tasks", task, {"status": "done"}).json()
    assert done["status"] == "done" and done["completed_at"]
    reopened = patch(luca, "tasks", done, {"status": "open"}).json()
    assert reopened["status"] == "open" and reopened["completed_at"] is None


def test_eliminazione_e_annulla(luca):
    task = create(luca, "tasks", {"title": "x"})
    deleted = luca.delete(f"/api/v1/tasks/{task['id']}", headers={"If-Match": str(task["version"])}).json()
    assert deleted["deleted_at"]
    assert luca.get("/api/v1/tasks").json() == []
    restored = luca.post(f"/api/v1/tasks/{task['id']}/restore", headers={"If-Match": str(deleted["version"])})
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
    assert len(luca.get("/api/v1/tasks").json()) == 1


def test_rinomina_familiare_mantiene_collegamenti(luca, seed):
    member = luca.get("/api/v1/members").json()[0]
    event = create(luca, "events", {"title": "Nuoto", "start_at": "2026-09-14T17:00:00+02:00",
                                    "member_id": member["id"]})
    renamed = patch(luca, "members", member, {"display_name": "Giulia"}).json()
    assert renamed["display_name"] == "Giulia"
    assert luca.get(f"/api/v1/events/{event['id']}").json()["member_id"] == member["id"]
    archived = patch(luca, "members", renamed, {"archived": True}).json()
    assert archived["archived"] is True


def test_evento_tutto_il_giorno_senza_utc(luca):
    event = create(luca, "events", {"title": "Gita", "all_day": True, "start_date": "2026-10-03",
                                    "start_at": "2026-10-03T10:00:00+02:00"})
    assert event["start_date"] == "2026-10-03" and event["start_at"] is None
    listed = luca.get("/api/v1/events", params={"from": "2026-10-03", "to": "2026-10-04"}).json()
    assert [e["id"] for e in listed] == [event["id"]]
    assert luca.get("/api/v1/events", params={"from": "2026-10-04", "to": "2026-10-05"}).json() == []


def test_validazione_evento(luca):
    response = luca.post("/api/v1/events", json={"title": "Senza ora"})
    assert response.status_code == 422
    response = luca.post("/api/v1/events", json={"title": "x", "start_at": "2026-09-14T17:00:00"})
    assert response.status_code == 422
    response = luca.post("/api/v1/events", json={"title": "x", "start_at": "2026-09-14T17:00:00+02:00",
                                                 "end_at": "2026-09-14T16:00:00+02:00"})
    assert response.status_code == 422
    assert "fine" in response.json()["message"]


def test_intervallo_giorni_locali_con_cambio_ora(luca):
    # 29 marzo 2026: in Italia si passa all'ora legale. Il giorno locale va dalle 23:00Z del 28 alle 22:00Z del 29.
    early = create(luca, "events", {"title": "Presto", "start_at": "2026-03-29T00:30:00+01:00"})
    late = create(luca, "events", {"title": "Sera", "start_at": "2026-03-29T23:30:00+02:00"})
    assert late["start_at"] == "2026-03-29T21:30:00Z"
    listed = {e["title"] for e in luca.get("/api/v1/events", params={"from": "2026-03-29", "to": "2026-03-30"}).json()}
    assert listed == {"Presto", "Sera"}
    before = {e["title"] for e in luca.get("/api/v1/events", params={"from": "2026-03-28", "to": "2026-03-29"}).json()}
    assert before == set()
    assert early["start_at"] == "2026-03-28T23:30:00Z"


def test_modifica_evento_passaggio_a_tutto_il_giorno(luca):
    event = create(luca, "events", {"title": "Saggio", "start_at": "2026-12-20T18:00:00+01:00"})
    changed = patch(luca, "events", event, {"all_day": True, "start_date": "2026-12-20"}).json()
    assert changed["all_day"] and changed["start_at"] is None and changed["start_date"] == "2026-12-20"


def test_svuota_spuntati(luca):
    kept = create(luca, "shopping/items", {"label": "Pane"})
    done = create(luca, "shopping/items", {"label": "Latte"})
    patch(luca, "shopping/items", done, {"checked": True})
    cleared = luca.post("/api/v1/shopping/items/clear-checked").json()
    assert [i["label"] for i in cleared] == ["Latte"]
    assert [i["id"] for i in luca.get("/api/v1/shopping/items").json()] == [kept["id"]]


def test_aree_famiglia(luca):
    household = luca.get("/api/v1/household").json()
    updated = luca.patch("/api/v1/household", json={"areas": ["Auto", "Animali", "Auto"]},
                         headers={"If-Match": str(household["version"])}).json()
    assert updated["areas"] == ["Auto", "Animali"]


def test_import_prototipo(luca):
    legacy = {
        "members": ["Papà", "Mamma Rossi", "Nonna materna"],
        "areas": ["Documenti"],
        "items": [
            {"type": "event", "title": "Nuoto", "date": "2026-09-15", "time": "17:30", "person": "Mamma Rossi",
             "note": "piscina comunale", "done": False, "id": "1"},
            {"type": "event", "title": "Senza data", "date": "", "time": "", "person": "", "note": ""},
            {"type": "task", "title": "Chiamare idraulico", "date": "", "time": "", "person": "Papà", "done": True},
            {"type": "shopping", "title": "Pile", "date": "", "time": "", "person": "", "done": False},
        ],
    }
    result = luca.post("/api/v1/import/local", json=legacy, headers={"Idempotency-Key": "import-1"})
    assert result.status_code == 201, result.text
    body = result.json()
    assert body == {"members_created": 2, "events": 1, "tasks": 1, "shopping": 1, "skipped": ["Senza data"]}
    again = luca.post("/api/v1/import/local", json=legacy, headers={"Idempotency-Key": "import-1"}).json()
    assert again == body
    members = {m["display_name"]: m["id"] for m in luca.get("/api/v1/members").json()}
    event = luca.get("/api/v1/events").json()[0]
    assert event["start_at"] == "2026-09-15T15:30:00Z"
    assert event["member_id"] == members["Mamma Rossi"] and event["location"] == "piscina comunale"
    assert luca.get("/api/v1/tasks").json()[0]["status"] == "done"
    assert "Documenti" in luca.get("/api/v1/household").json()["areas"]


from app.models import Bill


def test_bill_default_state_and_constraint(luca, db_factory, seed):
    with db_factory() as db:
        bill = Bill(household_id=seed["Rossi"], created_by=None, category="Bollette",
                    title="Bolletta luce", amount=None)
        db.add(bill)
        db.commit()
        assert bill.payment_state == "da_pagare"
        assert bill.currency == "EUR"


def test_bill_schema_rejects_negative_amount():
    with pytest.raises(Exception):
        BillIn(category="Bollette", title="x", amount=-1)


def test_bollette_crud_e_stato_pagamento(luca):
    bill = create(luca, "bills", {"category": "Bollette", "title": "Luce", "amount": "45.50",
                                  "due_date": "2026-10-10"})
    assert bill["payment_state"] == "da_pagare"
    assert bill["currency"] == "EUR"
    paid = patch(luca, "bills", bill, {"payment_state": "pagato"}).json()
    assert paid["payment_state"] == "pagato"
    assert len(luca.get("/api/v1/bills").json()) == 1
    deleted = luca.delete(f"/api/v1/bills/{bill['id']}", headers={"If-Match": str(paid["version"])})
    assert deleted.status_code == 200
    assert luca.get("/api/v1/bills").json() == []


def test_bill_categories_famiglia(luca):
    household = luca.get("/api/v1/household").json()
    assert household["bill_categories"] == ["Bollette", "Auto e assicurazione", "Altro"]
    updated = luca.patch("/api/v1/household", json={"bill_categories": ["Bollette", "Salute", "Bollette"]},
                         headers={"If-Match": str(household["version"])}).json()
    assert updated["bill_categories"] == ["Bollette", "Salute"]


def test_domini_bloccati_normalizzati(luca):
    household = luca.get("/api/v1/household").json()
    assert household["blocked_email_domains"] == []
    updated = luca.patch("/api/v1/household",
                         json={"blocked_email_domains": [" Newsletter.COM ", "newsletter.com"]},
                         headers={"If-Match": str(household["version"])})
    assert updated.status_code == 200, updated.text
    assert updated.json()["blocked_email_domains"] == ["newsletter.com"]


def test_domini_bloccati_rifiuta_valori_non_validi(luca):
    household = luca.get("/api/v1/household").json()
    for bad in ["tizio@gmail.com", "localhost", "news letter.com"]:
        response = luca.patch("/api/v1/household", json={"blocked_email_domains": [bad]},
                              headers={"If-Match": str(household["version"])})
        assert response.status_code == 422, bad
