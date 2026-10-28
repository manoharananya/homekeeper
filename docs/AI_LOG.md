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
