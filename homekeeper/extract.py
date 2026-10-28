"""Turn a PDF, photo or text file into plain text, then pull out the fields we care about.

Rule based on purpose: it works offline, needs no API key and every guess is shown to
the user for confirmation before anything is saved.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md"}

# --------------------------------------------------------------------------- text


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ocr_image(img) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""
    try:
        return pytesseract.image_to_string(img)
    except Exception:  # tesseract binary missing or failed
        return ""


def read_text(path: Path) -> tuple[str, bool]:
    """Return (text, used_ocr). Scanned PDFs fall back to OCR page by page."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        return path.read_text(errors="ignore"), False
    if ext in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image
            return _ocr_image(Image.open(path)), True
        except Exception:
            return "", True
    if ext == ".pdf":
        import pdfplumber
        parts, used_ocr = [], False
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:6]:  # receipts are short, manuals: first pages are enough
                txt = page.extract_text() or ""
                if len(txt.strip()) < 40:  # image-only page: OCR it
                    used_ocr = True
                    txt = _ocr_image(page.to_image(resolution=250).original)
                parts.append(txt)
        return "\n".join(parts), used_ocr
    return "", False


def fix_ocr(text: str) -> str:
    """Repair common OCR misreads seen on real Amazon.in packing slips."""
    # Amazon ASINs start with B0 (zero), OCR often reads 'BO'
    text = re.sub(r"\bBO([A-Z0-9]{8})\b", r"B0\1", text)
    # 'AI' read as 'Al' in product titles, '$10' for 'S10'
    text = re.sub(r"\bwith Al\b", "with AI", text)
    text = re.sub(r"\$(\d{1,3})\b", r"S\1", text)
    text = text.replace("Wwww.", "www.")
    return text


# --------------------------------------------------------------------------- fields

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "twelve": 12, "a": 1, "an": 1}

KNOWN_BRANDS = [
    "De'Longhi", "Samsung", "LG", "Sony", "JBL", "Bose", "Apple", "Xiaomi", "Redmi", "OnePlus",
    "Kent", "Aquaguard", "Eureka Forbes", "Pureit", "Livpure", "AO Smith", "Havells", "Bajaj",
    "Crompton", "Philips", "Daikin", "Voltas", "Blue Star", "Carrier", "Hitachi", "Panasonic",
    "Whirlpool", "Godrej", "IFB", "Bosch", "Haier", "Prestige", "Faber", "Elica", "Dyson",
    "Mi", "TP-Link", "Netgear", "Asus", "Dell", "HP", "Lenovo", "Racold", "V-Guard", "Luminous",
    "Atomberg", "Usha", "Orient", "Morphy Richards", "Agaro", "Eufy", "Roborock", "Kenstar",
]


@dataclass
class Extracted:
    path: str
    kind: str = "unknown"
    used_ocr: bool = False
    title: str | None = None
    brand: str | None = None
    model: str | None = None
    asin: str | None = None
    serial: str | None = None
    order_id: str | None = None
    seller: str | None = None
    ship_to: str | None = None
    price: float | None = None
    purchase_date: str | None = None
    return_by: str | None = None
    warranty_months: int | None = None
    plan_mbps: float | None = None
    isp: str | None = None
    schedules: list = field(default_factory=list)
    text: str = ""

    def as_dict(self):
        d = asdict(self)
        d.pop("text")
        return d


def parse_date(s: str) -> str | None:
    s = s.strip().rstrip(",.")
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _money(s: str) -> float | None:
    m = re.search(r"([\d,]+(?:\.\d{1,2})?)", s)
    return float(m.group(1).replace(",", "")) if m else None


