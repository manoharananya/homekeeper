"""Console interface. Run with no arguments for the interactive menu, or use subcommands."""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from . import __version__, catalog, db, export, intake, netcheck, tracker

console = Console()
INR = lambda x: f"₹{x:,.0f}" if x is not None else "-"


def days_txt(n: int | None) -> str:
    if n is None:
        return "-"
    if n < 0:
        return f"[red]{-n}d overdue[/]"
    if n == 0:
        return "[yellow]today[/]"
    return f"[yellow]in {n}d[/]" if n <= 7 else f"in {n}d"


def pick_product(con, ref: str):
    p = tracker.find_product(con, ref)
    if isinstance(p, list):
        console.print(f"[yellow]'{ref}' matches several products:[/] " + ", ".join(f"{r['id']}={r['name']}" for r in p))
        return None
    if not p:
        console.print(f"[red]No product matching '{ref}'.[/] Try `homekeeper list`.")
    return p


# --------------------------------------------------------------------------- setup


def cmd_setup(con, args):
    flags_given = any(v is not None for v in (args.names, args.plan, args.isp))
    if flags_given:  # non-interactive: only change what was passed (AI_LOG #12)
        if args.names:
            db.set_setting(con, "owner_names", [n.strip() for n in args.names.split(",") if n.strip()])
        if args.plan is not None:
            db.set_setting(con, "plan_mbps", float(args.plan))
        if args.isp:
            db.set_setting(con, "isp", args.isp)
        console.print("[green]Settings saved.[/]")
        return
    names = args.names or Prompt.ask("Your name(s) as they appear on orders (comma separated)",
                                     default=", ".join(db.get_setting(con, "owner_names", [])) or None)
    db.set_setting(con, "owner_names", [n.strip() for n in names.split(",") if n.strip()])
    plan = args.plan if args.plan is not None else Prompt.ask(
        "Internet plan speed in Mbps (from your ISP bill, blank to skip)", default=str(db.get_setting(con, "plan_mbps") or ""))
    if str(plan).strip():
        db.set_setting(con, "plan_mbps", float(plan))
    isp = args.isp or Prompt.ask("Internet provider (optional)", default=db.get_setting(con, "isp") or "")
    if isp:
        db.set_setting(con, "isp", isp)
    console.print(f"[green]Saved.[/] Drop invoices and manuals into [bold]{db.home_dir() / 'inbox'}[/] and run "
                  "[bold]homekeeper scan[/].")


# --------------------------------------------------------------------------- scan / review


def _show_candidate(i: int, n: int, f: dict, cand: intake.Candidate, why: str):
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim")
    t.add_column()
    w = f"{f['warranty_months']} months" + (" [dim](assumed default for category)[/]" if f.get("warranty_assumed") else "")
    rows = [("Category", f["category"].replace("_", " ")), ("Brand / model", f"{f.get('brand') or '-'} / {f.get('model') or '-'}"),
            ("Order", f.get("order_id") or "-"), ("Bought", f.get("purchase_date") or "-"),
            ("Paid", INR(f.get("price"))), ("Seller", f.get("seller") or "-"),
            ("Shipped to", f.get("ship_to") or "-"), ("Return by", f.get("return_by") or "-"), ("Warranty", w),
            ("Serial", f.get("serial") or "-"),
            ("Files", ", ".join(f"{d.kind}{' (OCR)' if d.used_ocr else ''}" for d in cand.docs) or "-")]
    if cand.manuals:
        n_s = sum(len(m.schedules) for m in cand.manuals)
        rows.append(("Manual", f"yes, {n_s} maintenance schedule(s) found"))
    for k, v in rows:
        t.add_row(k, str(v))
    console.print(Panel(t, title=f"[bold]{i}/{n}  {f['name']}[/]", expand=False))
    colour = "yellow" if "not you" in why else "green"
    console.print(f"  [{colour}]Suggestion: {why}[/]")


def _edit(f: dict):
    f["name"] = Prompt.ask("Name", default=f["name"])
    f["category"] = Prompt.ask("Category", choices=list(catalog.CATEGORIES), default=f["category"])
    f["warranty_months"] = IntPrompt.ask("Warranty (months)", default=int(f["warranty_months"] or 12))
    f["purchase_date"] = Prompt.ask("Purchase date (YYYY-MM-DD)", default=f.get("purchase_date") or db.today().isoformat())
    f["room"] = Prompt.ask("Room (optional)", default=f.get("room") or "") or None
    f.pop("warranty_assumed", None)


