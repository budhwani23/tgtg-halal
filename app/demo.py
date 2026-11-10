"""Fictional sample data so the UI can be tried without TGTG or Google accounts."""
import datetime as dt

from . import db, halal
from .tgtg_source import parse_item

CENTER = (50.1075, 8.6680)  # Frankfurt Bahnhofsviertel

# (name, description, category, price, offset, google place stand-in, in halal search)
SAMPLES = [
    ("Sample Grill House", "Fully halal certified (HMC) grill. Bags contain wraps and rice.", "MEAL", 4.50,
     (0.001, 0.002), {"reviews": [{"text": {"text": "Great food and 100% halal, staff very friendly"}}]}, True),
    ("Demo Bakery & Cafe", "Fresh bread and pastries from today.", "BAKED_GOODS", 3.09,
     (-0.002, 0.001), {"reviews": [{"text": {"text": "Tolle Brezeln. Achtung: die belegten Brötchen sind nicht halal."}}]}, False),
    ("Example Döner Corner", "Döner und Pizza bis spät.", "MEAL", 3.99,
     (0.003, -0.002), {"reviews": [{"text": {"text": "Bester Halal-Döner im Viertel"}},
                                   {"text": {"text": "Huge portions, meat is halal"}}]}, True),
    ("Test Supermarket Express", "Mixed groceries close to their date.", "GROCERIES", 3.50,
     (-0.001, -0.003), {"reviews": [{"text": {"text": "Hat einige Halal-Optionen im Kühlregal"}}]}, False),
    ("Placeholder Sushi Bar", "Assorted sushi boxes.", "MEAL", 4.99,
     (0.002, 0.004), {"reviews": [{"text": {"text": "Fresh fish, good value"}}]}, False),
    ("Mock Curry Kitchen", "Curries, rice and naan.", "MEAL", 4.00,
     (-0.003, 0.003), {"editorialSummary": {"text": "Casual spot for halal South Asian curries."}}, True),
]


def _raw(i, name, desc, cat, price, offset):
    now = dt.datetime.now(dt.timezone.utc)
    lat, lng = CENTER[0] + offset[0], CENTER[1] + offset[1]
    return {
        "item": {"item_id": f"demo-item-{i}", "description": desc, "item_category": cat,
                 "item_price": {"code": "EUR", "minor_units": int(price * 100), "decimals": 2},
                 "item_value": {"code": "EUR", "minor_units": int(price * 300), "decimals": 2},
                 "diet_categories": []},
        "store": {"store_id": f"demo-store-{i}", "store_name": name, "description": "",
                  "store_location": {"address": {"address_line": f"{10 + i} Beispielstraße, 60329 Frankfurt am Main"},
                                     "location": {"latitude": lat, "longitude": lng}}},
        "display_name": f"{name} - Surprise Bag",
        "items_available": i % 4,
        "pickup_interval": {"start": (now + dt.timedelta(hours=2)).isoformat(),
                            "end": (now + dt.timedelta(hours=3)).isoformat()},
    }


def load_demo():
    with db.connect() as conn:
        for i, (name, desc, cat, price, off, gplace, in_search) in enumerate(SAMPLES):
            store_row, item_row = parse_item(_raw(i, name, desc, cat, price, off))
            db.upsert_store(conn, store_row)
            db.upsert_item(conn, item_row)
            place = {"id": f"demo-place-{i}", "displayName": {"text": name},
                     "googleMapsUri": "https://maps.google.com/", **gplace}
            result = halal.score_store(store_row, [item_row], place, in_search)
            db.save_halal(conn, store_row["store_id"], result)
            print(f"{result['level']:>8} {result['score']:>5}  {name}")
    print("Demo data loaded. Run: python -m app.cli serve")
