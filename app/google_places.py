"""Google Places API (New) lookups, cached in SQLite to keep the bill down.

Two calls are used:
  * match_place     - find the Google Maps listing for a TGTG store (name + coords),
                      returning its types, editorial summary and up to 5 reviews.
  * halal_place_ids - IDs of places Google returns for "halal food" around a point.
                      Google ranks this search using its own "Halal food" offering
                      attribute, which the API does not expose directly.
"""
import math

import requests

from . import config, db

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
MATCH_FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.location",
    "places.types", "places.primaryType", "places.editorialSummary", "places.reviews",
    "places.googleMapsUri",
])
DAY = 86400


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _search(body: dict, field_mask: str) -> dict:
    if not config.GOOGLE_MAPS_API_KEY:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set (see .env.example)")
    resp = requests.post(SEARCH_URL, json=body, timeout=20, headers={
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": field_mask,
    })
    if resp.status_code != 200:
        raise RuntimeError(f"Places API {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def match_place(conn, name: str, address: str, lat: float, lng: float, max_dist_m: float = 250):
    key = f"match:{name.lower()}|{lat:.5f},{lng:.5f}"
    cached = db.cache_get(conn, key, 30 * DAY)
    if cached is None:
        cached = _search({
            "textQuery": f"{name} {address}".strip(),
            "pageSize": 5,
            "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 300.0}},
        }, MATCH_FIELDS)
        db.cache_put(conn, key, cached)

    best, best_d = None, max_dist_m
    for p in cached.get("places", []):
        loc = p.get("location") or {}
        if "latitude" not in loc:
            continue
        d = haversine_m(lat, lng, loc["latitude"], loc["longitude"])
        if d <= best_d:
            best, best_d = p, d
    return best


def halal_place_ids(conn, lat: float, lng: float, radius_m: float = 5000, pages: int = 3) -> set[str]:
    key = f"halal:{lat:.3f},{lng:.3f}|{int(radius_m)}"
    cached = db.cache_get(conn, key, 7 * DAY)
    if cached is None:
        ids, token = [], None
        for _ in range(pages):
            body = {
                "textQuery": "halal food",
                "pageSize": 20,
                "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                            "radius": float(min(radius_m, 50000))}},
            }
            if token:
                body["pageToken"] = token
            res = _search(body, "places.id,nextPageToken")
            ids += [p["id"] for p in res.get("places", [])]
            token = res.get("nextPageToken")
            if not token:
                break
        cached = ids
        db.cache_put(conn, key, cached)
    return set(cached)