def cmd_scan(con, args):
    owners = db.get_setting(con, "owner_names", [])
    if not owners and not args.yes:
        console.print("[yellow]Tip:[/] run [bold]homekeeper setup[/] first so I can spot gifts and orders for others.")
    with console.status("Reading new files in the inbox..."):
        cands, bills = intake.scan_inbox(con)
    if not cands and not bills:
        console.print(f"Inbox is empty. Drop PDFs or photos into [bold]{db.home_dir() / 'inbox'}[/].")
        return
    console.print(f"Found [bold]{len(cands)}[/] item(s) to review. You decide what goes in the tracker.\n")
    added = 0
    for i, cand in enumerate(cands, 1):
        if not cand.docs:  # a manual on its own
            man = cand.manuals[0]
            pid = getattr(man, "matched_product_id", None)
            label = man.title or Path(man.path).name
            if pid:
                p = con.execute("SELECT name FROM products WHERE id=?", (pid,)).fetchone()
                q = f"Manual '{label}' looks like it belongs to [bold]{p['name']}[/]. Attach it?"
                if args.yes or Confirm.ask(q, default=True):
                    intake.attach_manual(con, man, pid)
                    console.print(f"  [green]Attached[/], {len(man.schedules)} schedule(s) added from the manual.")
                    continue
            if args.yes:
                intake.set_aside(con, cand, "skip")
                continue
            ref = Prompt.ask(f"Manual '{label}': which product is it for? (id/name, [bold]n[/]=new product, "
                             "[bold]s[/]=skip)", default="s")
            if ref.lower() == "s":
                intake.set_aside(con, cand, "skip")
            elif ref.lower() == "n":
                f = cand.fields
                _edit(f)
                intake.save_product(con, f, cand)
                added += 1
            elif (p := pick_product(con, ref)):
                intake.attach_manual(con, man, p["id"])
            continue

        f = cand.fields
        decision, why = intake.suggest(f, owners)
        _show_candidate(i, len(cands), f, cand, why)
        if args.yes:
            choice = decision[0]
        else:
            # square brackets are Rich markup, so they must be escaped (AI_LOG #11)
            choice = Prompt.ask(r"\[h]ome  \[g]ift  \[o] someone else's  \[s]kip  \[e]dit then add",
                                choices=["h", "g", "o", "s", "e"], default=decision[0])
        if choice == "e":
            _edit(f)
            choice = "h"
        if choice == "h":
            pid = intake.save_product(con, f, cand)
            added += 1
            n_tasks = con.execute("SELECT COUNT(*) FROM tasks WHERE product_id=?", (pid,)).fetchone()[0]
            console.print(f"  [green]Added #{pid}[/] with {n_tasks} maintenance task(s). Files moved to the vault.\n")
        else:
            intake.set_aside(con, cand, {"g": "gift", "o": "other", "s": "skip"}[choice])
            console.print("  [dim]Set aside. It won't be asked about again.[/]\n")
    for b in bills:
        msg = f"ISP bill found: {b.isp or 'provider'} plan {b.plan_mbps or '?'} Mbps. Use as your plan speed?"
        if b.plan_mbps and (args.yes or Confirm.ask(msg, default=True)):
            db.set_setting(con, "plan_mbps", b.plan_mbps)
            if b.isp:
                db.set_setting(con, "isp", b.isp)
        intake.record_doc(con, b, "home", None, intake._file_into_vault(b.path, "_internet"))
        con.commit()
    console.print(f"[bold green]Done.[/] {added} product(s) added. Run [bold]homekeeper[/] to see the dashboard.")


# --------------------------------------------------------------------------- views


