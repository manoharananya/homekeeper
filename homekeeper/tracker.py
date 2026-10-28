"""Warranty, returns and maintenance logic (no printing here, so it is easy to test)."""
from __future__ import annotations

from datetime import date, timedelta

from . import db


def warranty_status(p, today: date | None = None) -> tuple[str, int | None]:
    """('active'|'expiring'|'expired'|'unknown', days_left)."""
    today = today or db.today()
    if not p["warranty_end"]:
        return "unknown", None
    left = (date.fromisoformat(p["warranty_end"]) - today).days
    if left < 0:
        return "expired", left
    return ("expiring" if left <= 30 else "active"), left


def return_status(p, today: date | None = None) -> tuple[str, int | None]:
    today = today or db.today()
    if not p["return_by"]:
        return "unknown", None
    left = (date.fromisoformat(p["return_by"]) - today).days
    return ("open" if left >= 0 else "closed"), left


def due_tasks(con, within_days: int = 30, today: date | None = None):
    today = today or db.today()
    horizon = (today + timedelta(days=within_days)).isoformat()
    rows = con.execute(
        "SELECT t.*, p.name AS product, p.brand, p.model FROM tasks t JOIN products p ON p.id=t.product_id "
        "WHERE t.next_due <= ? ORDER BY t.next_due", (horizon,)).fetchall()
    return [(r, (date.fromisoformat(r["next_due"]) - today).days) for r in rows]


def mark_done(con, task_id: int, cost: float | None = None, by_whom: str | None = None,
              note: str | None = None, on: date | None = None) -> str:
    on = on or db.today()
    t = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not t:
        raise ValueError(f"No task with id {task_id}")
    nxt = (on + timedelta(days=t["interval_days"])).isoformat()
    con.execute("UPDATE tasks SET last_done=?, next_due=? WHERE id=?", (on.isoformat(), nxt, task_id))
    con.execute("INSERT INTO task_log(task_id,done_on,cost,by_whom,note) VALUES (?,?,?,?,?)",
                (task_id, on.isoformat(), cost, by_whom, note))
    con.commit()
    return nxt


def spend_by_product(con, year: int | None = None):
    year = year or db.today().year
    return con.execute(
        "SELECT p.id, p.name, p.price, COALESCE(SUM(l.cost),0) AS spent, COUNT(l.id) AS jobs "
        "FROM products p LEFT JOIN tasks t ON t.product_id=p.id "
        "LEFT JOIN task_log l ON l.task_id=t.id AND substr(l.done_on,1,4)=? "
        "GROUP BY p.id ORDER BY spent DESC", (str(year),)).fetchall()


def repair_or_replace(price: float | None, spent: float) -> str | None:
    if price and spent >= 0.4 * price:
        return f"Upkeep this year is {spent / price:.0%} of the purchase price. Compare with replacing it."
    return None


def find_product(con, ref: str):
    """Accept an id ('3') or part of a name ('jbl')."""
    if str(ref).isdigit():
        return con.execute("SELECT * FROM products WHERE id=?", (int(ref),)).fetchone()
    rows = con.execute("SELECT * FROM products WHERE name LIKE ? OR brand LIKE ? OR model LIKE ?",
                       (f"%{ref}%",) * 3).fetchall()
    return rows[0] if len(rows) == 1 else (rows or None)
