import json
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    store_id     TEXT PRIMARY KEY,
    name         TEXT,
    branch       TEXT,
    description  TEXT,
    address      TEXT,
    lat          REAL,
    lng          REAL,
    website      TEXT,
    updated_at   REAL
);
CREATE TABLE IF NOT EXISTS items (
    item_id          TEXT PRIMARY KEY,
    store_id         TEXT REFERENCES stores(store_id),
    display_name     TEXT,
    description      TEXT,
    category         TEXT,
    diet_categories  TEXT,
    price            REAL,
    value            REAL,
    currency         TEXT,
    items_available  INTEGER,
    pickup_start     TEXT,
    pickup_end       TEXT,
    picture_url      TEXT,
    raw              TEXT,
    updated_at       REAL
);
CREATE TABLE IF NOT EXISTS halal (
    store_id    TEXT PRIMARY KEY REFERENCES stores(store_id),
    score       REAL,
    level       TEXT,
    evidence    TEXT,
    place_id    TEXT,
    place_name  TEXT,
    maps_uri    TEXT,
    checked_at  REAL
);
CREATE TABLE IF NOT EXISTS google_cache (
    key         TEXT PRIMARY KEY,
    response    TEXT,
    fetched_at  REAL
);
CREATE TABLE IF NOT EXISTS scraped_places (
    place_id    TEXT,
    store_id    TEXT,
    kind        TEXT,
    lat         REAL,
    lng         REAL,
    place       TEXT,
    PRIMARY KEY (place_id, kind)
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_store(conn, s: dict):
    conn.execute(
        """INSERT INTO stores (store_id, name, branch, description, address, lat, lng, website, updated_at)
           VALUES (:store_id, :name, :branch, :description, :address, :lat, :lng, :website, :updated_at)
           ON CONFLICT(store_id) DO UPDATE SET
             name=excluded.name, branch=excluded.branch, description=excluded.description,
             address=excluded.address, lat=excluded.lat, lng=excluded.lng,
             website=excluded.website, updated_at=excluded.updated_at""",
        {**s, "updated_at": time.time()},
    )


def upsert_item(conn, i: dict):
    row = {**i, "diet_categories": json.dumps(i.get("diet_categories") or []),
           "raw": json.dumps(i.get("raw") or {}), "updated_at": time.time()}
    conn.execute(
        """INSERT INTO items (item_id, store_id, display_name, description, category, diet_categories,
                              price, value, currency, items_available, pickup_start, pickup_end,
                              picture_url, raw, updated_at)
           VALUES (:item_id, :store_id, :display_name, :description, :category, :diet_categories,
                   :price, :value, :currency, :items_available, :pickup_start, :pickup_end,
                   :picture_url, :raw, :updated_at)
           ON CONFLICT(item_id) DO UPDATE SET
             store_id=excluded.store_id, display_name=excluded.display_name,
             description=excluded.description, category=excluded.category,
             diet_categories=excluded.diet_categories, price=excluded.price, value=excluded.value,
             currency=excluded.currency, items_available=excluded.items_available,
             pickup_start=excluded.pickup_start, pickup_end=excluded.pickup_end,
             picture_url=excluded.picture_url, raw=excluded.raw, updated_at=excluded.updated_at""",
        row,
    )


def save_halal(conn, store_id: str, result: dict):
    conn.execute(
        """INSERT INTO halal (store_id, score, level, evidence, place_id, place_name, maps_uri, checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(store_id) DO UPDATE SET
             score=excluded.score, level=excluded.level, evidence=excluded.evidence,
             place_id=excluded.place_id, place_name=excluded.place_name,
             maps_uri=excluded.maps_uri, checked_at=excluded.checked_at""",
        (store_id, result["score"], result["level"], json.dumps(result["evidence"]),
         result.get("place_id"), result.get("place_name"), result.get("maps_uri"), time.time()),
    )


def cache_get(conn, key: str, max_age_s: float):
    row = conn.execute("SELECT response, fetched_at FROM google_cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row["fetched_at"] < max_age_s:
        return json.loads(row["response"])
    return None


def cache_put(conn, key: str, response):
    conn.execute(
        "INSERT OR REPLACE INTO google_cache (key, response, fetched_at) VALUES (?, ?, ?)",
        (key, json.dumps(response), time.time()),
    )


def listings(conn):
    """Every item joined with its store and halal verdict, newest data first."""
    rows = conn.execute(
        """SELECT i.*, s.name AS store_name, s.branch, s.address, s.lat, s.lng, s.website,
                  h.score AS halal_score, h.level AS halal_level, h.evidence AS halal_evidence,
                  h.place_name, h.maps_uri, h.checked_at
           FROM items i JOIN stores s ON s.store_id = i.store_id
           LEFT JOIN halal h ON h.store_id = s.store_id
           ORDER BY i.updated_at DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("raw", None)
        d["diet_categories"] = json.loads(d["diet_categories"] or "[]")
        d["halal_evidence"] = json.loads(d["halal_evidence"] or "[]")
        d["halal_level"] = d["halal_level"] or "unchecked"
        out.append(d)
    return out