def cmd_dash(con, args):
    today = db.today()
    n_products = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    inbox = db.home_dir() / "inbox"
    waiting = sum(1 for p in inbox.rglob("*") if p.is_file() and p.suffix.lower() in intake.SUPPORTED)
    head = f"[bold]HomeKeeper[/]  {today:%a %d %b %Y}   {n_products} products tracked"
    if waiting:
        head += f"   [yellow]{waiting} new file(s) in inbox: run `scan`[/]"
    console.print(Panel(head, expand=False))

    due = tracker.due_tasks(con, args.days if hasattr(args, "days") else 30, today)
    t = Table(title="Maintenance due (next 30 days)", title_justify="left", show_lines=False)
    for c in ("ID", "Product", "Task", "When", "Who", "Est."):
        t.add_column(c)
    for r, left in due:
        t.add_row(str(r["id"]), r["product"], r["title"], days_txt(left), r["mode"], INR(r["est_cost"]) if r["est_cost"] else "-")
    console.print(t if due else "[green]No maintenance due in the next 30 days.[/]")

    alerts = []
    for p in con.execute("SELECT * FROM products"):
        ws, wl = tracker.warranty_status(p, today)
        rs, rl = tracker.return_status(p, today)
        if rs == "open":
            alerts.append(f"[yellow]Return window[/] for {p['name']} closes {days_txt(rl)} ({p['return_by']})")
        if ws == "expiring" or (ws == "active" and wl <= 60):
            alerts.append(f"[yellow]Warranty[/] for {p['name']} ends {days_txt(wl)}. Get pending issues fixed. "
                          f"`claim {p['id']}`")
    for a in alerts:
        console.print(" • " + a)

    last = con.execute("SELECT * FROM net_log ORDER BY ts DESC LIMIT 1").fetchone()
    if last and last["down_mbps"]:
        plan = last["plan_mbps"]
        pct = f" ({last['down_mbps'] / plan:.0%} of your {plan:.0f} Mbps plan)" if plan else ""
        console.print(f" • Internet: last test {last['down_mbps']} Mbps{pct} on {last['ts'].replace('T', ' ')}")
    console.print("\n[dim]Commands: scan · list · show <id> · done <task> · order <task> · warranty · claim <id> · "
                  "net check · export · menu[/]")


def cmd_list(con, args):
    t = Table(title="Your products")
    for c in ("ID", "Name", "Category", "Bought", "Paid", "Warranty", "Next task"):
        t.add_column(c)
    for p in con.execute("SELECT * FROM products ORDER BY id"):
        ws, wl = tracker.warranty_status(p)
        wtxt = {"active": f"[green]until {p['warranty_end']}[/]", "expiring": f"[yellow]{wl}d left[/]",
                "expired": "[red]expired[/]", "unknown": "-"}[ws]
        nt = con.execute("SELECT title,next_due FROM tasks WHERE product_id=? ORDER BY next_due LIMIT 1", (p["id"],)).fetchone()
        t.add_row(str(p["id"]), p["name"], (p["category"] or "").replace("_", " "), p["purchase_date"] or "-",
                  INR(p["price"]), wtxt, f"{nt['title']} ({nt['next_due']})" if nt else "-")
    console.print(t)


def cmd_show(con, args):
    p = pick_product(con, args.product)
    if not p:
        return
    ws, wl = tracker.warranty_status(p)
    info = (f"[bold]{p['name']}[/]  #{p['id']}\n{p['notes'] or ''}\n\n"
            f"Brand/model: {p['brand'] or '-'} / {p['model'] or '-'}   Serial: {p['serial'] or '-'}\n"
            f"Bought {p['purchase_date'] or '-'} from {p['seller'] or '-'} for {INR(p['price'])}   Order {p['order_id'] or '-'}\n"
            f"Warranty: {ws} {('(' + str(wl) + ' days left)') if wl and wl > 0 else ''} until {p['warranty_end'] or '-'}"
            f"   Return by: {p['return_by'] or '-'}")
    console.print(Panel(info, expand=False))
    t = Table(title="Maintenance")
    for c in ("ID", "Task", "Every", "Last done", "Next due", "Who", "Est.", "From"):
        t.add_column(c)
    for r in con.execute("SELECT * FROM tasks WHERE product_id=? ORDER BY next_due", (p["id"],)):
        t.add_row(str(r["id"]), r["title"], f"{r['interval_days']}d", r["last_done"] or "-", r["next_due"],
                  r["mode"], INR(r["est_cost"]) if r["est_cost"] else "-", r["source"])
    console.print(t)
    for d in con.execute("SELECT * FROM documents WHERE product_id=?", (p["id"],)):
        console.print(f" [dim]{d['kind']:<14}[/] {d['path']}")
    for c in con.execute("SELECT * FROM contacts WHERE product_id=?", (p["id"],)):
        console.print(f" [dim]contact[/]        {c['name']}: {c['phone'] or ''} {c['url'] or ''}")
    if args.howto:
        for r in con.execute("SELECT * FROM tasks WHERE product_id=? ORDER BY next_due", (p["id"],)):
            console.print(f"\n[bold]{r['title']}[/] ({r['mode']})\n  {r['how_to']}")


