"""Amministrazione da riga di comando. Non esiste registrazione pubblica: gli utenti si creano qui.

Esempi:
    uv run python -m app.cli create-household "Famiglia Rossi"
    uv run python -m app.cli create-user luca --role admin
    uv run python -m app.cli reset-password luca
    uv run python -m app.cli list-users
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from .db import SessionLocal
from .models import Household, HouseholdUser, Member, User
from .security import hash_password

DEFAULT_MEMBERS = [
    ("Papà", "genitore"), ("Mamma", "genitore"), ("Bambina", "figlia"),
    ("Nonna materna", "nonna"), ("Nonno materno", "nonno"), ("Nonna paterna", "nonna"), ("Nonno paterno", "nonno"),
]
DEFAULT_AREAS = ["Bambina", "Casa e bollette", "Auto", "Documenti"]


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        # PowerShell antepone un BOM invisibile a ciò che passa in pipe.
        password = sys.stdin.readline().rstrip("\r\n").lstrip("﻿")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Ripeti la password: "):
            sys.exit("Le password non coincidono.")
    if len(password) < 10:
        sys.exit("La password deve avere almeno 10 caratteri.")
    return password


def pick_household(db, ref: str | None) -> Household:
    households = db.scalars(select(Household)).all()
    if ref:
        matches = [h for h in households if ref in (h.id, h.name)]
    else:
        matches = households
    if len(matches) != 1:
        sys.exit("Specifica la famiglia con --household (id o nome)." if matches else "Nessuna famiglia trovata: "
                 "esegui prima create-household.")
    return matches[0]


def create_household(args) -> None:
    with SessionLocal() as db:
        household = Household(name=args.name, timezone=args.timezone, settings={"areas": DEFAULT_AREAS})
        db.add(household)
        db.flush()
        if not args.no_default_members:
            # Etichette provvisorie, modificabili dall'app: nessun nome reale presunto.
            for order, (name, relation) in enumerate(DEFAULT_MEMBERS):
                db.add(Member(household_id=household.id, display_name=name, relation=relation, sort_order=order))
        db.commit()
        print(f"Famiglia creata: {household.name} ({household.id})")


def create_user(args) -> None:
    login = args.login.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.login == login)):
            sys.exit(f"L'utente {login} esiste già.")
        household = pick_household(db, args.household)
        user = User(login=login, password_hash=hash_password(read_password(args.password_stdin)))
        db.add(user)
        db.flush()
        db.add(HouseholdUser(household_id=household.id, user_id=user.id, role=args.role))
        db.commit()
        print(f"Utente {login} creato nella famiglia {household.name} con ruolo {args.role}.")


def reset_password(args) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == args.login.strip().lower()))
        if user is None:
            sys.exit("Utente non trovato.")
        user.password_hash = hash_password(read_password(args.password_stdin))
        db.commit()
        print("Password aggiornata.")


def list_users(_args) -> None:
    with SessionLocal() as db:
        rows = db.execute(select(User, HouseholdUser, Household)
                          .join(HouseholdUser, HouseholdUser.user_id == User.id)
                          .join(Household, Household.id == HouseholdUser.household_id)).all()
        for user, membership, household in rows:
            state = " (disattivato)" if user.disabled else ""
            print(f"{user.login}\t{membership.role}\t{household.name}{state}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Amministrazione di Insieme")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("create-household", help="Crea la famiglia")
    p.add_argument("name")
    p.add_argument("--timezone", default="Europe/Rome")
    p.add_argument("--no-default-members", action="store_true", help="Non creare le etichette provvisorie")
    p.set_defaults(func=create_household)

    p = sub.add_parser("create-user", help="Crea un account adulto")
    p.add_argument("login")
    p.add_argument("--household", help="Id o nome della famiglia (se ce n'è più di una)")
    p.add_argument("--role", choices=["admin", "adult"], default="adult")
    p.add_argument("--password-stdin", action="store_true", help="Legge la password dalla prima riga di stdin")
    p.set_defaults(func=create_user)

    p = sub.add_parser("reset-password", help="Imposta una nuova password")
    p.add_argument("login")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=reset_password)

    p = sub.add_parser("list-users", help="Elenca gli utenti")
    p.set_defaults(func=list_users)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
