"""Built-in knowledge: product categories, default warranties and maintenance templates.

Manual-derived schedules take priority; these templates fill the gaps for appliances whose
manual is missing or vague. Costs are rough Indian-market estimates in INR and are editable.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

# name -> keywords, default warranty (months), templates
# template: (title, interval_days, mode, how_to, est_cost_inr, part_query or None)
CATEGORIES: dict[str, dict] = {
    "water_purifier": {
        "keywords": ["ro ", "water purifier", "purifier", "aquaguard", "kent", "pureit", "livpure", "uv+uf"],
        "warranty": 12,
        "tasks": [
            ("Clean storage tank", 90, "DIY", "Unplug, drain the tank, wipe with a soft cloth and clean water. No soap.", 0, None),
            ("Replace sediment pre-filter", 180, "Technician", "Book the brand service visit; usually bundled in an AMC. Sooner if water turns slow or cloudy.", 800, "sediment filter"),
            ("Replace carbon filter", 365, "Technician", "Done during the annual service. Bad taste or smell means it is overdue.", 900, "carbon filter"),
            ("Replace RO membrane", 730, "Technician", "Needed every 2-3 years depending on TDS of input water. Ask the technician to show the TDS reading.", 2500, "RO membrane"),
        ],
    },
    "air_conditioner": {
        "keywords": ["air conditioner", " ac ", "split ac", "window ac", "inverter ac", "daikin", "voltas", "blue star"],
        "warranty": 12,
        "tasks": [
            ("Wash indoor air filters", 30, "DIY", "Power off, lift the front panel, slide out the mesh filters, rinse in water, dry in shade, refit.", 0, None),
            ("Wet service (coil jet wash)", 180, "Technician", "Before summer and after monsoon. Technician cleans coils and drain line. Needs a ladder and pump.", 600, None),
            ("Gas pressure and electricals check", 365, "Technician", "Annual check. Weak cooling even after cleaning usually means low refrigerant.", 500, None),
        ],
    },
    "refrigerator": {
        "keywords": ["refrigerator", "fridge", "double door", "single door"],
        "warranty": 12,
        "tasks": [
            ("Clean condenser coils", 180, "DIY", "Unplug, pull the fridge out, vacuum or brush the coils at the back or bottom.", 0, None),
            ("Clean door gasket and drain hole", 90, "DIY", "Wipe the rubber seal with warm soapy water; clear the drain hole with the cleaning tool.", 0, None),
        ],
    },
    "washing_machine": {
        "keywords": ["washing machine", "front load", "top load", "washer"],
        "warranty": 24,
        "tasks": [
            ("Run drum clean cycle", 30, "DIY", "Empty drum, run the Tub Clean program with descaler or 1 cup white vinegar.", 150, "washing machine descaler"),
            ("Clean drain pump filter", 60, "DIY", "Front loaders: open the small bottom door, keep a tray ready, unscrew and rinse the filter.", 0, None),
            ("Clean inlet hose filter", 180, "DIY", "Turn off the tap, unscrew the hose at the machine, rinse the mesh filter.", 0, None),
        ],
    },
    "water_heater": {
        "keywords": ["geyser", "water heater", "racold", "ao smith", "instant heater"],
        "warranty": 24,
        "tasks": [
            ("Flush tank sediment", 180, "DIY", "Switch off power, close inlet, open drain valve until water runs clear.", 0, None),
            ("Descale and anode rod check", 365, "Technician", "Hard water eats the anode rod. Replacing it on time protects the tank warranty.", 700, "geyser anode rod"),
        ],
    },
    "chimney": {
        "keywords": ["chimney", "kitchen hood", "elica", "faber"],
        "warranty": 12,
        "tasks": [
            ("Clean baffle filters", 30, "DIY", "Soak filters in hot water with dish soap and baking soda for 2 hours, scrub, dry.", 0, None),
            ("Deep clean service", 180, "Technician", "Motor and duct cleaning. Auto-clean models need it less often.", 600, None),
        ],
    },
    "coffee_machine": {
        "keywords": ["espresso", "coffee machine", "coffee maker", "dedica", "nespresso", "delonghi", "de'longhi"],
        "warranty": 12,
        "tasks": [
            ("Clean milk frother and drip tray", 7, "DIY", "Purge steam wand after every use; weekly, soak the frother nozzle and wash the drip tray.", 0, None),
            ("Descale", 90, "DIY", "Use the brand descaler, follow the descale program in the manual. Sooner if the descale light comes on.", 900, "descaler"),
            ("Replace water filter / clean portafilter gasket", 180, "DIY", "Check gasket for cracks if shots leak around the group head.", 600, "water filter"),
        ],
    },
    "headphones": {
        "keywords": ["headphone", "earbuds", "earphone", "tws", "headset", "noise cancellation"],
        "warranty": 12,
        "tasks": [
            ("Clean ear cushions and mesh", 30, "DIY", "Wipe cushions with a slightly damp cloth; dry brush the mesh. Never use alcohol on protein leather.", 0, None),
            ("Top up battery if unused", 90, "DIY", "Lithium batteries age fastest at 0%. Charge to ~60% if stored.", 0, None),
            ("Replace ear pads", 540, "DIY", "Pads flatten and crack after 1.5-2 years. Search with the exact model.", 900, "replacement ear pads"),
        ],
    },
    "phone_tablet": {
        "keywords": ["tablet", "galaxy tab", "ipad", "smartphone", "mobile phone", "iphone", "galaxy s", "redmi"],
        "warranty": 12,
        "tasks": [
            ("Backup and software update", 30, "DIY", "Install pending updates; confirm cloud backup ran in the last month.", 0, None),
            ("Clean ports and check battery health", 180, "DIY", "Blow out the charging port; check battery health in settings.", 0, None),
        ],
    },
    "laptop": {
        "keywords": ["laptop", "notebook", "macbook", "thinkpad", "chromebook"],
        "warranty": 12,
        "tasks": [
            ("Backup and OS update", 30, "DIY", "Run updates and verify your backup can actually be restored.", 0, None),
            ("Dust vents / thermal check", 365, "Technician", "Loud fan or throttling means dust. Repaste for older laptops.", 800, None),
        ],
    },
    "router": {
        "keywords": ["router", "wifi", "wi-fi", "mesh", "tp-link", "netgear", "access point"],
        "warranty": 24,
        "tasks": [
            ("Reboot and check firmware", 30, "DIY", "Log in to the router admin page, apply firmware updates, reboot.", 0, None),
            ("Change Wi-Fi password and review devices", 180, "DIY", "Use `homekeeper net devices` to spot unknown devices first.", 0, None),
        ],
    },
    "vacuum": {
        "keywords": ["vacuum", "robot vacuum", "roborock", "eufy", "dyson"],
        "warranty": 12,
        "tasks": [
            ("Wash filter and empty bin", 14, "DIY", "Rinse washable filter, dry 24h before refitting.", 0, None),
            ("Replace HEPA filter and side brush", 180, "DIY", "Order the kit for your exact model.", 1200, "HEPA filter side brush kit"),
        ],
    },
    "air_purifier": {
        "keywords": ["air purifier", "hepa"],
        "warranty": 12,
        "tasks": [
            ("Wash pre-filter", 14, "DIY", "Vacuum or rinse the outer mesh pre-filter.", 0, None),
            ("Replace HEPA filter", 365, "DIY", "Replace when the filter indicator says so or yearly in polluted cities.", 3000, "HEPA replacement filter"),
        ],
    },
    "inverter": {
        "keywords": ["inverter", "ups", "tubular battery", "luminous", "exide"],
        "warranty": 24,
        "tasks": [
            ("Top up distilled water", 60, "DIY", "Check level indicators, top up with distilled water only.", 60, "distilled water battery"),
            ("Clean terminals", 180, "DIY", "Switch off, clean terminals, apply petroleum jelly.", 0, None),
        ],
    },
    "smoke_detector": {
        "keywords": ["smoke detector", "smoke alarm", "co detector"],
        "warranty": 12,
        "tasks": [
            ("Press test button", 30, "DIY", "Hold the test button until it beeps.", 0, None),
            ("Replace battery", 365, "DIY", "Replace yearly even if it has not chirped.", 150, "9V battery"),
        ],
    },
    "other": {"keywords": [], "warranty": 12, "tasks": [
        ("General inspection", 180, "DIY", "Check cables, clean dust, confirm it still works as expected.", 0, None),
    ]},
}


def guess_category(*texts: str | None) -> str:
    hay = " " + " ".join(t for t in texts if t).lower().replace("’", "'") + " "
    best, score = "other", 0
    for name, cat in CATEGORIES.items():
        s = sum(hay.count(k) for k in cat["keywords"])
        if s > score:
            best, score = name, s
    return best


def amazon_product_url(asin: str) -> str:
    return f"https://www.amazon.in/dp/{asin}"


def amazon_search_url(*terms: str | None) -> str:
    q = " ".join(t for t in terms if t)
    return f"https://www.amazon.in/s?k={quote_plus(q)}"


def support_search_url(brand: str | None, model: str | None = None) -> str:
    q = f"{brand or ''} {model or ''} India customer care service request"
    return f"https://www.google.com/search?q={quote_plus(q.strip())}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "item"
