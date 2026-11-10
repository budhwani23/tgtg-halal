"""Runs the halal check for every stored TGTG store."""
import json
import time

from . import config, db, google_places, gosom_import, halal

RECHECK_AFTER_S = 14 * 86400


def _items_for(conn, store_id):
    rows = conn.execute("SELECT display_name, description, diet_categories FROM items WHERE store_id=?",
                        (store_id,)).fetchall()
    return [{**dict(r), "diet_categories": json.loads(r["diet_categories"] or "[]")} for r in rows]


def enrich_all(force: bool = False, use_google: bool | None = None, log=print) -> dict:
    use_google = bool(config.GOOGLE_MAPS_API_KEY) if use_google is None else use_google
    if not use_google:
        log("No Google API key: using TGTG text plus scraped Google Maps data (if scraped).")
    counts = {}
    halal_ids_by_area: dict[tuple, set] = {}
    with db.connect() as conn:
        scraped_area_ids = gosom_import.area_place_ids(conn)
        stores = conn.execute(
            """SELECT s.* FROM stores s LEFT JOIN halal h ON h.store_id = s.store_id
               WHERE ? OR h.checked_at IS NULL OR h.checked_at < ?""",
            (force, time.time() - RECHECK_AFTER_S),
        ).fetchall()
        log(f"Checking {len(stores)} store(s)")
        for s in stores:
            store = dict(s)
            place, in_search = None, False
            if use_google and store["lat"] is not None:
                try:
                    place = google_places.match_place(conn, store["name"], store["address"], store["lat"], store["lng"])
                    area = (round(store["lat"], 2), round(store["lng"], 2))  # ~1 km cells
                    if area not in halal_ids_by_area:
                        halal_ids_by_area[area] = google_places.halal_place_ids(conn, *area, radius_m=2000)
                    in_search = bool(place) and place["id"] in halal_ids_by_area[area]
                except RuntimeError as e:
                    log(f"  Google lookup failed for {store['name']}: {e}")
            scraped = gosom_import.place_for_store(conn, store["store_id"])
            if place is None and scraped:  # free fallback: the scraped Maps listing
                place = scraped
            if scraped and scraped["id"] in scraped_area_ids:
                in_search = True
            hits = (scraped or {}).get("about_halal") or []
            result = halal.score_store(store, _items_for(conn, store["store_id"]), place, in_search, hits)
            db.save_halal(conn, store["store_id"], result)
            conn.commit()
            counts[result["level"]] = counts.get(result["level"], 0) + 1
            log(f"  {result['level']:>8}  {result['score']:>5}  {store['name']}")
    return counts