def cmd_warranty(con, args):
    t = Table(title="Warranties and return windows")
    for c in ("ID", "Product", "Warranty ends", "Status", "Return by"):
        t.add_column(c)
    rows = sorted(con.execute("SELECT * FROM products"), key=lambda p: p["warranty_end"] or "9999")
    for p in rows:
        ws, wl = tracker.warranty_status(p)
        rs, rl = tracker.return_status(p)
        style = {"active": "green", "expiring": "yellow", "expired": "red"}.get(ws, "dim")
        t.add_row(str(p["id"]), p["name"], p["warranty_end"] or "-",
                  f"[{style}]{ws}{f' ({wl}d)' if wl is not None and wl >= 0 else ''}[/]",
                  f"{p['return_by'] or '-'} {'[yellow](open)[/]' if rs == 'open' else ''}")
    console.print(t)


def cmd_claim(con, args):
    p = pick_product(con, args.product)
    if not p:
        return
    ws, wl = tracker.warranty_status(p)
    docs = con.execute("SELECT kind,path FROM documents WHERE product_id=?", (p["id"],)).fetchall()
    contacts = con.execute("SELECT * FROM contacts WHERE product_id=?", (p["id"],)).fetchall()
    lines = [f"WARRANTY CLAIM PACK: {p['name']}", "",
             f"Product      : {p['notes'] or p['name']}", f"Brand / model: {p['brand'] or '-'} / {p['model'] or '-'}",
             f"Serial no.   : {p['serial'] or '(check the sticker on the product)'}",
             f"Order no.    : {p['order_id'] or '-'}", f"Purchased    : {p['purchase_date'] or '-'} from {p['seller'] or '-'}",
             f"Price paid   : {INR(p['price'])}", f"Warranty     : {p['warranty_months'] or '-'} months, until "
             f"{p['warranty_end'] or '-'} ({ws}{', ' + str(wl) + ' days left' if wl and wl > 0 else ''})", "",
             "Attach these files:"] + [f"  - {d['kind']}: {d['path']}" for d in docs] + ["", "Contact:"] + \
            [f"  - {c['name']}: {c['phone'] or ''} {c['url'] or ''}" for c in contacts] + \
            ["", "Describe: what fails, since when, what you already tried. Ask for a service request (SR) number."]
    text = "\n".join(lines)
    out = db.home_dir() / "exports" / f"claim-{catalog.slug(p['name'])}.txt"
    out.write_text(text)
    console.print(Panel(text, expand=False))
    console.print(f"[green]Saved to[/] {out}")


def cmd_due(con, args):
    args.days = args.days or 30
    due = tracker.due_tasks(con, args.days)
    t = Table(title=f"Due in the next {args.days} days")
    for c in ("ID", "Product", "Task", "When", "Who", "How"):
        t.add_column(c, overflow="fold")
    for r, left in due:
        t.add_row(str(r["id"]), r["product"], r["title"], days_txt(left), r["mode"], (r["how_to"] or "")[:80])
    console.print(t)


def cmd_done(con, args):
    try:
        nxt = tracker.mark_done(con, args.task, args.cost, args.by, args.note,
                                date.fromisoformat(args.on) if args.on else None)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return
    console.print(f"[green]Logged.[/] Next due {nxt}.")


def cmd_order(con, args):
    ref = args.ref
    url = None
    if ref.lower().startswith("p"):
        p = pick_product(con, ref[1:])
        if p:
            url = catalog.amazon_product_url(p["asin"]) if p["asin"] else catalog.amazon_search_url(p["brand"], p["model"] or p["name"])
    else:
        t = con.execute("SELECT t.*, p.brand, p.model, p.name FROM tasks t JOIN products p ON p.id=t.product_id WHERE t.id=?",
                        (int(ref),)).fetchone()
        if not t:
            console.print(f"[red]No task {ref}[/]")
            return
        if not (t["order_url"] or t["part_query"]):
            console.print(f"'{t['title']}' needs no part ({t['mode']}). How to: {t['how_to']}")
            return
        url = t["order_url"] or catalog.amazon_search_url(t["brand"], t["model"], t["part_query"])
    if url:
        console.print(f"Opening {url}\n[dim]You confirm and pay on the site. HomeKeeper never buys anything itself.[/]")
        if not args.print_only:
            webbrowser.open(url)


