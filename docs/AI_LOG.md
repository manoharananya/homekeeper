# AI usage log

HomeKeeper was built with an AI coding assistant (Claude) as required by Mini-Project 2.
This log records how AI was used to **generate**, **debug** and **document** the script.
Each debugging entry lists the symptom, what the AI diagnosed, and the fix. Commit messages
reference these entries as `AI_LOG #n`.

## 1. Generation

| Step | Prompt (summary) | Output |
|---|---|---|
| Planning | "Design a console tool that unifies warranty, returns, maintenance and home Wi-Fi checks. I must approve every scanned order because some are gifts." | Module plan, data model, review-queue design |
| Data model | "SQLite schema for products, documents, maintenance tasks, task log, contacts, network log." | `homekeeper/db.py` |
| Extraction | "Parse Amazon.in tax invoices, order-summary pages and scanned packing slips into product fields, offline, no API key." | `homekeeper/extract.py` |
| Review queue | "Group documents of one order into one product, attach manuals by brand/model, and suggest Gift when the shipping name is not mine." | `homekeeper/intake.py` |
| Knowledge base | "Maintenance templates for common Indian home appliances: interval, DIY vs technician, how-to, rough INR cost, replacement part." | `homekeeper/catalog.py` |
| Network | "Speed test vs plan with a no-dependency fallback, ping/jitter/loss, ARP device list with new-device detection." | `homekeeper/netcheck.py` |
| Email | "Read-only IMAP search for invoices where the user picks which emails to import." | `homekeeper/mail.py` |
| CLI | "Menu plus subcommands with rich tables; dashboard as the default screen." | `homekeeper/cli.py` |
| Tests, README | "pytest suite for the core logic; README with quick start, commands, design and limits." | `tests/`, `README.md` |

## 2. Debugging

### #1 Shipping name glued to payment method
- **Symptom:** `ship_to` came out as `"Ananya Manohar Visa"` and `"Daljit Kaur Amazon Pay"` on real Amazon order pages.
- **AI diagnosis:** `pdfplumber` flattens the two-column layout, so the "Payment method" column ends up on the same text line as the name.
- **Fix:** split the line at payment keywords (Visa, Amazon Pay, UPI, EMI...) and keep at most three capitalised words.

### #2 Seller parsed as "Billing Address :"
- **Symptom:** on tax invoices `seller` was the literal header `"Billing Address :"`.
- **AI diagnosis:** "Sold By :" and "Billing Address :" are side-by-side headers, so the regex captured the neighbouring header instead of the next line.
- **Fix:** strip the address headers first, then cut the seller line right after the company suffix (Private Limited / Ltd / LLP).

### #3 OCR misreads on scanned packing slips
- **Symptom:** scanned slips gave `"Galaxy Tab $10"`, `"with Al"` and ASIN `BOFNWNZZ1B`; the ASIN was then picked as the model number.
- **AI diagnosis:** Tesseract confuses `S/$`, `I/l` and `0/O`. ASINs always start with `B0`.
- **Fix:** `fix_ocr()` post-processing for these patterns, and the model-number heuristic now ignores ASIN-like tokens.

### #4 Packing slip titles started with "1 "
- **Symptom:** titles like `"1 Samsung Galaxy Tab..."`.
- **AI diagnosis:** OCR inserts a blank line after the `QTY DESCRIPTION` header, so the "strip quantity on first line" rule ran on the empty line.
- **Fix:** skip blank lines before collecting the title.

### #5 Prices missing or wrong (₹1)
- **Symptom:** the geyser invoice showed "Paid ₹1" and the AC order showed no price.
- **AI diagnosis:** two causes. (a) The table header "Tax Amount Total Amount" matched the `Total Amount` pattern, so the next stray digit was taken as the price. (b) The sample PDFs were drawn in Helvetica, which has no rupee glyph, so `₹` came out as `n` and the `₹?` pattern no longer matched.
- **Fix:** every money pattern now requires a full `1,234.56` amount, and the currency prefix is a tolerant `[^\d\n]{0,5}?` (works for ₹, Rs., INR or garbled OCR). Samples now use a Unicode font.

### #6 Manual tasks glued to headings, plus duplicate tasks
- **Symptom:** a task was titled "CARE AND MAINTENANCE Clean the storage tank every 3 months with a soft..." and "Clean storage tank" appeared twice (once from the manual, once from the template).
- **AI diagnosis:** whitespace, including newlines, was collapsed *before* splitting into sentences, so a heading without a full stop merged with the next line. De-duplication compared only the first word and the exact interval, and 12 months (360 days) does not equal the template's 365.
- **Fix:** wrapped lines are joined only when the next line starts lowercase. Titles stop at the interval phrase. Months are `365/12` days. A template is skipped when it shares a key noun (e.g. "sediment", "membrane", "tank") with a manual task. Sentences mentioning a technician are marked *Technician*.

### #7 "527 days overdue" for older purchases
- **Symptom:** a geyser bought in 2024 showed every task hundreds of days overdue.
- **AI diagnosis:** the first due date was computed from the purchase date, but the tool has no idea whether the job was done since. Huge overdue numbers are noise, not information.
- **Fix:** `first_due()` returns `max(purchase + interval, today)`. Past-due tasks start as "due today" and follow the real schedule once marked done.

