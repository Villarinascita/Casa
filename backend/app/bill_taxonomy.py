"""Categorie e sottocategorie dei costi e memoria dei fornitori: se Luca corregge la categoria
di un costo, quel fornitore va sempre lì (vedi docs/superpowers/specs/2026-09-26-categorie-costi-design.md)."""

from .dedup import words

DEFAULT_TAXONOMY: dict[str, list[str]] = {
    "Bollette": ["Luce", "Gas", "Acqua", "Telefono e internet", "Rifiuti"],
    "Auto": ["Assicurazione", "Carburante", "Parcheggi e pedaggi", "Manutenzione", "Bollo"],
    "Casa": ["Manutenzione e riparazioni", "Arredamento e casa", "Affitto o mutuo"],
    "Cibo": ["Spesa", "Delivery", "Ristoranti e bar"],
    "Acquisti online": ["Amazon", "Vinted", "Altri negozi"],
    "Abbonamenti": ["Streaming", "App e software"],
    "Tecnologia e lavoro": ["Server e hosting", "Intelligenza artificiale", "Servizi"],
    "Salute": ["Visite", "Farmacia"],
    "Figli": ["Scuola", "Sport e attività"],
    "Viaggi": ["Voli", "Hotel", "Treni"],
    "Altro": [],
}
# Vecchie categorie predefinite sostituite dallo schema nuovo.
LEGACY = {"Auto e assicurazione": "Auto"}
_GENERIC = {"srl", "spa", "s", "r", "l", "inc", "ltd", "llc", "pbc", "gmbh", "italia", "italy", "ita", "it", "com",
            "services", "service", "sa", "snc", "sas", "the"}


def taxonomy_of(settings: dict | None) -> dict[str, list[str]]:
    settings = settings or {}
    if isinstance(settings.get("bill_taxonomy"), dict):
        return {k: list(v) for k, v in settings["bill_taxonomy"].items()}
    taxonomy = {k: list(v) for k, v in DEFAULT_TAXONOMY.items()}
    for category in settings.get("bill_categories", []):
        if category not in taxonomy and category not in LEGACY:
            taxonomy[category] = []
    return taxonomy


def supplier_key(supplier: str | None) -> str | None:
    """«Octopus Energy Italia Srl» e «Octopus Energy» sono lo stesso fornitore."""
    ws = [w for w in words(supplier or "") if w not in _GENERIC and not w.isdigit()]
    return " ".join(ws[:2]) or None


def rules_of(settings: dict | None) -> dict[str, list[str]]:
    rules = (settings or {}).get("bill_supplier_rules")
    return dict(rules) if isinstance(rules, dict) else {}


def known_supplier(settings: dict | None, supplier: str | None) -> tuple[str, str | None] | None:
    key = supplier_key(supplier)
    rule = rules_of(settings).get(key) if key else None
    return (rule[0], rule[1] if len(rule) > 1 else None) if rule else None


def learn(settings: dict | None, supplier: str | None, category: str, subcategory: str | None) -> dict | None:
    """Nuove impostazioni con la regola del fornitore, o None se non c'è nulla da imparare."""
    key = supplier_key(supplier)
    if not key:
        return None
    rules = rules_of(settings)
    if rules.get(key) == [category, subcategory]:
        return None
    rules[key] = [category, subcategory]
    return {**(settings or {}), "bill_supplier_rules": rules}


def normalize(taxonomy: dict[str, list[str]], category: str | None, subcategory: str | None) -> tuple[str, str | None]:
    """Categoria sconosciuta → «Altro»; la sottocategoria proposta da Hermes resta anche se nuova."""
    category = LEGACY.get(category or "", category or "")
    match = next((c for c in taxonomy if c.lower() == category.lower()), None)
    if match is None:
        return "Altro", None
    subcategory = (subcategory or "").strip() or None
    known = next((s for s in taxonomy[match] if subcategory and s.lower() == subcategory.lower()), None)
    return match, known or (subcategory[:60] if subcategory else None)


def prompt_text(taxonomy: dict[str, list[str]], settings: dict | None) -> str:
    listing = "; ".join(f"{c}: {', '.join(subs)}" if subs else c for c, subs in taxonomy.items())
    text = (f"Per bills scegli category SOLO tra queste categorie e subcategory tra le sue sottocategorie: {listing}. "
            "Capisci la categoria dal fornitore e dal contenuto (es. delivery di cibo → Cibo › Delivery, "
            "Amazon → Acquisti online › Amazon, assicurazione dell'auto → Auto › Assicurazione, fornitore di "
            "luce → Bollette › Luce). Se nessuna sottocategoria va bene puoi proporne una nuova breve; se "
            "nessuna categoria va bene usa «Altro». ")
    rules = rules_of(settings)
    if rules:
        text += ("Fornitori già classificati dalla famiglia (usa sempre questa classificazione): "
                 + "; ".join(f"{k} → {v[0]}{' › ' + v[1] if len(v) > 1 and v[1] else ''}" for k, v in list(rules.items())[:60])
                 + ". ")
    return text