def cmd_task_add(con, args):
    p = pick_product(con, args.product)
    if not p:
        return
    from datetime import timedelta
    due = (db.today() + timedelta(days=args.every)).isoformat()
    con.execute("INSERT INTO tasks(product_id,title,interval_days,mode,how_to,est_cost,source,next_due) VALUES (?,?,?,?,?,?,?,?)",
                (p["id"], args.title, args.every, args.mode, args.how or "", args.cost, "user", due))
    con.commit()
    console.print(f"[green]Added.[/] First due {due}.")


def cmd_contact_add(con, args):
    p = pick_product(con, args.product)
    if not p:
        return
    con.execute("INSERT INTO contacts(product_id,name,phone,url,notes) VALUES (?,?,?,?,?)",
                (p["id"], args.name, args.phone, args.url, args.notes))
    con.commit()
    console.print("[green]Contact saved.[/]")


def cmd_spend(con, args):
    t = Table(title=f"Upkeep spend {db.today().year}")
    for c in ("Product", "Paid", "Spent this year", "Jobs", "Note"):
        t.add_column(c)
    for r in tracker.spend_by_product(con):
        t.add_row(r["name"], INR(r["price"]), INR(r["spent"]), str(r["jobs"]), tracker.repair_or_replace(r["price"], r["spent"]) or "")
    console.print(t)


# --------------------------------------------------------------------------- network


def cmd_net(con, args):
    if args.action == "check":
        with console.status("Testing ping, packet loss and download speed (about 30s)..."):
            r = netcheck.run_check(con)
        if r.get("error"):
            console.print(f"[red]{r['error']}[/] Ping/packet-loss results were still logged.")
        plan = r.get("plan_mbps")
        verdict = ""
        if plan and r.get("down_mbps"):
            pct = r["down_mbps"] / plan
            colour = "green" if pct >= 0.8 else "yellow" if pct >= 0.5 else "red"
            verdict = f"  [{colour}]{pct:.0%} of the {plan:.0f} Mbps you pay for[/]"
        console.print(f"Download {r.get('down_mbps') or '-'} Mbps{verdict}\nUpload   {r.get('up_mbps') or '-'} Mbps\n"
                      f"Ping     {r.get('ping_ms') or '-'} ms  jitter {r.get('jitter_ms') or '-'} ms  "
                      f"loss {r.get('loss_pct') if r.get('loss_pct') is not None else '-'}%")
        if not plan:
            console.print("[dim]Tip: `homekeeper setup --plan 100` to compare against your plan.[/]")
    elif args.action == "report":
        rep = netcheck.report(con)
        if not rep:
            console.print("No tests yet. Run `homekeeper net check` (or schedule it, see README).")
            return
        console.print(Panel(
            f"Tests logged: {rep['tests']}\nAverage download: {rep['avg_down']} Mbps"
            + (f" = [bold]{rep['pct_of_plan']}%[/] of your {rep['plan']:.0f} Mbps plan" if rep["pct_of_plan"] else "")
            + f"\nSlowest test: {rep['min_down']} Mbps\nTests below half your plan: {rep['below_half_plan']}"
            + f"\nAverage packet loss: {rep['avg_loss']}%\nWorst hours: "
            + ", ".join(f"{h} ({v} Mbps)" for h, v in rep["worst_hours"]),
            title="Internet report (use this as evidence with your ISP)", expand=False))
    elif args.action == "devices":
        devs = netcheck.scan_devices(con)
        if not devs:
            console.print("No devices visible. Open a few apps on the network and retry, or run on the home Wi-Fi.")
            return
        t = Table(title="Devices on your network")
        for c in ("IP", "MAC", "Maker", "Label", ""):
            t.add_column(c)
        for d in devs:
            t.add_row(d["ip"], d["mac"], d["vendor"], d["label"] or "-", "[yellow]NEW[/]" if d["new"] else "")
        console.print(t)
        console.print("[dim]Name a device: homekeeper net label <MAC> \"Living room TV\"[/]")
    elif args.action == "label":
        con.execute("UPDATE devices SET label=? WHERE mac=?", (args.label, args.mac.upper()))
        con.commit()
        console.print("[green]Labelled.[/]")