### #8 Gmail search quoting
- **Symptom:** caught in AI code review before the first live run. The `X-GM-RAW` search string would be rejected by the server.
- **AI diagnosis:** the Gmail query contained inner double quotes (`"order confirmation"`) inside the quoted IMAP string argument, which breaks IMAP string quoting.
- **Fix:** rewrote the query with single keywords and no inner quotes.

### #9 Invoice titles lost their second line
- **Symptom:** "Racold Eterno Pro 15L ... Geyser, 5 Star," with no model number; the model appeared only on the wrapped second line.
- **AI diagnosis:** the "strip price columns" regex `\s+\d+\s+₹.*` ran *after* joining the lines, so `.*` deleted everything after the first price, including the continuation line.
- **Fix:** price columns are cut per line (`line.split("₹")[0]`) before joining.

### #10 Net check crashed when offline
- **Symptom:** a long traceback (`URLError: Tunnel connection failed: 403`) when speed-test servers were unreachable.
- **AI diagnosis:** the fallback download test was outside any `try` block, so a network failure in the fallback was unhandled.
- **Fix:** the fallback is wrapped too. The check reports "Speed test failed... Are you online?" and still logs ping and packet-loss results.

### #11 Review prompt lost its letters
- **Symptom:** the prompt rendered as `ome  ift  someone else's  kip  dit` instead of `[h]ome [g]ift ...`.
- **AI diagnosis:** `rich` treats `[h]` as a markup tag and silently removes it.
- **Fix:** escaped the brackets (`\[h]ome`).

### #12 `setup --names ... --plan ...` still asked questions
- **Symptom:** non-interactive setup crashed with `EOFError` waiting for the ISP name.
- **AI diagnosis:** each missing flag fell back to an interactive prompt.
- **Fix:** if any flag is passed, setup changes only those values and never prompts.

## 2b. Second review pass (after publishing)

A second AI review ran the tool against deliberately bad input: a corrupt PDF, a screenshot that is not an invoice, the same invoice dropped in twice, and product names instead of ids.

### #13 One corrupt PDF crashed the whole scan
- **Symptom:** `PdfminerException: No /Root object! - Is this really a PDF?` and a traceback. No other file in the inbox was processed.
- **AI diagnosis:** `extract()` assumed every file opens. One bad download (a truncated or HTML "PDF") blocked everything else.
- **Fix:** read errors are caught per file. The file is moved to `inbox/_unreadable/` with a one-line reason, and the scan carries on. Files with no text at all (e.g. a scan without Tesseract installed) get the same treatment, with a hint.

### #14 A random screenshot was added as a "product"
- **Symptom:** with `scan --yes`, a PNG screenshot became product "screenshot".
- **AI diagnosis:** the default suggestion was always Home unless the shipping name differed, even when nothing in the file looked like an invoice.
- **Fix:** if every file in a candidate is `unknown` and there is no order number, the suggestion is **Skip** ("Doesn't look like an invoice, order or manual"). You can still override it.

### #15 Warranty end dates drifted at month ends
- **Symptom:** an item bought on the 31st got a warranty ending on the 28th.
- **AI diagnosis:** the code clamped every day to 28 so it was always valid, which lost up to 3 days of warranty.
- **Fix:** `add_months()` uses `calendar.monthrange`, so 31 Jan + 1 month = 28 Feb, and 15 Mar + 12 months = 15 Mar.

### #16 `order kent` crashed
- **Symptom:** `ValueError: invalid literal for int() with base 10: 'kent'`.
- **AI diagnosis:** `order` only accepted a task id or `p<id>`. Anything else was passed to `int()`.
- **Fix:** `order` accepts a task id, `p<id>` or a product name.

### #17 Duplicate downloads nagged forever
- **Symptom:** after dropping the same invoice twice, the dashboard kept saying "1 new file in inbox".
- **AI diagnosis:** the duplicate was skipped by hash but never moved, so it stayed in the inbox.
- **Fix:** duplicates go to `inbox/_duplicates/` and the scan says so.

Also replaced the deprecated `datetime.utcnow()` in the calendar export.

### #18 First CI run failed after 15 minutes
- **Symptom:** GitHub Actions run #1 showed a red cross after 15m 2s.
- **AI diagnosis:** the annotations showed the code was not the problem. The two Ubuntu jobs ran and only raised warnings. The two macOS jobs said *"The job was not acquired by Runner of type hosted even after multiple attempts"*: GitHub had no free macOS machine (*"Due to capacity constraints..."*), so the run timed out and failed. There were also warnings that `checkout@v4`/`setup-python@v5` use deprecated Node.js 20, and that `ubuntu-latest` is moving to Ubuntu 26.
- **Fix:** CI runs on Linux only, pinned to `ubuntu-24.04`, with a 10-minute timeout. The actions are upgraded to `checkout@v5` and `setup-python@v6`. macOS was already covered by running the tool locally.

## 3. Documentation

The README (problem, features, quick start, command reference, design, limits) and the docstrings were drafted with AI and then checked against the actual behaviour by running every command shown. The README screenshots are generated from the demo by `docs/make_screenshots.py`, so they match the code.