def classify(text: str) -> str:
    t = text.lower()
    if "packing slip" in t:
        return "packing_slip"
    if "tax invoice" in t or "bill of supply" in t or re.search(r"\binvoice (no|number)\b", t):
        return "invoice"
    if "order placed" in t and "order number" in t:
        return "order_summary"
    if t.startswith("subject:") and re.search(r"\b\d{3}-\d{7}-\d{7}\b|\border\b", t):
        return "order_summary"  # order / shipping confirmation email saved by mail.py
    if re.search(r"broadband|fibre|fiber|internet plan|data usage|isp", t) and "mbps" in t:
        return "isp_bill"
    if re.search(r"user manual|owner'?s manual|instruction manual|operating instructions|user guide", t) \
            or len(re.findall(r"\b(clean|replace|maintenance|warning|caution)\b", t)) >= 4:
        return "manual"
    return "unknown"


def _title(text: str, kind: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    if kind == "invoice":
        # first item row starts with "1 " after the Description header
        try:
            start = next(i for i, ln in enumerate(lines) if ln.lower().startswith("description"))
        except StopIteration:
            start = 0
        for ln in lines[start + 1:]:
            if not out and not re.match(r"^1\s+\S", ln):
                continue
            if re.match(r"^(HSN|TOTAL|Amount in Words)", ln, re.I):
                break
            out.append(re.sub(r"^1\s+", "", ln) if not out else ln)
    elif kind == "packing_slip":
        for i, ln in enumerate(lines):
            if re.match(r"^QTY\s+DESCRIPTION", ln, re.I):
                for nxt in lines[i + 1:]:
                    if not nxt:
                        continue
                    if re.match(r"^(B0|BO|X0)[A-Z0-9]{7,10}$", nxt) or nxt.lower().startswith(("serial", "registered")):
                        break
                    out.append(re.sub(r"^1\s+", "", nxt) if not out else nxt)
                break
    elif kind == "order_summary":
        for i, ln in enumerate(lines):
            if ln.lower().startswith("sold by"):
                j = i - 1
                while j >= 0 and not re.match(r"^(Delivered|Service completed|Arriving|Shipped|Return)", lines[j]):
                    j -= 1
                out = lines[j + 1:i]
                break
    if not out:
        return None
    title = " ".join(out)
    title = re.sub(r"₹\s?[\d,]+\.\d{2}.*?(?=\s[A-Z][a-z]|$)", " ", title)  # strip price columns
    title = re.sub(r"\s+\d+\s+₹.*", "", title)
    title = title.split(" | ")[0]
    title = re.sub(r"\s{2,}", " ", title).strip(" ,(")
    return title or None


def short_name(title: str, brand: str | None) -> str:
    """'JBL New Live 780NC, Advanced Noise ...' -> 'JBL New Live 780NC'."""
    head = re.split(r"[,(|\[]", title)[0].strip()
    words = head.split()
    if len(words) > 6:
        head = " ".join(words[:5])
    model = _model(title, "")
    if model and model.lower() not in head.lower():
        head = f"{head} {model}"
    return head


def _brand(title: str | None, text: str) -> str | None:
    hay = (title or "") + "\n" + text[:1500]
    norm = hay.replace("’", "'")
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(b)}\b", norm, re.I):
            return b
    if title:
        return title.split()[0].replace("’", "'")
    return None


def _model(title: str | None, text: str) -> str | None:
    m = re.search(r"\bModel(?:\s*(?:No\.?|Number|Name))?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/ ]{2,20}?)(?:\s{2,}|\n|,|$)", text, re.I)
    if m:
        return m.group(1).strip()
    if title:
        # tokens mixing letters and digits, e.g. EC890M, S10, 780NC, RT28
        cands = re.findall(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]{1,11}\b", title)
        cands = [c for c in cands if not re.match(r"^(\d+(GB|TB|MP|H|W|L|MM|CM|HZ|MAH)|B[0O][A-Z0-9]{7,10}|X0[A-Z0-9]{8}|BT|IP\d\d)$", c, re.I)]
        if cands:
            return max(cands, key=len) if len(cands) > 1 and any(len(c) >= 5 for c in cands) else cands[0]
    return None


