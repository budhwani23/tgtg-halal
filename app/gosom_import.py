"""Free halal evidence from github.com/gosom/google-maps-scraper (no API key, no billing).

Two kinds of scraper runs feed this module:
  * store runs - one query per TGTG store, tagged "<name>, <address> #!#<store_id>", so
                 each result maps back to exactly one store. Gives the store's Maps
                 description, category and ~5 reviews (the same evidence Places gives).
  * area runs  - queries like "halal Bahnhofsviertel Frankfurt"; the places Google
                 returns there count as "appears in Google's halal search".

Note: scraping Google Maps is against Google's terms of service. It is opt-in here.
"""
import json
import subprocess
from pathlib import Path

from . import config, db

IMAGE = "gosom/google-maps-scraper:latest"
SCRAPER_DIR = config.DATA_DIR / "scraper"

FRANKFURT_DISTRICTS = [
    "Bahnhofsviertel", "Innenstadt", "Sachsenhausen", "Bockenheim", "Nordend", "Ostend", "Gallus",
    "Bornheim", "Höchst", "Rödelheim", "Griesheim", "Fechenheim", "Niederrad", "Westend", "Hausen",
    "Preungesheim",
]


def _halal_strings(node):
    """Every enabled 'about' option (or other string) that mentions halal."""
    if isinstance(node, dict):
        if node.get("enabled") is False:
            return []
        return [s for v in node.values() for s in _halal_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _halal_strings(v)]
    if isinstance(node, str) and "halal" in node.lower():
        return [node]
    return []


def load_records(path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def to_place(rec: dict) -> dict:
    """Shape a scraped record like a Places API result so halal.score_store can read it."""
    reviews = []
    for r in (rec.get("user_reviews") or []) + (rec.get("user_reviews_extended") or []):
        text = r.get("Description") or r.get("description") or ""
        if text:
            reviews.append({"text": {"text": text}})
    return {
        "id": rec.get("place_id") or rec.get("cid"),
        "displayName": {"text": rec.get("title") or ""},
        "types": [c for c in (rec.get("categories") or [rec.get("category")]) if c],
        "editorialSummary": {"text": rec.get("description") or ""},
        "reviews": reviews,
        "googleMapsUri": rec.get("link"),
        "about_halal": _halal_strings(rec.get("about") or []),
    }


MAX_MATCH_M = 300


def _best_per_store(records: list[dict], stores: dict) -> list[dict]:
    """A store query can return several places; keep the one nearest the TGTG location."""
    from .google_places import haversine_m

    best: dict[str, tuple[float, dict]] = {}
    for rec in records:
        sid = rec.get("input_id")
        s = stores.get(sid)
        lat, lng = rec.get("latitude"), rec.get("longitude", rec.get("longtitude"))
        if not s or s["lat"] is None or lat is None or lng is None:
            continue
        d = haversine_m(s["lat"], s["lng"], lat, lng)
        if d <= MAX_MATCH_M and (sid not in best or d < best[sid][0]):
            best[sid] = (d, rec)
    return [rec for _, rec in best.values()]


def import_file(path, kind: str) -> int:
    """kind: 'store' (input_id = TGTG store_id) or 'area' (halal search results)."""
    n = 0
    with db.connect() as conn:
        stores = {r["store_id"]: dict(r) for r in conn.execute("SELECT store_id, lat, lng FROM stores")}
        records = load_records(path)
        if kind == "store":
            records = _best_per_store(records, stores)
        for rec in records:
            store_id = rec.get("input_id") if kind == "store" else None
            place = to_place(rec)
            if kind == "store":  # one scraped place per store
                conn.execute("DELETE FROM scraped_places WHERE store_id=? AND kind='store'", (store_id,))
            conn.execute(
                "INSERT OR REPLACE INTO scraped_places (place_id, store_id, kind, lat, lng, place) VALUES (?,?,?,?,?,?)",
                (place["id"] or f"{kind}:{n}:{rec.get('title')}", store_id, kind,
                 rec.get("latitude"), rec.get("longitude", rec.get("longtitude")), json.dumps(place)),
            )
            n += 1
    return n


def place_for_store(conn, store_id: str) -> dict | None:
    row = conn.execute("SELECT place FROM scraped_places WHERE store_id=? AND kind='store'", (store_id,)).fetchone()
    return json.loads(row["place"]) if row else None


def area_place_ids(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT place_id FROM scraped_places WHERE kind='area'")}


# ---- Running the scraper ----------------------------------------------------------

def write_queries() -> tuple[Path, Path]:
    SCRAPER_DIR.mkdir(parents=True, exist_ok=True)
    area = [f"halal {d} Frankfurt am Main" for d in FRANKFURT_DISTRICTS] + [
        "halal restaurant Frankfurt am Main", "halal metzgerei Frankfurt",
        "halal döner Frankfurt", "halal bäckerei Frankfurt"]
    with db.connect() as conn:
        rows = conn.execute("SELECT store_id, name, address FROM stores").fetchall()
    stores = [f"{r['name'].strip()}, {(r['address'] or '').strip()} #!#{r['store_id']}" for r in rows]
    area_path, store_path = SCRAPER_DIR / "area_queries.txt", SCRAPER_DIR / "store_queries.txt"
    area_path.write_text("\n".join(area) + "\n", encoding="utf-8")
    store_path.write_text("\n".join(stores) + "\n", encoding="utf-8")
    return area_path, store_path


def run_scraper(queries: Path, results: Path, depth: int, concurrency: int = 4, log=print):
    """Run the scraper in Docker. Needs Docker Desktop running."""
    results.unlink(missing_ok=True)
    cmd = ["docker", "run", "--rm", "-v", f"{SCRAPER_DIR.resolve()}:/data", IMAGE,
           "-input", f"/data/{queries.name}", "-results", f"/data/{results.name}", "-json",
           "-lang", "de", "-depth", str(depth), "-c", str(concurrency), "-exit-on-inactivity", "2m"]
    log(f"Running scraper on {queries.name} …")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"Scraper failed ({proc.returncode}): {proc.stderr[-500:]}")
    return results


def scrape_all(log=print) -> dict:
    area_q, store_q = write_queries()
    area_res = run_scraper(area_q, SCRAPER_DIR / "area_results.json", depth=5, log=log)
    store_res = run_scraper(store_q, SCRAPER_DIR / "store_results.json", depth=1, log=log)
    with db.connect() as conn:
        conn.execute("DELETE FROM scraped_places")
    return {"area": import_file(area_res, "area"), "store": import_file(store_res, "store")}
