"""Simulated network history so `net report` has something to show in the demo.
Rows are only written into the demo home, never into your real data."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from . import db


def seed_network(con, days: int = 7, plan: float = 100.0):
    rnd = random.Random(42)
    if not db.get_setting(con, "plan_mbps"):
        db.set_setting(con, "plan_mbps", plan)
    plan = db.get_setting(con, "plan_mbps")
    start = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(days=days)
    for h in range(0, days * 24, 3):
        ts = start + timedelta(hours=h)
        evening = 19 <= ts.hour <= 23
        down = rnd.uniform(0.35, 0.6) * plan if evening else rnd.uniform(0.75, 0.97) * plan
        loss = rnd.choice([0, 0, 0, 1, 2, 5]) if evening else rnd.choice([0, 0, 0, 0, 1])
        con.execute("INSERT INTO net_log(ts,down_mbps,up_mbps,ping_ms,loss_pct,plan_mbps) VALUES (?,?,?,?,?,?)",
                    (ts.isoformat(timespec="minutes"), round(down, 1), round(down * 0.9, 1),
                     round(rnd.uniform(6, 40), 1), loss, plan))
    con.commit()


def seed_history(con):
    """Pretend some jobs were done in the past, so the demo shows a realistic mix of due dates and spend."""
    from datetime import date, timedelta

    from . import tracker
    today = db.today()
    plan = [("Wash indoor air filters", 22, 0, "self"), ("Wet service (coil jet wash)", 170, 650, "Cool Air technician"),
            ("Clean the storage tank", 80, 0, "self"), ("Flush tank sediment", 150, 0, "self")]
    for title, ago, cost, who in plan:
        t = con.execute("SELECT id FROM tasks WHERE title=?", (title,)).fetchone()
        if t:
            tracker.mark_done(con, t["id"], cost, who, "demo history", today - timedelta(days=ago))
