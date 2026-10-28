"""Calendar (.ics) and CSV exports."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db


def _event(uid: str, day: str, summary: str, desc: str = "") -> list[str]:
    d = date.fromisoformat(day)
    esc = lambda s: s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}@homekeeper",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{esc(desc)}",
        "BEGIN:VALARM", "TRIGGER:-PT12H", "ACTION:DISPLAY", f"DESCRIPTION:{esc(summary)}", "END:VALARM",
        "END:VEVENT",
    ]


def to_ics(con, path: Path | None = None) -> Path:
    path = Path(path or db.home_dir() / "exports" / "homekeeper.ics")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HomeKeeper//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:HomeKeeper"]
    for t in con.execute("SELECT t.*, p.name AS product FROM tasks t JOIN products p ON p.id=t.product_id"):
        lines += _event(f"task-{t['id']}-{t['next_due']}", t["next_due"], f"{t['product']}: {t['title']}",
                        f"{t['mode']}. {t['how_to'] or ''}\nMark done: homekeeper done {t['id']}")
    for p in con.execute("SELECT * FROM products"):
        if p["warranty_end"]:
            warn = (date.fromisoformat(p["warranty_end"]) - timedelta(days=30)).isoformat()
            lines += _event(f"warranty-{p['id']}", warn, f"{p['name']}: warranty ends in 30 days",
                            f"Ends {p['warranty_end']}. Book any pending repair now. Claim pack: homekeeper claim {p['id']}")
        if p["return_by"] and p["return_by"] >= db.today().isoformat():
            lines += _event(f"return-{p['id']}", p["return_by"], f"{p['name']}: last day to return")
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n")
    return path


def to_csv(con, path: Path | None = None) -> Path:
    path = Path(path or db.home_dir() / "exports" / "products.csv")
    rows = con.execute("SELECT id,name,brand,model,category,serial,order_id,seller,price,purchase_date,"
                       "return_by,warranty_end,room FROM products ORDER BY id").fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else ["id"])
        w.writerows([tuple(r) for r in rows])
    return path
