import base64
import io
import zipfile
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.grandparent_plan import (PlanError, apply_plan, create_plan, extract_text, normalize_items, process_plans,
                                  school_year_end)
from app.models import Event, GrandparentPlan, Household, Member, User
from app.telegram import process_update, receive_document

NOW = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)  # domenica


def _docx(paragraphs, table=None):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
                       + "</w:tr>" for row in table)
        body += f"<w:tbl>{rows}</w:tbl>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return buffer.getvalue()


def _pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\nstartxref\n"
              + str(xref).encode() + b"\n%%" + b"EOF")
    return out.getvalue()


def test_legge_word_con_tabella_e_pdf():
    text = extract_text("programma.docx", _docx(["Programma dei nonni"], [["Martedi", "16:30", "Asilo", "Nonna Anna"]]))
    assert "Programma dei nonni" in text and "Martedi | 16:30 | Asilo | Nonna Anna" in text
    assert "Nonna Anna martedi asilo" in extract_text("p.pdf", _pdf("Nonna Anna martedi asilo"))


@pytest.mark.parametrize("name,data,message", [
    ("vecchio.doc", b"x", "Word vecchio"), ("foto.jpg", b"x", "PDF o un Word"),
    ("rotto.docx", b"non zip", "Non riesco ad aprire"), ("vuoto.docx", _docx([]), "non c'è testo"),
])
def test_file_non_utilizzabili(name, data, message):
    with pytest.raises(PlanError, match=message):
        extract_text(name, data)


def test_voci_pulite():
    items = normalize_items([
        {"who": "Nonna Anna", "title": "Asilo", "weekday": 2, "start": "16.30", "until": None},
        {"who": "Nonno Piero", "title": "Visita", "date": "2026-10-05", "weekday": 3, "start": "25:00"},
        {"who": "", "title": "senza nonno", "weekday": 1}, {"who": "X", "title": "senza giorno"}, "rotta"],
        date(2026, 9, 27))
    assert items == [
        {"who": "Nonna Anna", "title": "Asilo", "weekday": 2, "date": None, "start": "16:30", "end": None,
         "place": None, "notes": None, "from": None, "until": "2027-06-30"},
        {"who": "Nonno Piero", "title": "Visita", "weekday": None, "date": "2026-10-05", "start": None, "end": None,
         "place": None, "notes": None, "from": None, "until": None}]
    assert school_year_end(date(2027, 3, 1)) == date(2027, 6, 30)


def _plan(db, seed, source="app"):
    user = db.scalar(select(User).where(User.login == "luca"))
    plan = create_plan(db, seed["Rossi"], user.id, source, "programma.docx",
                       _docx(["Nonna Anna prende Matilde all'asilo il martedì alle 16:30 fino al 20 ottobre"]))
    return plan, user


def _read(text, members, today, context=""):
    return {"items": [{"who": "Nonna Anna", "title": "Prendere Matilde all'asilo", "weekday": 2, "start": "16:30",
                       "place": "Asilo", "until": "2026-10-20"},
                      {"who": "Mamma Rossi", "title": "Visita pediatra", "date": "2026-10-01", "start": "10:00"}],
            "notes": ""}


def test_lettura_conferma_e_sostituzione(db_factory, seed):
    with db_factory() as db:
        plan, user = _plan(db, seed)
        assert plan.status == "reading"
        sent = []
        process_plans(db, _read, NOW, notify=lambda p, s: sent.append(s))
        assert plan.status == "pending" and len(plan.items) == 2 and "ogni martedì 16:30" in sent[0]
        result = apply_plan(db, plan, user.id, NOW)
        # martedì 29/9, 6/10, 13/10, 20/10 più la visita dell'1/10
        assert result == {"created": 5, "replaced": 0, "new_members": ["Nonna Anna"]}
        asilo = sorted(e.start_at.date() for e in db.scalars(select(Event).where(Event.source == "nonni"))
                       if e.title.startswith("Prendere"))
        assert [d.isoformat() for d in asilo] == ["2026-09-29", "2026-10-06", "2026-10-13", "2026-10-20"]
        household = db.get(Household, seed["Rossi"])
        nonna = db.scalar(select(Member).where(Member.display_name == "Nonna Anna"))
        assert nonna.relation == "nonna" and nonna.id in household.settings["grandparent_members"]
        assert seed["member_Rossi"] in household.settings["grandparent_members"]  # «Mamma Rossi» c'era già
        # Un nuovo programma sostituisce gli impegni futuri del precedente.
        second, _ = _plan(db, seed)
        process_plans(db, _read, NOW)
        again = apply_plan(db, second, user.id, NOW)
        assert again["replaced"] == 5 and again["new_members"] == []
        with pytest.raises(PlanError):
            apply_plan(db, second, user.id, NOW)


