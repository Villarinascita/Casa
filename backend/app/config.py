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
    telegram_bot_token: str = ""
    hermes_url: str = ""
    hermes_api_key: str = ""
    hermes_model: str = "insieme"
    hermes_email_url: str = ""
    hermes_email_api_key: str = ""
    hermes_email_model: str = "insieme-email"
    stt_url: str = ""
    stt_api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"
    public_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_token_key: str = ""


settings = Settings()
