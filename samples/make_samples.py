"""Generate the fictional sample documents used by `homekeeper demo` and the tests.

They copy the layout of real Amazon.in documents (tax invoice, order-summary page) plus a
product manual and an ISP bill. All names, numbers and addresses are made up.
Run: python samples/make_samples.py
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent


FONT, BOLD = "Helvetica", "Helvetica-Bold"
for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial Unicode.ttf"):
    if Path(path).exists():  # a Unicode font, so the rupee sign survives (Helvetica turns it into 'n')
        pdfmetrics.registerFont(TTFont("Uni", path))
        FONT = BOLD = "Uni"
        break


def pdf(name: str, lines: list[str]):
    c = canvas.Canvas(str(HERE / name), pagesize=A4)
    y = 800
    for ln in lines:
        if ln == "---":
            c.showPage()
            y = 800
            continue
        c.setFont(BOLD if ln.isupper() and len(ln) > 3 else FONT, 10)
        c.drawString(40, y, ln)
        y -= 15
    c.save()


def invoice(name, seller, order, date, item_lines, price, ship_to="Ananya Manohar"):
    pdf(name, [
        "Tax Invoice/Bill of Supply/Cash Memo", "(Original for Recipient)", "",
        "Sold By :", seller, "12 Example Industrial Area, Pune, Maharashtra, 411001", "",
        "Shipping Address :", ship_to, "Flat 4B, Sample Residency, Bengaluru, KARNATAKA, 560001", "",
        f"Order Number: {order}", f"Order Date: {date}", f"Invoice Date : {date}", "",
        "Sl. No Description Unit Price Qty Net Amount Tax Rate Tax Type Tax Amount Total Amount",
        *item_lines, "HSN:84212190", f"TOTAL: ₹0.00₹{price}", "Amount in Words:", "Sample only",
    ])


def order_page(name, placed, order, ship_to, title_lines, sold_by, return_line, total):
    pdf(name, [
        "Order Details", "Order Summary", f"Order placed {placed} Order number {order}",
        "Ship to Payment method Order Summary", f"{ship_to} UPI Item(s) Subtotal: ₹{total}",
        "22 Example Road, Bengaluru Grand Total: ₹" + total, "", "Delivered 5 days later", "Service completed",
        *title_lines, f"Sold by: {sold_by}", return_line, f"₹{total}",
    ])


if __name__ == "__main__":
    invoice("invoice_kent_ro.pdf", "Aqua Retail Private Limited", "408-1234567-1112223", "15.03.2026", [
        "1 KENT Grand Plus 9L RO+UV+UF Water Purifier with TDS Controller, ₹13,982.20 1 ₹13,982.20 18% IGST ₹2,516.80 ₹16,499.00",
        "White, KGP-9L | B0SAMPLE01 ( 1 Year Warranty )"], "16,499.00")
    pdf("manual_kent_grand_plus.pdf", [
        "KENT Grand Plus User Manual", "Model No: KGP-9L", "", "IMPORTANT SAFETY INSTRUCTIONS",
        "Warning: do not connect the purifier to a hot water line.", "Caution: use only genuine KENT filters.", "",
        "CARE AND MAINTENANCE",
        "Clean the storage tank every 3 months with a soft cloth and clean water.",
        "Replace the sediment filter every 6 months for best taste and flow.",
        "Replace the carbon filter once every 12 months.",
        "Get the RO membrane checked by a KENT technician every 2 years.",
        "Clean the outer body with a dry cloth. Do not use detergent.", "",
        "Warranty: warranty of 1 year from the date of purchase.",
        "Service: 1800-000-0000 (sample number)",
    ])
    order_page("order_daikin_ac.pdf", "2 April 2026", "405-7654321-3334445", "Ananya Manohar", [
        "Daikin 1.5 Ton 3 Star Inverter Split AC (Copper, PM 2.5 Filter, FTKL50UV16V,", "White), 1 Year Warranty"],
        "Cool Air Appliances Pvt Ltd", "Return window closed on 12 April 2026", "38,990.00")
    invoice("invoice_racold_geyser.pdf", "Heatwave Distributors LLP", "406-1112223-4445556", "20.11.2024", [
        "1 Racold Eterno Pro 15L Vertical Storage Water Heater Geyser, 5 Star, ₹7,626.27 1 ₹7,626.27 18% IGST ₹1,372.73 ₹8,999.00",
        "ETERNOPRO15 | B0SAMPLE02 ( 2 Years Warranty )"], "8,999.00")
    order_page("order_airfryer_gift.pdf", "8 October 2026", "407-9998887-7776665", "Rohan Mehta", [
        "Philips Essential Air Fryer HD9200/90, 4.1L, Rapid Air Technology,", "Black, 2 Year Warranty"],
        "Kitchen World Retail Private Limited", "Return window closes on 22 November 2026", "6,499.00")
    pdf("isp_bill_oct.pdf", [
        "Airtel Xstream Fiber", "Broadband bill for October 2026", "Account: 00000000 (sample)",
        "Plan: Xstream Fiber 100 Mbps Unlimited", "Data usage: 412 GB", "Amount Payable: Rs. 799.00",
    ])
    print("Samples written to", HERE)