def test_hermes_non_raggiungibile_riprova(db_factory, seed):
    from app.hermes_client import HermesInvalidResponse, HermesUnavailable
    with db_factory() as db:
        plan, _ = _plan(db, seed)

        def down(*args):
            raise HermesUnavailable("giù")

        process_plans(db, down, NOW)
        assert db.get(GrandparentPlan, plan.id).status == "reading"

        def confused(*args):
            raise HermesInvalidResponse("boh")

        process_plans(db, confused, NOW)
        assert db.get(GrandparentPlan, plan.id).status == "failed"


def _upload(client, name="programma.docx", data=None):
    content = base64.b64encode(data if data is not None else _docx(["Nonna: martedì asilo"])).decode()
    return client.post("/api/v1/nonni/plans", json={"filename": name, "content_base64": content})


def test_api_caricamento_elenco_e_scarto(luca, db_factory, seed):
    upload = _upload(luca)
    assert upload.status_code == 201, upload.text
    assert upload.json()["status"] == "reading"
    bad = _upload(luca, "foto.jpg", b"x")
    assert bad.status_code == 422 and "PDF" in bad.json()["message"]
    with db_factory() as db:
        process_plans(db, _read, NOW)
    listed = luca.get("/api/v1/nonni/plans").json()
    assert listed[0]["status"] == "pending"
    assert listed[0]["items"][0]["summary"].startswith("Nonna Anna · ogni martedì")
    assert luca.post(f"/api/v1/nonni/plans/{listed[0]['id']}/discard").status_code == 204
    assert luca.get("/api/v1/nonni/plans").json() == []


def test_api_conferma(luca, marco, db_factory, seed):
    upload = _upload(luca).json()
    with db_factory() as db:
        process_plans(db, _read, NOW)
    assert marco.post(f"/api/v1/nonni/plans/{upload['id']}/apply").status_code == 404  # altra famiglia
    applied = luca.post(f"/api/v1/nonni/plans/{upload['id']}/apply")
    assert applied.status_code == 200 and applied.json()["created"] >= 1


def _message(update_id, **extra):
    return {"update_id": update_id,
            "message": {"from": {"id": 123}, "chat": {"id": 123, "type": "private"}, **extra}}


def test_telegram_file_e_conferma(luca, db_factory, seed):
    code = luca.post("/api/v1/connections/telegram/start").json()["code"]
    with db_factory() as db:
        process_update(db, _message(1, text=f"/link {code}"), lambda *_: {})
        reply = receive_document(db, _message(2, document={}), "programma.docx", _docx(["Nonna Anna martedì asilo"]))
        assert "lo leggo" in reply
        process_plans(db, _read, NOW)
        answer = process_update(db, _message(3, text="Sì"), lambda *_: pytest.fail("non deve passare da Hermes"))
        assert answer.startswith("Fatto: ho inserito")
        assert db.scalar(select(GrandparentPlan)).status == "applied"
        # Senza programmi in attesa «sì» torna una richiesta normale.
        seen = []
        process_update(db, _message(4, text="sì"), lambda text, ctx: seen.append(text) or {"clarification": "Cosa?"})
        assert seen == ["sì"]


def test_telegram_senza_collegamento(db_factory, seed):
    with db_factory() as db:
        reply = receive_document(db, {"update_id": 9, "message": {"from": {"id": 999}, "chat": {"id": 999, "type": "private"}}},
                                 "p.docx", _docx(["x"]))
        assert "Collega Telegram" in reply


def test_vale_dalla_data_indicata_con_indicazioni_e_calendario(db_factory, seed):
    with db_factory() as db:
        user = db.scalar(select(User).where(User.login == "luca"))
        db.add(Event(household_id=seed["Rossi"], title="GINNASTICA ARTISTICA", source="google",
                     start_at=datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc)))
        db.commit()
        plan = create_plan(db, seed["Rossi"], user.id, "app", "schema.docx", _docx(["Lunedì ginnastica con Mirco"]))
        seen = {}

        def read(text, members, today, context):
            seen["context"] = context
            return {"items": [{"who": "Mirco", "title": "Portare Matilde a ginnastica", "weekday": 1, "start": "16:30",
                               "notes": "Dopo: doccia e pigiamino, cena alle 19:00", "from": "2026-10-05",
                               "until": "2026-10-19"}]}

        process_plans(db, read, NOW)
        assert "gio 01/10" in seen["context"] and "GINNASTICA ARTISTICA" in seen["context"]
        assert plan.items[0]["from"] == "2026-10-05"
        result = apply_plan(db, plan, user.id, NOW)
        events = sorted(db.scalars(select(Event).where(Event.source == "nonni")).all(), key=lambda e: e.start_at)
        assert result["created"] == 3 and [e.start_at.date().isoformat() for e in events] == [
            "2026-10-05", "2026-10-12", "2026-10-19"]  # non il 28/09: vale dal 5/10
        assert events[0].notes == "Dopo: doccia e pigiamino, cena alle 19:00"
