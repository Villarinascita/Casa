import base64
from datetime import datetime, timezone

from sqlalchemy import select

from app.bill_taxonomy import DEFAULT_TAXONOMY, known_supplier, normalize, prompt_text, supplier_key, taxonomy_of
from app.gmail_sync import ingest_message
from app.models import Bill, GoogleConnection, Household, User

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def test_fornitore_normalizzato():
    assert supplier_key("Octopus Energy Italia Srl") == supplier_key("Octopus Energy") == "octopus energy"
    assert supplier_key("NETFLIX SERVICES ITA") == "netflix"
    assert supplier_key("") is None


def test_categoria_sconosciuta_e_vecchia():
    taxonomy = taxonomy_of({})
    assert normalize(taxonomy, "Auto e assicurazione", "assicurazione") == ("Auto", "Assicurazione")
    assert normalize(taxonomy, "Pippo", "x") == ("Altro", None)
    assert normalize(taxonomy, "cibo", "Sushi") == ("Cibo", "Sushi")  # sottocategoria nuova proposta da Hermes


def test_categorie_personalizzate_si_aggiungono():
    assert "Cani" in taxonomy_of({"bill_categories": ["Bollette", "Auto e assicurazione", "Cani"]})
    assert "Auto e assicurazione" not in taxonomy_of({"bill_categories": ["Auto e assicurazione"]})


def test_prompt_con_fornitori_noti():
    text = prompt_text(DEFAULT_TAXONOMY, {"bill_supplier_rules": {"deliveroo": ["Cibo", "Delivery"]}})
    assert "Bollette: Luce, Gas" in text and "deliveroo → Cibo › Delivery" in text


def _message(message_id):
    return {"id": message_id, "threadId": "t", "labelIds": ["INBOX"], "snippet": "x",
            "payload": {"headers": [{"name": "From", "value": "Deliveroo <no-reply@deliveroo.it>"}],
                        "body": {"data": base64.urlsafe_b64encode(b"x").decode()}}}


def test_correggere_la_categoria_insegna_il_fornitore(luca, db_factory, seed):
    created = luca.post("/api/v1/bills", json={"category": "Altro", "title": "Ordine cena", "supplier": "Deliveroo Italy Srl",
                                              "amount": "18.50"}).json()
    fixed = luca.patch(f"/api/v1/bills/{created['id']}", json={"category": "Cibo", "subcategory": "Delivery"},
                       headers={"If-Match": str(created["version"])})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["subcategory"] == "Delivery"
    with db_factory() as db:
        settings = db.get(Household, seed["Rossi"]).settings
        assert known_supplier(settings, "Deliveroo") == ("Cibo", "Delivery")
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="l@gmail.com",
                                      refresh_token_encrypted="x")
        db.add(connection)
        db.commit()
        # Hermes sbaglia categoria, ma il fornitore è già noto: vince la scelta della famiglia.
        ingest_message(db, connection, _message("m1"), lambda t: {"actions": [], "bills": [
            {"category": "Altro", "title": "Pagamento Deliveroo", "supplier": "Deliveroo", "amount": 37.26,
             "due_date": "2026-09-20"}]}, "Europe/Rome", NOW, household_settings=settings)
        bill = db.scalar(select(Bill).where(Bill.title == "Pagamento Deliveroo"))
        assert (bill.category, bill.subcategory) == ("Cibo", "Delivery")


def test_hermes_classifica_con_sottocategoria(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        connection = GoogleConnection(household_id=seed["Rossi"], user_id=user.id, email="l@gmail.com",
                                      refresh_token_encrypted="x")
        db.add(connection)
        db.commit()
        ingest_message(db, connection, _message("m1"), lambda t: {"actions": [], "bills": [
            {"category": "Bollette", "subcategory": "gas", "title": "Bolletta gas", "supplier": "Sinergas",
             "amount": 54.1}]}, "Europe/Rome", NOW, household_settings={})
        bill = db.scalar(select(Bill))
        assert (bill.category, bill.subcategory) == ("Bollette", "Gas")


def test_classify_bills_legge_la_risposta():
    import httpx
    from app.hermes_client import HermesClient
    content = '{"items":[{"id":"a","category":"Cibo","subcategory":"Delivery"},{"id":3}]}'
    client = HermesClient("http://h", "k", "m", httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))))
    assert client.classify_bills([{"id": "a", "title": "Deliveroo"}], "guida", "m") == {"a": ("Cibo", "Delivery")}