INTERVAL_RE = re.compile(
    r"(?:every|once (?:in|every)|at least once (?:in|every)|once a)\s+"
    r"(?P<n>\d+|one|two|three|four|six|twelve|a|an)?\s*(?P<unit>day|week|month|year)s?",
    re.I,
)
ACTION_RE = re.compile(r"\b(clean|replace|change|descale|service|servic|inspect|check|wash|flush|lubricate|oil|test|top up)\w*", re.I)


GENERIC = {"the", "and", "with", "for", "filter", "every", "once", "months", "month", "year", "years",
           "clean", "replace", "change", "check", "checked", "service", "your", "from", "best", "get", "unit"}


def _join_wrapped(text: str) -> str:
    """Join lines that are a wrapped continuation (next line starts lowercase); keep real breaks."""
    return re.sub(r"\n(?=[a-z(])", " ", text)


def find_schedules(text: str) -> list[dict]:
    """Sentences like 'Replace the sediment filter every 6 months' -> task + interval in days."""
    found, seen = [], set()
    for sent in re.split(r"(?<=[.!?])\s+|\n|\s•\s", _join_wrapped(text)):
        sent = re.sub(r"\s+", " ", sent).strip(" -•*")
        m = INTERVAL_RE.search(sent)
        act = ACTION_RE.search(sent)
        if not m or not act or len(sent) > 220:
            continue
        n_raw = (m.group("n") or "1").lower()
        n = int(n_raw) if n_raw.isdigit() else WORD_NUM.get(n_raw, 1)
        unit = m.group("unit").lower()
        days = {"day": n, "week": 7 * n, "month": round(n * 365 / 12), "year": 365 * n}[unit]
        # title = from the start of the sentence (or the verb) up to the interval phrase
        head = sent[:m.start()].strip(" ,.;:")
        title = re.sub(r"^(please|you should|it is recommended to|we recommend)\s+", "", head, flags=re.I)
        title = re.sub(r"\s+by (?:an? |the )?\w+ technician$", "", title, flags=re.I)
        title = (title[:1].upper() + title[1:])[:70] or sent[:70]
        key = (act.group(0).lower()[:5], days)
        if key in seen:
            continue
        seen.add(key)
        mode = "Technician" if re.search(r"technician|service (?:centre|center|engineer)|authori[sz]ed", sent, re.I) else "DIY"
        found.append({"title": title, "interval_days": days, "how_to": sent, "mode": mode})
    return found


