"""Mittenti email bloccati (domini interi o indirizzi precisi): normalizzazione e confronto
con il mittente (solo header From)."""

import re
from collections.abc import Iterable
from email.utils import parseaddr

_DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$")
_LOCAL_PART = re.compile(r"^[a-z0-9._%+-]{1,64}$")


def normalize_blocked_sender(value: str) -> str:
    """Dominio (newsletter.com) o indirizzo preciso (promo@newsletter.com), in minuscolo e
    senza spazi né punto finale; ValueError se non accettabile."""
    entry = value.strip().lower().rstrip(".")
    local, at, domain = entry.rpartition("@")
    if at and (not _LOCAL_PART.match(local) or not _DOMAIN.match(domain)):
        raise ValueError(f"«{value}» non è un indirizzo email valido (es. promo@negozio.it).")
    if not at and not _DOMAIN.match(entry):
        raise ValueError(f"«{value}» non è un dominio valido (es. newsletter.com).")
    return entry


def sender_address(from_header: str) -> str | None:
    address = parseaddr(from_header or "")[1].strip().lower().rstrip(".")
    return address if "@" in address else None


def sender_domain(from_header: str) -> str | None:
    address = sender_address(from_header)
    return address.rsplit("@", 1)[1] or None if address else None


def is_blocked_sender(from_header: str, blocked: Iterable[str]) -> bool:
    """Vero se il mittente è un indirizzo bloccato, oppure appartiene a un dominio bloccato
    o a un suo sottodominio."""
    address = sender_address(from_header)
    if not address:
        return False
    domain = address.rsplit("@", 1)[1]
    return any(address == entry if "@" in entry else (domain == entry or domain.endswith("." + entry))
               for entry in blocked)
