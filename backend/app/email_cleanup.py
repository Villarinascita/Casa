"""Pulizia retroattiva delle email dei domini bloccati (cestino Gmail, mai cancellazione)."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EmailDomainCleanup, GoogleConnection, utcnow


def queue_domain_cleanups(db: Session, household_id: str, previous: Iterable[str], current: Iterable[str]) -> None:
    """Avvia una pulizia per ogni dominio appena aggiunto; chiude quelle dei domini tolti."""
    previous, current = set(previous), set(current)
    connections = db.scalars(select(GoogleConnection).where(GoogleConnection.household_id == household_id)).all()
    for domain in sorted(current - previous):
        for connection in connections:
            db.add(EmailDomainCleanup(household_id=household_id, connection_id=connection.id, domain=domain))
    removed = previous - current
    if removed:
        for row in db.scalars(select(EmailDomainCleanup).where(
                EmailDomainCleanup.household_id == household_id, EmailDomainCleanup.status == "running",
                EmailDomainCleanup.domain.in_(removed))).all():
            row.status = "done"
            row.completed_at = utcnow()