# --------------------------------------------------------------------------- export / mail / demo


def cmd_export(con, args):
    ics = export.to_ics(con)
    csvp = export.to_csv(con)
    console.print(f"[green]Calendar:[/] {ics}  (import into Google/Apple Calendar for reminders)\n[green]CSV:[/] {csvp}")


def cmd_mail(con, args):
    from getpass import getpass

    from . import mail
    host = args.host or db.get_setting(con, "imap_host") or Prompt.ask("IMAP server", default="imap.gmail.com")
    user = args.user or db.get_setting(con, "imap_user") or Prompt.ask("Email address")
    db.set_setting(con, "imap_host", host)
    db.set_setting(con, "imap_user", user)
    pw = os.environ.get("HOMEKEEPER_IMAP_PASSWORD") or getpass("App password (not stored): ")
    with console.status("Connecting (read-only)..."):
        m = mail.connect(host, user, pw)
        found = mail.search(m, host, args.days)
    if not found:
        console.print("No matching emails.")
        return
    t = Table(title=f"Possible invoices / orders (last {args.days} days)")
    for c in ("#", "Date", "From", "Subject", "Files"):
        t.add_column(c, overflow="fold")
    for i, e in enumerate(found, 1):
        t.add_row(str(i), e["date"], e["from"][:30], e["subject"][:70], str(e["attachments"] or "-"))
    console.print(t)
    sel = Prompt.ask("Import which? e.g. 1,3,5-7 / all / none", default="none")
    picked = mail.parse_selection(sel, len(found))
    n = 0
    for i in picked:
        n += len(mail.download(m, found[i]["uid"], mail.inbox_folder()))
    m.logout()
    console.print(f"[green]{n} file(s) saved to the inbox.[/] Now run [bold]scan[/] to review them (gift / someone else / home).")


def cmd_demo(con_unused, args):
    import shutil
    target = Path(args.home or "homekeeper_demo").resolve()
    if target.exists():
        shutil.rmtree(target)
    os.environ["HOMEKEEPER_HOME"] = str(target)
    con = db.connect()
    samples = Path(__file__).resolve().parent.parent / "samples"
    for f in samples.glob("*"):
        if f.suffix.lower() in intake.SUPPORTED:
            shutil.copy(f, db.home_dir() / "inbox" / f.name)
    db.set_setting(con, "owner_names", ["Ananya Manohar"])
    console.print(Panel(f"Demo home: {target}\nOwner set to 'Ananya Manohar'. Sample invoices, a manual and an ISP bill "
                        "copied to the inbox.\nReview decisions are auto-accepted for the demo.", title="HomeKeeper demo",
                        expand=False))
    cmd_scan(con, argparse.Namespace(yes=True))
    from . import demo_data
    demo_data.seed_network(con)
    console.print()
    cmd_dash(con, argparse.Namespace(days=30))
    console.print(f"\n[bold]Try next[/] (demo data):\n  python -m homekeeper --home {target.name} list\n"
                  f"  python -m homekeeper --home {target.name} show 1 --howto\n"
                  f"  python -m homekeeper --home {target.name} net report\n"
                  f"  python -m homekeeper --home {target.name} claim 1")


# --------------------------------------------------------------------------- menu

MENU = [
    ("Dashboard", "dash"), ("Scan inbox (review new invoices/manuals)", "scan"), ("All products", "list"),
    ("Product details", "show"), ("Maintenance due", "due"), ("Mark a task done", "done"),
    ("Order a part / reorder", "order"), ("Warranties & returns", "warranty"), ("Warranty claim pack", "claim"),
    ("Internet: run check", "net check"), ("Internet: report", "net report"), ("Internet: devices", "net devices"),
    ("Upkeep spend", "spend"), ("Import from email", "mail"), ("Export calendar + CSV", "export"),
    ("Settings", "setup"), ("Quit", "quit"),
]


