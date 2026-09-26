"""Password, sessioni con cookie HttpOnly, protezione CSRF e limite ai tentativi di accesso."""

import hashlib
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .errors import ApiError, error_body
from .models import HouseholdUser, User, UserSession, utcnow

COOKIE_NAME = "insieme_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "insieme"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

hasher = PasswordHasher()
_DUMMY_HASH = hasher.hash("password-inesistente")


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(user: User | None, password: str) -> bool:
    if user is None:
        # Stesso costo computazionale anche per utenti inesistenti.
        try:
            hasher.verify(_DUMMY_HASH, password)
        except VerifyMismatchError:
            pass
        return False
    try:
        return hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Ctx:
    user_id: str
    login: str
    household_id: str
    role: str


# I nonni non devono rientrare di continuo: il loro accesso resta ricordato sei mesi.
GRANDPARENT_SESSION_DAYS = 180
# Un accesso «nonno» vede solo la propria pagina: tutto il resto dell'API gli è chiuso.
GRANDPARENT_PATHS = {"/api/v1/me", "/api/v1/auth/logout", "/api/v1/nonni/week"}


def start_session(db: Session, response: Response, user: User, household_id: str, role: str = "adult") -> None:
    token = secrets.token_urlsafe(32)
    lifetime = timedelta(days=GRANDPARENT_SESSION_DAYS if role == "nonno" else settings.session_days)
    db.add(UserSession(token_hash=_token_hash(token), user_id=user.id, household_id=household_id,
                       expires_at=utcnow() + lifetime))
    response.set_cookie(COOKIE_NAME, token, max_age=int(lifetime.total_seconds()), httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/")


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
        if session:
            db.delete(session)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=settings.cookie_secure, samesite="strict")


def current(request: Request, db: Session = Depends(get_db)) -> Ctx:
    """Identità e famiglia si ricavano sempre dalla sessione, mai dai dati inviati dal client."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise ApiError(401, "unauthenticated", "Accesso richiesto.")
    row = db.execute(
        select(UserSession, User, HouseholdUser)
        .join(User, User.id == UserSession.user_id)
        .join(HouseholdUser, (HouseholdUser.user_id == User.id)
              & (HouseholdUser.household_id == UserSession.household_id))
        .where(UserSession.token_hash == _token_hash(token))
    ).first()
    if row is None:
        raise ApiError(401, "unauthenticated", "Sessione non valida. Accedi di nuovo.")
    session, user, membership = row
    if user.disabled or session.expires_at <= utcnow():
        raise ApiError(401, "session_expired", "Sessione scaduta. Accedi di nuovo.")
    if membership.role == "nonno" and request.url.path not in GRANDPARENT_PATHS:
        raise ApiError(403, "forbidden", "Questa pagina non è disponibile per questo accesso.")
    return Ctx(user_id=user.id, login=user.login, household_id=session.household_id, role=membership.role)


def csrf_rejection(request: Request) -> JSONResponse | None:
    """Richieste che modificano dati: header personalizzato obbligatorio e Origin dello stesso host."""
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return None
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        return JSONResponse(error_body(request, "csrf", "Richiesta non consentita."), status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins and urlsplit(origin).netloc != request.headers.get("host"):
        return JSONResponse(error_body(request, "csrf", "Origine non consentita."), status_code=403)
    return None


class LoginLimiter:
    """Limite in memoria ai tentativi falliti, per indirizzo e per coppia indirizzo/utente."""

    def __init__(self, per_login: int = 8, per_ip: int = 30, window_seconds: int = 900):
        self.limits = {"login": per_login, "ip": per_ip}
        self.window = window_seconds
        self.failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _keys(self, ip: str, login: str) -> list[tuple[str, str]]:
        return [("ip", ip), ("login", f"{ip}|{login.lower()}")]

    def check(self, ip: str, login: str) -> None:
        now = time.monotonic()
        for key in self._keys(ip, login):
            attempts = self.failures[key]
            while attempts and now - attempts[0] > self.window:
                attempts.popleft()
            if len(attempts) >= self.limits[key[0]]:
                raise ApiError(429, "too_many_attempts", "Troppi tentativi. Riprova tra qualche minuto.")

    def fail(self, ip: str, login: str) -> None:
        now = time.monotonic()
        for key in self._keys(ip, login):
            self.failures[key].append(now)

    def reset(self, ip: str, login: str) -> None:
        self.failures.pop(self._keys(ip, login)[1], None)


login_limiter = LoginLimiter()
