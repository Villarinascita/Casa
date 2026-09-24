from datetime import datetime, timezone

from sqlalchemy import select

from app.models import ChannelLink, ReminderDelivery, Task, User
from app.reminders import advance_local, dispatch_pending, enqueue_due


def test_weekly_reminder_preserves_local_hour_across_dst():
    before = datetime(2026, 3, 24, 17, 0, tzinfo=timezone.utc)  # 18:00 Europe/Rome
    assert advance_local(before, "weekly", "Europe/Rome") == datetime(
        2026, 3, 31, 16, 0, tzinfo=timezone.utc
    )


def test_task_can_have_recurring_reminder(luca):
    response = luca.post("/api/v1/tasks", json={
        "title": "Preparare la borsa", "remind_at": "2026-09-29T17:00:00+02:00",
        "repeat": "weekly",
    })
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["remind_at"] == "2026-09-29T15:00:00Z"
    assert task["repeat"] == "weekly"


def test_recurring_reminder_requires_time(luca):
    response = luca.post("/api/v1/tasks", json={"title": "Borsa", "repeat": "weekly"})
    assert response.status_code == 422


def test_due_reminder_is_queued_once_and_weekly_task_moves_forward(luca, db_factory):
    task = luca.post("/api/v1/tasks", json={
        "title": "Preparare la borsa", "remind_at": "2026-03-24T18:00:00+01:00",
        "repeat": "weekly",
    }).json()
    at = datetime(2026, 3, 24, 17, 1, tzinfo=timezone.utc)
    with db_factory() as db:
        assert enqueue_due(db, at) == 1
        assert enqueue_due(db, at) == 0
        delivery = db.scalar(select(ReminderDelivery))
        saved = db.get(Task, task["id"])
        assert delivery.task_id == task["id"]
        assert delivery.scheduled_at == datetime(2026, 3, 24, 17, tzinfo=timezone.utc)
        assert saved.remind_at == datetime(2026, 3, 31, 16, tzinfo=timezone.utc)


def test_failed_delivery_is_retryable_and_success_is_not_resent(luca, db_factory):
    task = luca.post("/api/v1/tasks", json={
        "title": "Preparare la borsa", "remind_at": "2026-09-29T17:00:00+02:00",
    }).json()
    at = datetime(2026, 9, 29, 15, 1, tzinfo=timezone.utc)
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        db.add(ChannelLink(household_id=task["household_id"] if "household_id" in task else
                           db.get(Task, task["id"]).household_id,
                           user_id=user.id, platform="telegram", external_user_id="123", chat_id="123"))
        db.commit()
        enqueue_due(db, at)
        calls = []

        def fail(chat_id, message):
            calls.append((chat_id, message))
            raise OSError("temporarily unavailable")

        assert dispatch_pending(db, fail, at) == 0
        delivery = db.scalar(select(ReminderDelivery))
        assert delivery.status == "pending" and delivery.attempts == 1

        assert dispatch_pending(db, lambda chat_id, message: calls.append((chat_id, message)), at) == 1
        assert dispatch_pending(db, lambda chat_id, message: calls.append((chat_id, message)), at) == 0
        assert len(calls) == 2
        assert delivery.status == "sent"
