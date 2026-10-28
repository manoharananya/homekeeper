"""Inbox -> review queue -> tracker.

1. Every new file in <home>/inbox is read and classified.
2. Files are grouped into one candidate product per order (invoice + order page + packing slip).
3. Manuals are attached to the product whose brand/model they match best.
4. YOU review each candidate: Home / Gift / Someone else / Skip. Nothing is saved without that.
"""
from __future__ import annotations

import calendar
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from . import catalog, db
from .extract import SUPPORTED, Extracted, extract, file_hash, key_nouns, short_name

KIND_PRIORITY = {"invoice": 0, "order_summary": 1, "packing_slip": 2, "manual": 3, "unknown": 4}


@dataclass
class Candidate:
    docs: list[Extracted] = field(default_factory=list)
    manuals: list[Extracted] = field(default_factory=list)

    def best(self, attr):
        for d in sorted(self.docs, key=lambda d: KIND_PRIORITY.get(d.kind, 9)):
            if getattr(d, attr):
                return getattr(d, attr)
        for d in self.manuals:
            if getattr(d, attr, None):
                return getattr(d, attr)
        return None

    @property
    def fields(self) -> dict:
        title = self.best("title") or Path((self.docs or self.manuals)[0].path).stem
        brand = self.best("brand")
        f = {k: self.best(k) for k in ("brand", "model", "asin", "serial", "order_id", "seller", "price",
                                       "purchase_date", "return_by", "warranty_months", "ship_to")}
        f["title"] = title
        f["name"] = short_name(title, brand)
        f["category"] = catalog.guess_category(title, *(m.title for m in self.manuals))
        if not f["warranty_months"]:
            f["warranty_months"] = catalog.CATEGORIES[f["category"]]["warranty"]
            f["warranty_assumed"] = True
        return f


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_manual(manual: Extracted, names: list[tuple[str, str | None, str | None]]) -> int | None:
    """Index of the best (title, brand, model) match for a manual, or None."""
    best_i, best_s = None, 0.0
    for i, (title, brand, model) in enumerate(names):
        s = 0.0
        if model and manual.model and model.lower() == manual.model.lower():
            s += 0.6
        elif model and model.lower() in manual.text[:3000].lower():
            s += 0.5
        if brand and manual.brand and brand.lower() == manual.brand.lower():
            s += 0.25
        s += 0.3 * _similar(title or "", manual.title or "")
        if s > best_s:
            best_i, best_s = i, s
    return best_i if best_s >= 0.45 else None


UNREADABLE, DUPLICATES = "_unreadable", "_duplicates"


def inbox_files(inbox: Path) -> list[Path]:
    """Supported files waiting in the inbox (files we could not read are parked in _unreadable/)."""
    return [p for p in sorted(inbox.rglob("*")) if p.is_file() and p.suffix.lower() in SUPPORTED
            and not {UNREADABLE, DUPLICATES} & set(p.relative_to(inbox).parts)]


def _park(inbox: Path, p: Path, folder: str) -> Path:
    dest_dir = inbox / folder
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / p.name
    shutil.move(str(p), dest)
    return dest


def scan_inbox(con, inbox: Path | None = None, unreadable: list | None = None
               ) -> tuple[list[Candidate], list[Extracted]]:
    """Read new files and build review candidates. Returns (candidates, isp_bills).
    Files that cannot be read are moved to inbox/_unreadable/ and appended to `unreadable`."""
    inbox = Path(inbox or db.home_dir() / "inbox")
    known = {r["sha256"] for r in con.execute("SELECT sha256 FROM documents")}
    exs: list[Extracted] = []
    seen_now: set[str] = set()
    for p in inbox_files(inbox):
        h = file_hash(p)
        if h in known or h in seen_now:  # already tracked, or the same file dropped in twice (AI_LOG #17)
            dest = _park(inbox, p, DUPLICATES)
            if unreadable is not None:
                unreadable.append(Extracted(path=str(dest), kind="duplicate",
                                            error="same file is already tracked or in this batch"))
            continue
        seen_now.add(h)
        ex = extract(p)
        if ex.kind == "unreadable":
            ex.path = str(_park(inbox, p, UNREADABLE))
            if unreadable is not None:
                unreadable.append(ex)
            continue
        exs.append(ex)

    groups: dict[str, Candidate] = {}
    loose_manuals, bills = [], []
    for ex in exs:
        if ex.kind == "manual":
            loose_manuals.append(ex)
        elif ex.kind == "isp_bill":
            bills.append(ex)
        else:
            key = ex.order_id or f"file:{ex.path}"
            groups.setdefault(key, Candidate()).docs.append(ex)
    cands = list(groups.values())

    # attach manuals to new candidates first, then to products already in the tracker
    existing = con.execute("SELECT id, name, brand, model FROM products").fetchall()
    for man in loose_manuals:
        names = [(c.fields["title"], c.fields["brand"], c.fields["model"]) for c in cands]
        i = match_manual(man, names)
        if i is not None:
            cands[i].manuals.append(man)
            continue
        j = match_manual(man, [(r["name"], r["brand"], r["model"]) for r in existing])
        if j is not None:
            man.matched_product_id = existing[j]["id"]  # type: ignore[attr-defined]
        cands.append(Candidate(manuals=[man]))  # reviewed on its own
    return cands, bills


def suggest(fields: dict, owner_names: list[str], kinds: list[str] | None = None) -> tuple[str, str]:
    """Pre-select a decision and explain why. The user always confirms."""
    if kinds is not None and all(k == "unknown" for k in kinds) and not fields.get("order_id"):
        return "skip", "Doesn't look like an invoice, order or manual"  # AI_LOG #14
    ship = (fields.get("ship_to") or "").lower()
    if ship and owner_names and not any(_similar(ship, o) > 0.8 or o.lower() in ship for o in owner_names):
        return "other", f"Shipped to {fields['ship_to']}, not you. Gift or someone else's?"
    return "home", "Shipped to you" if ship else "No shipping name found"


