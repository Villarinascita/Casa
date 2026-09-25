from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.bills import dispatch_bill_reminders
from app.models import Bill, ChannelLink, User
from app.security import Ctx  # noqa: F401  (non usato direttamente, ma chiarisce il contesto per chi legge)


def _link_telegram(db, user_id, household_id, chat_id="123"):
    db.add(ChannelLink(household_id=household_id, user_id=user_id, platform="telegram",
                       external_user_id=chat_id, chat_id=chat_id))
    db.commit()


def test_found_reminder_sent_once(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        _link_telegram(db, user.id, seed["Rossi"])
        bill = Bill(household_id=seed["Rossi"], created_by=user.id, category="Bollette",
                    title="Luce", amount=45.5, due_date=date(2026, 10, 10))
        db.add(bill)
        db.commit()

        sent = []
        now = datetime(2026, 9, 25, tzinfo=timezone.utc)
        assert dispatch_bill_reminders(db, lambda chat_id, text: sent.append((chat_id, text)), now) == 1
        assert len(sent) == 1
        assert "Luce" in sent[0][1] and "45.50" in sent[0][1]
        bill = db.scalar(select(Bill))
        assert bill.found_reminder_sent_at == now

        # Un secondo giro non lo rimanda.
        assert dispatch_bill_reminders(db, lambda chat_id, text: sent.append((chat_id, text)), now) == 0
        assert len(sent) == 1


def test_due_soon_reminder_only_within_three_days_and_not_if_paid(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        _link_telegram(db, user.id, seed["Rossi"])
        now = datetime(2026, 9, 25, tzinfo=timezone.utc)
        near = Bill(household_id=seed["Rossi"], created_by=user.id, category="Bollette", title="Vicina",
                    amount=10, due_date=date(2026, 9, 27), found_reminder_sent_at=now)
        far = Bill(household_id=seed["Rossi"], created_by=user.id, category="Bollette", title="Lontana",
                   amount=10, due_date=date(2026, 12, 1), found_reminder_sent_at=now)
        paid = Bill(household_id=seed["Rossi"], created_by=user.id, category="Bollette", title="Pagata",
                   amount=10, due_date=date(2026, 9, 26), found_reminder_sent_at=now, payment_state="pagato")
        db.add_all([near, far, paid])
        db.commit()

        sent = []
        assert dispatch_bill_reminders(db, lambda chat_id, text: sent.append((chat_id, text)), now) == 1
        assert len(sent) == 1 and "Vicina" in sent[0][1]


def test_no_reminder_without_telegram_link_stays_pending(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        bill = Bill(household_id=seed["Rossi"], created_by=user.id, category="Bollette", title="Luce", amount=1)
        db.add(bill)
        db.commit()

        now = datetime(2026, 9, 25, tzinfo=timezone.utc)
        assert dispatch_bill_reminders(db, lambda *a: None, now) == 0
        assert db.scalar(select(Bill)).found_reminder_sent_at is None