def key_nouns(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", title.lower()) if w not in GENERIC}


def extract(path: Path) -> Extracted:
    path = Path(path)
    raw, used_ocr = read_text(path)
    text = fix_ocr(raw) if used_ocr else raw
    ex = Extracted(path=str(path), used_ocr=used_ocr, text=text)
    ex.kind = classify(text)

    if m := re.search(r"\b(\d{3}-\d{7}-\d{7})\b", text):  # Amazon order id
        ex.order_id = m.group(1)
    elif m := re.search(r"\b(OD\d{12,})\b", text):  # Flipkart order id
        ex.order_id = m.group(1)

    if m := re.search(r"\b(B0[A-Z0-9]{8})\b", text):
        ex.asin = m.group(1)
    if m := re.search(r"Serial\s*(?:No\.?|Number)?\s*[:#]?\s*([A-Z0-9]{6,20})", text, re.I):
        ex.serial = m.group(1)
    seller_text = re.sub(r"(Billing|Shipping) Address\s*:?", "", text)
    if m := re.search(r"Sold\s*by\s*:?\s*\n?\s*([A-Z][^\n]{3,80})", seller_text, re.I):
        seller = m.group(1).strip()
        # invoices put the buyer's name on the same line: cut after the company suffix
        if c := re.search(r"^(.*?\b(?:Private Limited|Pvt\.? Ltd\.?|Limited|Ltd\.?|LLP|Inc\.?))", seller):
            seller = c.group(1)
        ex.seller = seller.strip()

    # dates: purchase
    for pat in (r"Order Date\s*:?\s*([\d./-]{8,10})", rf"Order placed\s+(\d{{1,2}} (?:{MONTHS}) \d{{4}})",
                rf"Packing slip for \S+\s+(\d{{1,2}} (?:{MONTHS}) \d{{4}})", r"Invoice Date\s*:?\s*([\d./-]{8,10})",
                rf"(?:Purchase|Bill|Invoice) date\s*:?\s*(\d{{1,2}} (?:{MONTHS}) \d{{4}})"):
        if m := re.search(pat, text, re.I):
            ex.purchase_date = parse_date(m.group(1))
            if ex.purchase_date:
                break
    if m := re.search(rf"Return window (?:closed|closes) on\s+(\d{{1,2}} (?:{MONTHS}) \d{{4}})", text, re.I):
        ex.return_by = parse_date(m.group(1))

    # money: currency symbol may be ₹, Rs., INR, or garbled by OCR/fonts, so allow any short prefix (AI_LOG #5)
    CUR = r"[^\d\n]{0,5}?"
    for pat in (rf"Grand Total\s*:?{CUR}([\d,]+\.\d{{2}})", rf"Invoice Value\s*:?\s*\n?{CUR}([\d,]+\.\d{{2}})",
                rf"\bTOTAL:{CUR}[\d,]+\.\d{{2}}{CUR}([\d,]+\.\d{{2}})", rf"Total Amount\s*:?{CUR}([\d,]+\.\d{{2}})",
                rf"Amount Payable\s*:?{CUR}([\d,]+\.?\d*)"):
        if m := re.search(pat, text, re.I):
            ex.price = _money(m.group(1))
            break

    # who it was shipped to (used to pre-suggest "gift / someone else")
    m = re.search(r"Ship to[^\n]*\n\s*([^\n]+)", text) or \
        re.search(r"Shipping Address\s*:?\s*\n\s*([^\n]+)", text)
    if m:
        # the next column (payment method) is glued on in extracted text: cut it off
        name = re.split(r"\s+(?:Visa|Mastercard|RuPay|Amazon Pay|UPI|Cash|Pay on|EMI|Net ?Banking|"
                        r"Credit|Debit|HDFC|ICICI|SBI|Axis|Item)\b", m.group(1))[0]
        words = re.findall(r"[A-Z][a-zA-Z.]+", name)[:3]
        ex.ship_to = " ".join(words) or None

    # warranty
    if m := re.search(r"(\d+)\s*(?:Yrs?|Years?)\*?\s*(?:Manufacturer\s*)?Warranty", text, re.I):
        ex.warranty_months = int(m.group(1)) * 12
    elif m := re.search(r"warranty (?:period )?(?:of |: ?|for )?(\d+|one|two|three)\s*(year|month)s?", text, re.I):
        n = m.group(1).lower()
        n = int(n) if n.isdigit() else WORD_NUM[n]
        ex.warranty_months = n * (12 if m.group(2).lower() == "year" else 1)

    ex.title = _title(text, ex.kind)
    if not ex.title and (m := re.search(r'^Subject:.*?(?:order of|ordered|shipped:?|delivered:?)\s*["“]?(.+?)["”]?(?:\.{3}|…)?\s*(?:has been|is|$)',
                                         text, re.I | re.M)):
        ex.title = m.group(1).strip(' "“”')
    if ex.kind == "manual":
        if m := re.search(r"^(.{5,80}?)\s*(?:User Manual|Owner'?s Manual|Instruction Manual|User Guide)", text, re.I | re.M):
            ex.title = m.group(1).strip(" -:")
        ex.schedules = find_schedules(text)
    ex.brand = _brand(ex.title, text)
    ex.model = _model(ex.title, text)

    if ex.kind == "isp_bill":
        if m := re.search(r"(\d{2,4})\s*Mbps", text, re.I):
            ex.plan_mbps = float(m.group(1))
        for isp in ("Airtel", "Jio", "ACT", "BSNL", "Hathway", "Excitel", "Tata Play", "You Broadband", "Spectra"):
            if re.search(rf"\b{isp}\b", text):
                ex.isp = isp
                break
    return ex
