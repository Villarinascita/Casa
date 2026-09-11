from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Configurazione letta da variabili d'ambiente INSIEME_* o da backend/.env."""

    model_config = SettingsConfigDict(env_prefix="INSIEME_", env_file=BACKEND_DIR / ".env")

    database_url: str = f"sqlite:///{(ROOT_DIR / 'data' / 'insieme.db').as_posix()}"
    frontend_dir: Path = ROOT_DIR / "frontend"
    session_days: int = 30
    # Da attivare quando l'app è servita in HTTPS (reverse proxy sul NAS).
    cookie_secure: bool = False
    # Origini aggiuntive ammesse per le richieste che modificano dati (es. dominio del reverse proxy).
    allowed_origins: list[str] = []


settings = Settings()
