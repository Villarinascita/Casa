from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crud import check_version, commit
from ..db import get_db
from ..errors import ApiError
from ..email_cleanup import queue_domain_cleanups
from ..models import EmailDomainCleanup, Household, HouseholdUser, User
from ..schemas import DEFAULT_BILL_CATEGORIES, EmailCleanupOut, HouseholdOut, HouseholdPatch, LoginIn, MeOut
from ..security import (Ctx, current, end_session, hash_password, hasher, login_limiter, start_session,
                        verify_password)

router = APIRouter(tags=["auth"])


def household_out(household: Household) -> HouseholdOut:
    settings = household.settings or {}
    return HouseholdOut(id=household.id, name=household.name, timezone=household.timezone,
                        version=household.version, areas=list(settings.get("areas", [])),
                        bill_categories=list(settings.get("bill_categories", DEFAULT_BILL_CATEGORIES)),
                        blocked_email_domains=list(settings.get("blocked_email_domains", [])))


def me_out(db: Session, ctx: Ctx) -> MeOut:
    return MeOut(user_id=ctx.user_id, login=ctx.login, role=ctx.role,
                 household=household_out(db.get(Household, ctx.household_id)))


@router.post("/auth/login", response_model=MeOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    login_limiter.check(ip, data.login)
    user = db.scalar(select(User).where(User.login == data.login.lower()))
    if not verify_password(user, data.password) or user.disabled:
        login_limiter.fail(ip, data.login)
        raise ApiError(401, "invalid_credentials", "Nome utente o password non corretti.")
    membership = db.scalar(select(HouseholdUser).where(HouseholdUser.user_id == user.id))
    if membership is None:
        raise ApiError(403, "no_household", "Questo utente non appartiene a nessuna famiglia.")
    login_limiter.reset(ip, data.login)
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    start_session(db, response, user, membership.household_id)
    db.commit()
    ctx = Ctx(user_id=user.id, login=user.login, household_id=membership.household_id, role=membership.role)
    return me_out(db, ctx)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    db.commit()


@router.get("/me", response_model=MeOut)
def me(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    return me_out(db, ctx)


@router.get("/household", response_model=HouseholdOut)
def get_household(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    return household_out(db.get(Household, ctx.household_id))


@router.patch("/household", response_model=HouseholdOut)
def update_household(data: HouseholdPatch, ctx: Ctx = Depends(current), db: Session = Depends(get_db),
                     if_match: str | None = Header(None)):
    household = db.get(Household, ctx.household_id)
    check_version(household, if_match)
    if data.name is not None:
        household.name = data.name
    if data.areas is not None:
        household.settings = {**(household.settings or {}), "areas": data.areas}
    if data.bill_categories is not None:
        household.settings = {**(household.settings or {}), "bill_categories": data.bill_categories}
    if data.blocked_email_domains is not None:
        previous = list((household.settings or {}).get("blocked_email_domains", []))
        household.settings = {**(household.settings or {}), "blocked_email_domains": data.blocked_email_domains}
        queue_domain_cleanups(db, household.id, previous, data.blocked_email_domains)
    commit(db)
    return household_out(household)


@router.get("/household/email-cleanups", response_model=list[EmailCleanupOut])
def list_email_cleanups(ctx: Ctx = Depends(current), db: Session = Depends(get_db)):
    return db.scalars(select(EmailDomainCleanup).where(EmailDomainCleanup.household_id == ctx.household_id)
                      .order_by(EmailDomainCleanup.created_at.desc())).all()
