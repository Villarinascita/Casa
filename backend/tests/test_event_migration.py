from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


def test_event_migration_preserves_existing_appointments(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config('alembic.ini')
    command.upgrade(config, '20260927_04')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO households
            (id, name, timezone, locale, settings, created_at, updated_at, version)
            VALUES ('family', 'Test', 'Europe/Rome', 'it-IT', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"""))
        connection.execute(text("""INSERT INTO events
            (id, household_id, title, all_day, start_date, source, created_at, updated_at, version)
            VALUES ('existing', 'family', 'Visita', 1, '2026-09-29', 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"""))
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        row = connection.execute(text('SELECT title, reminder_minutes, series_id FROM events')).one()
        assert tuple(row) == ('Visita', None, None)
    assert 'event_reminder_deliveries' in inspect(engine).get_table_names()
    command.downgrade(config, '20260927_04')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT title FROM events')).scalar_one() == 'Visita'
    assert 'event_reminder_deliveries' not in inspect(engine).get_table_names()
    engine.dispose()
