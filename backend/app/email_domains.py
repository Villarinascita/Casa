"""Domini email bloccati: normalizzazione e confronto con il mittente (solo header From)."""

import re
from collections.abc import Iterable
from email.utils import parseaddr

_DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$")


def normalize_domain(value: str) -> str:
    """Dominio in minuscolo, senza spazi né punto finale; ValueError se non accettabile."""
    domain = value.strip().lower().rstrip(".")
    if "@" in domain or not _DOMAIN.match(domain):
        raise ValueError(f"«{value}» non è un dominio valido (es. newsletter.com).")
    return domain


def sender_domain(from_header: str) -> str | None:
    address = parseaddr(from_header or "")[1].strip().lower()
    if "@" not in address:
        return None
    return address.rsplit("@", 1)[1].rstrip(".") or None


def is_blocked_sender(from_header: str, blocked_domains: Iterable[str]) -> bool:
    """Vero se il mittente appartiene a un dominio bloccato o a un suo sottodominio."""
    domain = sender_domain(from_header)
    if not domain:
        return False
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in blocked_domains)
