import pytest

from app.email_domains import is_blocked_sender, normalize_blocked_sender, sender_domain


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


def test_normalize_blocked_sender():
    assert normalize_blocked_sender("  News.COM. ") == "news.com"
    assert normalize_blocked_sender(" Promotion-IT@Amazon.it ") == "promotion-it@amazon.it"
    for bad in ["@b.com", "a@nodot", "a b@x.com", "nodot", "sp ace.com", "a..b.com", "a@@b.com", ""]:
        with pytest.raises(ValueError):
            normalize_blocked_sender(bad)


@pytest.mark.parametrize("header,expected", [
    ("Amazon <promotion-it@amazon.it>", True),
    ("order-update@amazon.it", False),
    ("promotion-it@offerte.amazon.it", False),
    ("xpromotion-it@amazon.it", False),
])
def test_is_blocked_sender_indirizzo_preciso(header, expected):
    assert is_blocked_sender(header, ["promotion-it@amazon.it"]) is expected
