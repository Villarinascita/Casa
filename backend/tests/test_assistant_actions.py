def test_action_batch_creates_distinct_resources_once(luca):
    body = {"actions": [
        {"kind": "task", "data": {"title": "Borsa palestra", "remind_at": "2026-09-29T18:00:00+02:00"}},
        {"kind": "shopping", "data": {"label": "Latte"}},
    ]}
    headers = {"Idempotency-Key": "telegram-msg-1"}
    first = luca.post("/api/v1/assistant/actions", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert [item["kind"] for item in first.json()["created"]] == ["task", "shopping"]
    second = luca.post("/api/v1/assistant/actions", json=body, headers=headers)
    assert second.json() == first.json()
    assert len(luca.get("/api/v1/tasks").json()) == 1
    assert len(luca.get("/api/v1/shopping/items").json()) == 1


def test_invalid_action_does_not_save_partial_batch(luca):
    response = luca.post("/api/v1/assistant/actions", json={"actions": [
        {"kind": "shopping", "data": {"label": "Pane"}},
        {"kind": "event", "data": {"title": "Senza data"}},
    ]})
    assert response.status_code == 422
    assert luca.get("/api/v1/shopping/items").json() == []


def test_action_batch_rejects_member_from_another_household(luca, seed):
    response = luca.post("/api/v1/assistant/actions", json={"actions": [
        {"kind": "task", "data": {"title": "Visita", "member_id": seed["member_Bianchi"]}},
    ]})
    assert response.status_code == 422
    assert luca.get("/api/v1/tasks").json() == []