def menu(con, parser):
    while True:
        console.rule("[bold]HomeKeeper")
        for i, (label, _) in enumerate(MENU, 1):
            console.print(f" [cyan]{i:>2}[/] {label}")
        choice = IntPrompt.ask("Choose", default=1)
        if not 1 <= choice <= len(MENU):
            continue
        cmd = MENU[choice - 1][1]
        if cmd == "quit":
            return
        argv = cmd.split()
        if cmd in ("show", "claim"):
            argv.append(Prompt.ask("Product id or name"))
        elif cmd in ("done", "order"):
            cmd_due(con, argparse.Namespace(days=60))
            argv.append(Prompt.ask("Task id" if cmd == "done" else "Task id (or p<product id> to reorder the product)"))
        try:
            args = parser.parse_args(argv)
            args.func(con, args)
        except SystemExit:
            pass
        except Exception as e:  # keep the menu alive, show the error
            console.print(f"[red]Error:[/] {e}")
        Prompt.ask("\n[dim]Enter to continue[/]", default="", show_default=False)


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="homekeeper", description="Warranties, maintenance and home internet in one console tool.")
    ap.add_argument("--home", help="data folder (default ~/HomeKeeper or $HOMEKEEPER_HOME)")
    ap.add_argument("--version", action="version", version=f"homekeeper {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    def add(name, func, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(func=func)
        return p

    p = add("setup", cmd_setup, "your name(s), internet plan speed, ISP")
    p.add_argument("--names")
    p.add_argument("--plan", type=float)
    p.add_argument("--isp")
    p = add("scan", cmd_scan, "read new files in the inbox and review them")
    p.add_argument("--yes", action="store_true", help="accept suggestions without asking")
    p = add("dash", cmd_dash, "dashboard")
    p.add_argument("--days", type=int, default=30)
    add("list", cmd_list, "all products")
    p = add("show", cmd_show, "one product with tasks, files and contacts")
    p.add_argument("product")
    p.add_argument("--howto", action="store_true", help="print how-to steps for every task")
    add("warranty", cmd_warranty, "warranty and return status")
    p = add("claim", cmd_claim, "print and save a warranty claim pack")
    p.add_argument("product")
    p = add("due", cmd_due, "maintenance due")
    p.add_argument("--days", type=int, default=30)
    p = add("done", cmd_done, "mark a maintenance task done")
    p.add_argument("task", type=int)
    p.add_argument("--cost", type=float)
    p.add_argument("--by", help="who did it, e.g. 'self' or technician name")
    p.add_argument("--note")
    p.add_argument("--on", help="date done, YYYY-MM-DD (default today)")
    p = add("order", cmd_order, "open the order page for a task's part (or p<id> to reorder a product)")
    p.add_argument("ref")
    p.add_argument("--print-only", action="store_true")
    p = add("task", cmd_task_add, "add your own recurring task")
    p.add_argument("product")
    p.add_argument("title")
    p.add_argument("--every", type=int, required=True, help="interval in days")
    p.add_argument("--mode", choices=["DIY", "Technician"], default="DIY")
    p.add_argument("--cost", type=float)
    p.add_argument("--how")
    p = add("contact", cmd_contact_add, "save a service contact for a product")
    p.add_argument("product")
    p.add_argument("name")
    p.add_argument("--phone")
    p.add_argument("--url")
    p.add_argument("--notes")
    add("spend", cmd_spend, "upkeep spend per product this year")
    p = add("net", cmd_net, "internet checks: check | report | devices | label")
    p.add_argument("action", choices=["check", "report", "devices", "label"])
    p.add_argument("mac", nargs="?")
    p.add_argument("label", nargs="?")
    add("export", cmd_export, "calendar (.ics) and CSV export")
    p = add("mail", cmd_mail, "import invoices from email (read-only IMAP, you pick which)")
    p.add_argument("--host")
    p.add_argument("--user")
    p.add_argument("--days", type=int, default=365)
    add("menu", lambda con, a: None, "interactive menu")
    p = add("demo", cmd_demo, "load sample data into ./homekeeper_demo and show the dashboard")
    return ap


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "demo":
        return cmd_demo(None, args)
    if args.home:
        os.environ["HOMEKEEPER_HOME"] = str(Path(args.home).resolve())
    con = db.connect()
    if args.cmd in (None, "menu"):
        if not db.get_setting(con, "owner_names"):
            console.print(Panel("Welcome to HomeKeeper. Quick setup first.", expand=False))
            cmd_setup(con, argparse.Namespace(names=None, plan=None, isp=None))
        cmd_dash(con, argparse.Namespace(days=30))
        if sys.stdin.isatty():
            menu(con, parser)
        return
    args.func(con, args)


if __name__ == "__main__":
    main()
