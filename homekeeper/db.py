"""SQLite storage. Everything HomeKeeper knows lives in one file: <home>/homekeeper.db."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    brand           TEXT,
    model           TEXT,
    category        TEXT,
    asin            TEXT,
    serial          TEXT,
    order_id        TEXT,
    seller          TEXT,
    price           REAL,
    purchase_date   TEXT,
    return_by       TEXT,
    warranty_months INTEGER,
    warranty_end    TEXT,
    room            TEXT,
    notes           TEXT,
    created         TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    kind        TEXT,          -- invoice | order_summary | packing_slip | manual | isp_bill | unknown
    path        TEXT,
    sha256      TEXT UNIQUE,
    decision    TEXT,          -- home | gift | other | skip
    added       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY,
    product_id    INTEGER REFERENCES products(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    interval_days INTEGER NOT NULL,
    mode          TEXT,        -- DIY | Technician
    how_to        TEXT,
    est_cost      REAL,
    part_query    TEXT,
    order_url     TEXT,
    source        TEXT,        -- manual | template | user
    last_done     TEXT,
    next_due      TEXT
);
CREATE TABLE IF NOT EXISTS task_log (
    id       INTEGER PRIMARY KEY,
    task_id  INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    done_on  TEXT,
    cost     REAL,
    by_whom  TEXT,
    note     TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    name       TEXT,
    phone      TEXT,
    url        TEXT,
    notes      TEXT
);
CREATE TABLE IF NOT EXISTS net_log (
    id        INTEGER PRIMARY KEY,
    ts        TEXT,
    down_mbps REAL,
    up_mbps   REAL,
    ping_ms   REAL,
    loss_pct  REAL,
    plan_mbps REAL
);
CREATE TABLE IF NOT EXISTS devices (
    mac        TEXT PRIMARY KEY,
    ip         TEXT,
    vendor     TEXT,
    label      TEXT,
    first_seen TEXT,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def home_dir() -> Path:
    """Data folder. Override with the HOMEKEEPER_HOME environment variable."""
    root = Path(os.environ.get("HOMEKEEPER_HOME", Path.home() / "HomeKeeper")).expanduser()
    for sub in ("inbox", "vault", "exports"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(home_dir() / "homekeeper.db")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(con, key, value):
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value)))
    con.commit()


def today() -> date:
    """Single place for 'today', so tests and the demo can freeze time."""
    fixed = os.environ.get("HOMEKEEPER_TODAY")
    return date.fromisoformat(fixed) if fixed else date.today()