def _file_into_vault(path: str, folder: str, kind: str | None = None) -> str:
    """Move a file into vault/<folder>/, renamed to its type (invoice.pdf, manual.pdf...)."""
    dest_dir = db.home_dir() / "vault" / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    stem = kind if kind and kind != "unknown" else src.stem
    dest, n = dest_dir / f"{stem}{src.suffix.lower()}", 2
    while dest.exists() and dest.resolve() != src.resolve():
        dest, n = dest_dir / f"{stem}-{n}{src.suffix.lower()}", n + 1
    if Path(path).resolve() != dest.resolve():
        shutil.move(path, dest)
    return str(dest)


def first_due(start: date, interval_days: int) -> date:
    """First due date. If it is already in the past we don't know when it was last done,
    so it is due now rather than 'N days overdue' (AI_LOG #7)."""
    return max(start + timedelta(days=interval_days), db.today())


def add_tasks(con, product_id: int, category: str, schedules: list[dict], start: str | None,
              brand: str | None = None, model: str | None = None) -> int:
    """Create maintenance tasks: from the manual first, templates for anything not covered."""
    start_d = date.fromisoformat(start) if start else db.today()
    created = 0
    for s in schedules:
        con.execute("INSERT INTO tasks(product_id,title,interval_days,mode,how_to,source,next_due)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (product_id, s["title"], s["interval_days"], s.get("mode", "DIY"), s["how_to"], "manual",
                     first_due(start_d, s["interval_days"]).isoformat()))
        created += 1
    manual_nouns = [key_nouns(s["title"]) for s in schedules]
    for title, days, mode, how, cost, part in catalog.CATEGORIES[category]["tasks"]:
        if any(key_nouns(title) & n for n in manual_nouns):
            continue  # the manual already covers this (AI_LOG #6)
        url = catalog.amazon_search_url(brand, model, part) if part else None
        con.execute("INSERT INTO tasks(product_id,title,interval_days,mode,how_to,est_cost,part_query,order_url,"
                    "source,next_due) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (product_id, title, days, mode, how, cost, part, url, "template",
                     first_due(start_d, days).isoformat()))
        created += 1
    # manual tasks that match a template inherit its cost and part link
    for title, days, mode, how, cost, part in catalog.CATEGORIES[category]["tasks"]:
        for s in schedules:
            if key_nouns(title) & key_nouns(s["title"]) and (cost or part):
                con.execute("UPDATE tasks SET est_cost=?, part_query=?, order_url=? WHERE product_id=? AND title=?",
                            (cost, part, catalog.amazon_search_url(brand, model, part) if part else None,
                             product_id, s["title"]))
    return created


def add_months(d: date, months: int) -> date:
    """31 Jan + 1 month = 28/29 Feb, 15 Mar + 12 = 15 Mar next year (AI_LOG #15)."""
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def save_product(con, f: dict, cand: Candidate) -> int:
    end = None
    if f.get("purchase_date") and f.get("warranty_months"):
        end = add_months(date.fromisoformat(f["purchase_date"]), int(f["warranty_months"])).isoformat()
    cur = con.execute(
        "INSERT INTO products(name,brand,model,category,asin,serial,order_id,seller,price,purchase_date,"
        "return_by,warranty_months,warranty_end,room,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f["name"], f.get("brand"), f.get("model"), f["category"], f.get("asin"), f.get("serial"),
         f.get("order_id"), f.get("seller"), f.get("price"), f.get("purchase_date"), f.get("return_by"),
         f.get("warranty_months"), end, f.get("room"), f.get("title")))
    pid = cur.lastrowid
    folder = catalog.slug(f"{f['name']}-{pid}")
    for ex in cand.docs + cand.manuals:
        record_doc(con, ex, "home", pid, _file_into_vault(ex.path, folder, ex.kind))
    schedules = [s for m in cand.manuals for s in m.schedules]
    add_tasks(con, pid, f["category"], schedules, f.get("purchase_date"), f.get("brand"), f.get("model"))
    con.execute("INSERT INTO contacts(product_id,name,url,notes) VALUES (?,?,?,?)",
                (pid, f"{f.get('brand') or 'Brand'} service", catalog.support_search_url(f.get("brand"), f.get("model")),
                 "Search link. Replace with the real number once you have it: homekeeper contact add"))
    con.commit()
    return pid


def record_doc(con, ex: Extracted, decision: str, product_id: int | None, path: str | None = None):
    con.execute("INSERT OR IGNORE INTO documents(product_id,kind,path,sha256,decision) VALUES (?,?,?,?,?)",
                (product_id, ex.kind, path or ex.path, file_hash(Path(path or ex.path)), decision))


def attach_manual(con, man: Extracted, pid: int):
    row = con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    folder = catalog.slug(f"{row['name']}-{pid}")
    record_doc(con, man, "home", pid, _file_into_vault(man.path, folder, "manual"))
    if man.schedules:
        con.execute("DELETE FROM tasks WHERE product_id=? AND source='template' AND last_done IS NULL", (pid,))
        add_tasks(con, pid, row["category"], man.schedules, row["purchase_date"], row["brand"], row["model"])
    con.commit()


def set_aside(con, cand: Candidate, decision: str):
    """Gift / someone else / skip: remember the files so they are never asked about again."""
    for ex in cand.docs + cand.manuals:
        record_doc(con, ex, decision, None, _file_into_vault(ex.path, f"_not-home/{decision}"))
    con.commit()


Decider = Callable[[Candidate, dict, tuple[str, str]], tuple[str, dict]]
