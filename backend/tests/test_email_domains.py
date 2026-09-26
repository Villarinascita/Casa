import pytest

from app.email_domains import is_blocked_sender, normalize_domain, sender_domain


def test_sender_domain_da_header_con_nome():
    assert sender_domain('"Octopus Energy" <Ciao@OctopusEnergy.it>') == "octopusenergy.it"


def test_sender_domain_senza_indirizzo():
    assert sender_domain("nessuno") is None
    assert sender_domain("") is None


@pytest.mark.parametrize("header,expected", [
    ("info@newsletter.com", True),
    ("Offerte <promo@offerte.newsletter.com>", True),
    ("x@notnewsletter.com", False),
    ("x@newsletter.com.evil.it", False),
    ("", False),
])
def test_is_blocked_sender(header, expected):
    assert is_blocked_sender(header, ["newsletter.com"]) is expected


def test_normalize_domain():
    assert normalize_domain("  News.COM. ") == "news.com"
    for bad in ["a@b.com", "nodot", "sp ace.com", "a..b.com", ""]:
        with pytest.raises(ValueError):
            normalize_domain(bad)
