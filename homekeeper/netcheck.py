"""Home internet health: speed vs what you pay for, reliability, and who is on your network."""
from __future__ import annotations

import platform
import re
import statistics
import subprocess
import time
import urllib.request
from datetime import datetime

from . import db

# first 3 bytes of a MAC address -> maker (small offline list of common home devices)
OUI = {
    "00:17:88": "Philips Hue", "18:B4:30": "Nest", "44:65:0D": "Amazon Echo", "FC:65:DE": "Amazon",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "50:C7:BF": "TP-Link", "A4:2B:B0": "TP-Link",
    "F4:F2:6D": "TP-Link", "3C:84:6A": "TP-Link", "C0:25:E9": "TP-Link", "00:1A:11": "Google",
    "F4:F5:D8": "Google", "3C:5A:B4": "Google", "A4:77:33": "Google", "00:E0:4C": "Realtek",
    "B0:BE:76": "TP-Link", "D8:0D:17": "TP-Link", "70:4F:57": "TP-Link", "8C:85:90": "Apple",
    "F0:18:98": "Apple", "AC:BC:32": "Apple", "3C:22:FB": "Apple", "A8:5C:2C": "Apple",
    "BC:D0:74": "Apple", "28:6C:07": "Xiaomi", "64:09:80": "Xiaomi", "78:11:DC": "Xiaomi",
    "50:EC:50": "Xiaomi", "8C:79:F5": "Samsung", "F4:7B:09": "Samsung", "5C:49:7D": "Samsung",
    "CC:6E:A4": "Samsung", "10:2C:6B": "AMPAK (smart plug/IoT)", "24:0A:C4": "Espressif (IoT)",
    "84:F3:EB": "Espressif (IoT)", "C8:2B:96": "Espressif (IoT)", "D8:F1:5B": "Espressif (IoT)",
    "7C:49:EB": "Xiaomi", "E8:DB:84": "Espressif (IoT)", "00:04:4B": "Nvidia",
}


def speed_test() -> dict:
    """Use speedtest-cli if installed, else a simple timed download."""
    try:
        import speedtest  # type: ignore
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        down = st.download() / 1e6
        up = st.upload(pre_allocate=False) / 1e6
        return {"down_mbps": round(down, 1), "up_mbps": round(up, 1),
                "ping_ms": round(st.results.ping, 1), "method": "speedtest.net"}
    except Exception:
        url = "https://speed.cloudflare.com/__down?bytes=25000000"
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=60) as r:
            n = len(r.read())
        secs = time.time() - t0
        return {"down_mbps": round(n * 8 / secs / 1e6, 1), "up_mbps": None, "ping_ms": None,
                "method": "cloudflare download"}


def ping(host: str = "1.1.1.1", count: int = 10) -> dict:
    flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        out = subprocess.run(["ping", flag, str(count), host], capture_output=True, text=True, timeout=40).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"ping_ms": None, "jitter_ms": None, "loss_pct": None}
    times = [float(x) for x in re.findall(r"time[=<]\s?([\d.]+)", out)]
    loss = re.search(r"([\d.]+)% (?:packet )?loss", out)
    return {
        "ping_ms": round(statistics.mean(times), 1) if times else None,
        "jitter_ms": round(statistics.pstdev(times), 1) if len(times) > 1 else None,
        "loss_pct": float(loss.group(1)) if loss else (100.0 if not times else 0.0),
    }


def run_check(con) -> dict:
    res = {**ping(), **{k: v for k, v in speed_test().items() if v is not None or k != "ping_ms"}}
    plan = db.get_setting(con, "plan_mbps")
    res["plan_mbps"] = plan
    con.execute("INSERT INTO net_log(ts,down_mbps,up_mbps,ping_ms,loss_pct,plan_mbps) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="minutes"), res.get("down_mbps"), res.get("up_mbps"),
                 res.get("ping_ms"), res.get("loss_pct"), plan))
    con.commit()
    return res


def report(con) -> dict | None:
    rows = con.execute("SELECT * FROM net_log ORDER BY ts").fetchall()
    if not rows:
        return None
    downs = [r["down_mbps"] for r in rows if r["down_mbps"]]
    plan = db.get_setting(con, "plan_mbps")
    by_hour: dict[int, list[float]] = {}
    for r in rows:
        if r["down_mbps"]:
            by_hour.setdefault(int(r["ts"][11:13]), []).append(r["down_mbps"])
    hourly = {h: statistics.mean(v) for h, v in by_hour.items()}
    worst = sorted(hourly.items(), key=lambda kv: kv[1])[:3]
    below = [d for d in downs if plan and d < 0.5 * plan]
    return {
        "tests": len(rows), "avg_down": round(statistics.mean(downs), 1) if downs else None,
        "min_down": min(downs) if downs else None, "plan": plan,
        "pct_of_plan": round(100 * statistics.mean(downs) / plan) if plan and downs else None,
        "below_half_plan": len(below),
        "avg_loss": round(statistics.mean([r["loss_pct"] for r in rows if r["loss_pct"] is not None] or [0]), 1),
        "worst_hours": [(f"{h:02d}:00", round(v, 1)) for h, v in worst],
    }


def scan_devices(con) -> list[dict]:
    """Devices your computer has seen on the local network (ARP table). Flags new ones."""
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=20).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        try:
            out = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=20).stdout
        except FileNotFoundError:
            return []
    now = datetime.now().isoformat(timespec="minutes")
    found = []
    for line in out.splitlines():
        ip = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        mac = re.search(r"((?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2})", line)
        if not ip or not mac:
            continue
        m = ":".join(p.zfill(2) for p in re.split("[:-]", mac.group(1))).upper()
        if m in ("FF:FF:FF:FF:FF:FF",) or m.startswith("01:00:5E"):
            continue
        known = con.execute("SELECT * FROM devices WHERE mac=?", (m,)).fetchone()
        vendor = OUI.get(m[:8], "Randomised MAC (phone/laptop privacy)" if int(m[1], 16) & 2 else "Unknown maker")
        if known:
            con.execute("UPDATE devices SET ip=?, last_seen=? WHERE mac=?", (ip.group(1), now, m))
        else:
            con.execute("INSERT INTO devices(mac,ip,vendor,first_seen,last_seen) VALUES (?,?,?,?,?)",
                        (m, ip.group(1), vendor, now, now))
        found.append({"mac": m, "ip": ip.group(1), "vendor": vendor, "label": known["label"] if known else None,
                      "new": known is None})
    con.commit()
    return found
