"""Optional: pull invoices and order emails from your mailbox into the review inbox.

Read-only IMAP (works with Gmail using an App Password). You pick which emails to import,
and every imported file still goes through the normal Home / Gift / Someone else review.
Nothing is sent, deleted or marked as read.
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import db

# no inner quotes: the whole query is sent as one quoted IMAP string (AI_LOG #6)
GMAIL_QUERY = ("newer_than:{days}d (invoice OR receipt OR warranty OR manual OR order OR shipped OR delivered) "
               "(has:attachment OR from:amazon.in OR from:flipkart.com)")
SUBJECT_TERMS = ["invoice", "order", "warranty", "receipt", "manual", "shipped"]


def _dec(s) -> str:
    return str(make_header(decode_header(s or "")))


def connect(host: str, user: str, password: str) -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(host)
    m.login(user, password)
    m.select("INBOX", readonly=True)
    return m


def search(m: imaplib.IMAP4_SSL, host: str, days: int = 365, limit: int = 60) -> list[dict]:
    if "gmail" in host:
        typ, data = m.uid("SEARCH", "X-GM-RAW", f'"{GMAIL_QUERY.format(days=days)}"')
    else:
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        crit = " ".join(["OR"] * (len(SUBJECT_TERMS) - 1) + [f'SUBJECT "{t}"' for t in SUBJECT_TERMS])
        typ, data = m.uid("SEARCH", None, f"(SINCE {since} {crit})")
    uids = (data[0] or b"").split()[-limit:][::-1]
    out = []
    for uid in uids:
        typ, msg_data = m.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODYSTRUCTURE)")
        raw = b"".join(p[1] for p in msg_data if isinstance(p, tuple))
        meta = b" ".join(p if isinstance(p, bytes) else p[0] for p in msg_data)
        hdr = email.message_from_bytes(raw)
        try:
            when = parsedate_to_datetime(hdr["Date"]).date().isoformat()
        except Exception:
            when = ""
        out.append({"uid": uid, "from": _dec(hdr["From"]), "subject": _dec(hdr["Subject"]), "date": when,
                    "attachments": len(re.findall(rb'"(?:application/pdf|image/jpeg|image/png)"', meta, re.I))
                    or len(re.findall(rb'\.pdf"', meta, re.I))})
    return out


def download(m: imaplib.IMAP4_SSL, uid: bytes, dest: Path) -> list[Path]:
    """Save PDF/image attachments; if none, save the email text so the order can still be parsed."""
    dest.mkdir(parents=True, exist_ok=True)
    typ, data = m.uid("FETCH", uid, "(BODY.PEEK[])")
    msg = email.message_from_bytes(data[0][1])
    saved = []
    for part in msg.walk():
        name = part.get_filename()
        if name and re.search(r"\.(pdf|png|jpe?g)$", name, re.I):
            p = dest / f"{uid.decode()}_{re.sub(r'[^A-Za-z0-9._-]', '_', _dec(name))}"
            p.write_bytes(part.get_payload(decode=True))
            saved.append(p)
    if not saved:
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                break
            if part.get_content_type() == "text/html" and not body:
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                body = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\1>", "", html))
        p = dest / f"{uid.decode()}_email.txt"
        p.write_text(f"Subject: {_dec(msg['Subject'])}\nFrom: {_dec(msg['From'])}\nDate: {msg['Date']}\n\n"
                     + re.sub(r"[ \t]+", " ", body))
        saved.append(p)
    return saved


def parse_selection(sel: str, n: int) -> list[int]:
    """'1,3,5-7' -> [0,2,4,5,6]; 'all' -> everything; '' or 'none' -> nothing."""
    sel = sel.strip().lower()
    if sel in ("", "none", "n"):
        return []
    if sel in ("all", "a"):
        return list(range(n))
    idx = set()
    for part in sel.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            idx.update(range(int(a) - 1, int(b)))
        elif part.isdigit():
            idx.add(int(part) - 1)
    return sorted(i for i in idx if 0 <= i < n)


def inbox_folder() -> Path:
    return db.home_dir() / "inbox" / "email"
