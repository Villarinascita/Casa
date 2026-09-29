from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import ChannelLink, Event, User


def series(luca, **changes):
    return luca.post('/api/v1/events/recurring', json={
        'title': 'Nuoto', 'start_at': '2026-03-24T18:00:00+01:00',
        'end_at': '2026-03-24T19:00:00+01:00',
        'repeat': 'weekly', 'repeat_until': '2026-04-07', 'reminder_minutes': 60,
        **changes,
    }, headers={'Idempotency-Key': 'nuoto-series'})


def test_weekly_series_is_atomic_idempotent_and_preserves_local_times(luca, marco):
    response = series(luca)
    assert response.status_code == 201, response.text
    assert series(luca).json() == response.json()
    events = luca.get('/api/v1/events').json()
    assert [e['start_at'] for e in events] == [
        '2026-03-24T17:00:00Z', '2026-03-31T16:00:00Z', '2026-04-07T16:00:00Z']
    assert [e['end_at'] for e in events] == [
        '2026-03-24T18:00:00Z', '2026-03-31T17:00:00Z', '2026-04-07T17:00:00Z']
    assert len({e['series_id'] for e in events}) == 1
    assert events[0]['series_id']
    assert all(e['reminder_minutes'] == 60 for e in events)
    assert marco.get('/api/v1/events').json() == []
    middle = events[1]
    edited = luca.patch(f"/api/v1/events/{middle['id']}", json={'title': 'Nuoto spostato'},
                       headers={'If-Match': str(middle['version'])})
    assert edited.status_code == 200
    assert [e['title'] for e in luca.get('/api/v1/events').json()] == ['Nuoto', 'Nuoto spostato', 'Nuoto']


def test_monthly_all_day_series_keeps_original_day_after_february(luca):
    response = series(luca, all_day=True, start_date='2028-01-31', end_date='2028-02-01',
                      repeat='monthly', repeat_until='2028-03-31')
    assert response.status_code == 201, response.text
    events = luca.get('/api/v1/events').json()
    assert [e['start_date'] for e in events] == ['2028-01-31', '2028-02-29', '2028-03-31']
    assert [e['end_date'] for e in events] == ['2028-02-01', '2028-03-01', '2028-04-01']


@pytest.mark.parametrize('changes', [
    {'repeat_until': '2026-03-23'}, {'repeat_until': None}, {'repeat': 'yearly'},
    {'repeat': 'daily', 'repeat_until': '2030-01-01'}, {'reminder_minutes': -1},
    {'member_id': 'missing-member'},
])
def test_invalid_series_does_not_create_any_events(luca, changes):
    assert series(luca, **changes).status_code == 422
    assert luca.get('/api/v1/events').json() == []


def test_daily_series_uses_household_date_near_midnight(luca):
    response = series(luca, start_at='2026-09-29T00:30:00+02:00', end_at=None,
                      repeat='daily', repeat_until='2026-09-30')
    assert response.status_code == 201, response.text
    assert [e['start_at'] for e in luca.get('/api/v1/events').json()] == [
        '2026-09-28T22:30:00Z', '2026-09-29T22:30:00Z']


def test_invalid_interval_on_dst_transition_returns_validation_error(luca):
    response = series(luca, start_at='2026-03-22T02:30:00+01:00',
                      end_at='2026-03-22T03:00:00+01:00', repeat_until='2026-03-29')
    assert response.status_code == 422
    assert luca.get('/api/v1/events').json() == []


def test_event_reminder_queued_once_retries_and_cancels_after_edit(luca, db_factory):
    response = luca.post('/api/v1/events', json={
        'title': 'Pediatra', 'start_at': '2026-09-29T18:00:00+02:00', 'reminder_minutes': 60})
    assert response.status_code == 201, response.text
    from app.event_reminders import enqueue_due, dispatch_pending
    from app.models import EventReminderDelivery
    event = response.json()
    now = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == 'luca'))
        db.add(ChannelLink(household_id=db.get(Event, event['id']).household_id,
                           user_id=user.id, platform='telegram', external_user_id='event123', chat_id='123'))
        db.commit()
        assert enqueue_due(db, now) == 1
        assert enqueue_due(db, now) == 0
        def fail(chat, text):
            raise OSError('temporarily unavailable')
        assert dispatch_pending(db, fail, now) == 0
        delivery = db.scalar(select(EventReminderDelivery))
        assert delivery.attempts == 1 and delivery.status == 'pending'
        sent = []
        assert dispatch_pending(db, lambda chat, text: sent.append((chat, text)), now) == 1
        assert dispatch_pending(db, lambda *args: sent.append(args), now) == 0
        assert sent[0][0] == '123' and 'Pediatra' in sent[0][1] and '18:00' in sent[0][1]


@pytest.mark.parametrize('change', [{'reminder_minutes': None}, {'start_at': '2026-09-30T18:00:00+02:00'}, 'delete'])
def test_pending_reminder_is_not_sent_after_event_changes(luca, db_factory, change):
    response = luca.post('/api/v1/events', json={
        'title': 'Pediatra', 'start_at': '2026-09-29T18:00:00+02:00', 'reminder_minutes': 60})
    assert response.status_code == 201, response.text
    from app.event_reminders import enqueue_due, dispatch_pending
    from app.models import EventReminderDelivery
    event = response.json()
    now = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
    with db_factory() as db:
        assert enqueue_due(db, now) == 1
    headers = {'If-Match': str(event['version'])}
    if change == 'delete':
        assert luca.delete(f"/api/v1/events/{event['id']}", headers=headers).status_code == 200
    else:
        assert luca.patch(f"/api/v1/events/{event['id']}", json=change, headers=headers).status_code == 200
    with db_factory() as db:
        sent = []
        assert dispatch_pending(db, lambda *args: sent.append(args), now) == 0
        assert sent == []
        assert db.scalar(select(EventReminderDelivery)).status == 'cancelled'


def test_all_day_reminder_uses_nine_am_in_household_timezone(luca, db_factory):
    response = luca.post('/api/v1/events', json={
        'title': 'Gita', 'all_day': True, 'start_date': '2026-09-29', 'reminder_minutes': 1440})
    assert response.status_code == 201, response.text
    from app.event_reminders import enqueue_due
    with db_factory() as db:
        assert enqueue_due(db, datetime(2026, 9, 28, 6, 59, tzinfo=timezone.utc)) == 0
        assert enqueue_due(db, datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)) == 1
        assert enqueue_due(db, datetime(2026, 9, 28, 7, 1, tzinfo=timezone.utc)) == 0
