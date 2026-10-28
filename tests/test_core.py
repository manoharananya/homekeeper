"""Core tests: parsing, matching, review suggestions, due dates. Run: pytest -q"""
import shutil
from datetime import date
from pathlib import Path

import pytest

from homekeeper import db, intake, mail, tracker
from homekeeper.extract import classify, extract, find_schedules, fix_ocr, parse_date

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMEKEEPER_HOME", str(tmp_path / "hk"))
    monkeypatch.setenv("HOMEKEEPER_TODAY", "2026-10-28")
    for f in SAMPLES.glob("*.pdf"):
        shutil.copy(f, db.home_dir() / "inbox" / f.name)
    con = db.connect()
    db.set_setting(con, "owner_names", ["Ananya Manohar"])
    return con


def test_parse_dates():
    assert parse_date("12.05.2026") == "2026-05-12"
    assert parse_date("4 July 2026") == "2026-07-04"
    assert parse_date("nonsense") is None


def test_ocr_fixes():
    assert fix_ocr("ASIN BOFNWNZZ1B") == "ASIN B0FNWNZZ1B"
    assert fix_ocr("Galaxy Tab $10 Lite with Al") == "Galaxy Tab S10 Lite with AI"


def test_classify():
    assert classify("Tax Invoice/Bill of Supply") == "invoice"
    assert classify("Packing slip for X 17 July 2026") == "packing_slip"
    assert classify("Order placed 4 July 2026 Order number 1") == "order_summary"
    assert classify("Airtel Xstream Fiber broadband 100 Mbps") == "isp_bill"


def test_manual_schedules():
    s = find_schedules("CARE\nReplace the sediment filter every 6 months.\nClean the tank once every 3 months.\n"
                       "Get the membrane checked by a technician every 2 years.")
    got = {(x["title"], x["interval_days"], x["mode"]) for x in s}
    assert ("Replace the sediment filter", 182, "DIY") in got
    assert ("Clean the tank", 91, "DIY") in got
    assert ("Get the membrane checked", 730, "Technician") in got


def test_invoice_fields():
    ex = extract(SAMPLES / "invoice_kent_ro.pdf")
    assert ex.kind == "invoice"
    assert ex.order_id == "408-1234567-1112223"
    assert ex.price == 16499.0
    assert ex.purchase_date == "2026-03-15"
    assert ex.model == "KGP-9L"
    assert ex.ship_to == "Ananya Manohar"
    assert ex.warranty_months == 12


def test_scan_groups_and_matches_manual(home):
    cands, bills = intake.scan_inbox(home)
    assert len(bills) == 1 and bills[0].plan_mbps == 100
    kent = next(c for c in cands if c.docs and c.fields["brand"] == "Kent")
    assert len(kent.manuals) == 1, "manual should attach to the Kent purifier"
    assert kent.fields["category"] == "water_purifier"


def test_gift_is_suggested_for_other_recipient(home):
    cands, _ = intake.scan_inbox(home)
    fryer = next(c for c in cands if c.docs and "Air Fryer" in c.fields["title"])
    decision, why = intake.suggest(fryer.fields, ["Ananya Manohar"])
    assert decision == "other" and "Rohan Mehta" in why


def test_save_creates_tasks_without_duplicates(home):
    cands, _ = intake.scan_inbox(home)
    kent = next(c for c in cands if c.docs and c.fields["brand"] == "Kent")
    pid = intake.save_product(home, kent.fields, kent)
    titles = [r["title"] for r in home.execute("SELECT title FROM tasks WHERE product_id=?", (pid,))]
    assert len(titles) == 4  # all four from the manual, no template duplicates
    assert not any(t == "Clean storage tank" for t in titles)
    p = home.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    assert p["warranty_end"] == "2027-03-15"
    assert (db.home_dir() / "vault").rglob("manual.pdf")


def test_old_purchase_tasks_are_due_now_not_years_overdue(home):
    assert intake.first_due(date(2020, 1, 1), 30) == date(2026, 10, 28)


def test_mark_done_reschedules(home):
    cands, _ = intake.scan_inbox(home)
    c = next(c for c in cands if c.docs and c.fields["brand"] == "Daikin")
    pid = intake.save_product(home, c.fields, c)
    t = home.execute("SELECT * FROM tasks WHERE product_id=? ORDER BY interval_days LIMIT 1", (pid,)).fetchone()
    nxt = tracker.mark_done(home, t["id"], cost=0, on=date(2026, 10, 28))
    assert nxt == "2026-11-27"


def test_warranty_status():
    row = {"warranty_end": "2026-11-20"}
    assert tracker.warranty_status(row, date(2026, 10, 28)) == ("expiring", 23)
    assert tracker.warranty_status(row, date(2027, 1, 1))[0] == "expired"


def test_email_selection():
    assert mail.parse_selection("1,3,5-7", 10) == [0, 2, 4, 5, 6]
    assert mail.parse_selection("all", 3) == [0, 1, 2]
    assert mail.parse_selection("none", 3) == []
