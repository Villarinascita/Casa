"""OAuth Google e richieste alle API Workspace."""

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EmailDomainCleanup, GoogleConnection, GoogleOAuthState, Household, utcnow
from .security import Ctx

SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
)


class GoogleApi:
    def __init__(self, client_id: str, client_secret: str, client: httpx.Client | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = client or httpx.Client(timeout=30)

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        response = self.client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        })
        response.raise_for_status()
        return response.json()

    def profile(self, access_token: str) -> dict:
        response = self.client.get("https://gmail.googleapis.com/gmail/v1/users/me/profile",
                                   headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        return response.json()

    def refresh(self, refresh_token: str) -> str:
        response = self.client.post("https://oauth2.googleapis.com/token", data={
            "refresh_token": refresh_token, "client_id": self.client_id,
            "client_secret": self.client_secret, "grant_type": "refresh_token",
        })
        response.raise_for_status()
        return response.json()["access_token"]

    def get(self, url: str, token: str, params: dict | None = None) -> dict:
        response = self.client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()

    def post(self, url: str, token: str, body: dict) -> dict:
        response = self.client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()

    def patch(self, url: str, token: str, body: dict, etag: str) -> dict:
        response = self.client.patch(url, json=body,
                                     headers={"Authorization": f"Bearer {token}", "If-Match": etag})
        response.raise_for_status()
        return response.json()

    def delete(self, url: str, token: str, etag: str) -> None:
        response = self.client.delete(url, headers={"Authorization": f"Bearer {token}", "If-Match": etag})
        response.raise_for_status()


class GoogleService:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, encryption_key: str,
                 api: GoogleApi | None = None):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.fernet = Fernet(encryption_key.encode())
        self.api = api or GoogleApi(client_id, client_secret)

    def start(self, db: Session, ctx: Ctx) -> str:
        state = secrets.token_urlsafe(32)
        db.add(GoogleOAuthState(state_hash=hashlib.sha256(state.encode()).hexdigest(),
                                user_id=ctx.user_id, household_id=ctx.household_id,
                                expires_at=utcnow() + timedelta(minutes=10)))
        db.commit()
        params = {
            "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": " ".join(SCOPES),
            "access_type": "offline", "prompt": "consent", "state": state,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    def finish(self, db: Session, state: str, code: str) -> GoogleConnection:
        row = db.get(GoogleOAuthState, hashlib.sha256(state.encode()).hexdigest())
        if row is None or row.expires_at <= utcnow():
            raise ValueError("Autorizzazione Google scaduta o non valida")
        tokens = self.api.exchange_code(code, self.redirect_uri)
        email = self.api.profile(tokens["access_token"])["emailAddress"]
        connection = db.scalar(select(GoogleConnection).where(GoogleConnection.user_id == row.user_id))
        is_new_connection = connection is None
        if connection is None:
            if not tokens.get("refresh_token"):
                raise ValueError("Google non ha restituito un token di accesso persistente")
            connection = GoogleConnection(user_id=row.user_id, household_id=row.household_id,
                                          email=email, refresh_token_encrypted="")
            db.add(connection)
            db.flush()
        if is_new_connection:
            household = db.get(Household, row.household_id)
            blocked_domains = (household.settings or {}).get("blocked_email_domains", []) if household else []
            for domain in blocked_domains:
                db.add(EmailDomainCleanup(household_id=row.household_id, connection_id=connection.id, domain=domain))
        if tokens.get("refresh_token"):
            connection.refresh_token_encrypted = self.fernet.encrypt(tokens["refresh_token"].encode()).decode()
        connection.email = email
        db.delete(row)
        db.commit()
        return connection

    def refresh_token(self, connection: GoogleConnection) -> str:
        return self.fernet.decrypt(connection.refresh_token_encrypted.encode()).decode()

    def access_token(self, connection: GoogleConnection) -> str:
        return self.api.refresh(self.refresh_token(connection))
