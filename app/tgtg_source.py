"""Pulls listings from Too Good To Go through the unofficial tgtg-python client.

TGTG has no "give me everything" endpoint: the app only answers "what is near this
point within this radius". To cover a whole city we tile it with overlapping circles
and page through each one.
"""
import json
import math
import time

from . import config, db


def _money(obj):
    if not obj:
        return None, None
    try:
        return obj["minor_units"] / (10 ** obj.get("decimals", 2)), obj.get("code")
    except (KeyError, TypeError):
        return None, None


def parse_item(raw: dict) -> tuple[dict, dict]:
    """Turn one raw TGTG item into (store_row, item_row)."""
    item = raw.get("item") or {}
    store = raw.get("store") or {}
    loc = (store.get("store_location") or {})
    coords = loc.get("location") or {}
    price, currency = _money(item.get("item_price") or item.get("price_including_taxes") or item.get("price"))
    value, _ = _money(item.get("item_value") or item.get("value_including_taxes") or item.get("value"))
    pickup = raw.get("pickup_interval") or {}
    picture = (item.get("cover_picture") or {}).get("current_url") or (store.get("logo_picture") or {}).get("current_url")

    store_row = {
        "store_id": str(store.get("store_id") or item.get("item_id")),
        "name": store.get("store_name") or raw.get("display_name") or "",
        "branch": store.get("branch") or "",
        "description": store.get("description") or "",
        "address": (loc.get("address") or {}).get("address_line") or "",
        "lat": coords.get("latitude"),
        "lng": coords.get("longitude"),
        "website": store.get("website") or "",
    }
    item_row = {
        "item_id": str(item.get("item_id")),
        "store_id": store_row["store_id"],
        "display_name": raw.get("display_name") or item.get("name") or store_row["name"],
        "description": item.get("description") or "",
        "category": item.get("item_category") or "",
        "diet_categories": item.get("diet_categories") or [],
        "price": price,
        "value": value,
        "currency": currency,
        "items_available": raw.get("items_available"),
        "pickup_start": pickup.get("start"),
        "pickup_end": pickup.get("end"),
        "picture_url": picture,
        "raw": raw,
    }
    return store_row, item_row


def login(email: str):
    """Interactive: TGTG emails a PIN, which tgtg-python reads from stdin."""
    from tgtg import TgtgClient

    creds = TgtgClient(url=config.TGTG_BASE_URL, email=email).get_credentials()
    config.CREDENTIALS_PATH.write_text(json.dumps({"email": email, **creds}, indent=2))
    return config.CREDENTIALS_PATH


# --- Two-step login for the web UI -------------------------------------------------
# tgtg-python's login() reads the PIN from stdin, which a web server can't do, so the
# web flow calls the same two endpoints itself and keeps the client (and its DataDome
# cookie) alive between the "send PIN" and "enter PIN" requests.
_pending: dict[str, tuple] = {}  # email -> (client, polling_id, started_at)
PIN_TTL_S = 15 * 60


class LoginError(Exception):
    pass


def _blocked(resp_text: str) -> bool:
    return "captcha-delivery" in resp_text


def start_login(email: str) -> None:
    """Ask TGTG to email a login PIN."""
    from tgtg import TgtgClient
    from tgtg import AUTH_BY_EMAIL_ENDPOINT

    email = email.strip().lower()
    client = TgtgClient(url=config.TGTG_BASE_URL, email=email)
    resp = client._post(client._get_url(AUTH_BY_EMAIL_ENDPOINT),
                        json={"device_type": client.device_type, "email": email})
    if resp.status_code == 429:
        raise LoginError("TGTG says too many requests. Wait a while and try again.")
    if resp.status_code == 403 and _blocked(resp.text):
        raise LoginError("TGTG blocked the request with a CAPTCHA (bot protection). Wait a few hours and retry.")
    if resp.status_code != 200:
        raise LoginError(f"TGTG returned HTTP {resp.status_code}.")
    data = resp.json()
    if data.get("state") == "TERMS":
        raise LoginError("This email has no Too Good To Go account. Sign up in the TGTG app first.")
    if data.get("state") != "WAIT":
        raise LoginError(f"Unexpected TGTG login state: {data.get('state')}")
    # Drop stale entries so abandoned logins don't pile up in memory.
    for k in [k for k, v in _pending.items() if time.time() - v[2] > PIN_TTL_S]:
        _pending.pop(k, None)
    _pending[email] = (client, data["polling_id"], time.time(), 0)


MAX_PIN_ATTEMPTS = 5


def finish_login(email: str, pin: str, save: bool = True) -> None:
    """Exchange the emailed PIN for tokens.

    save=True keeps the tokens for scanning (your own account, CLI/local use).
    save=False only proves the person owns the TGTG account; the tokens are discarded.
    """
    email = email.strip().lower()
    entry = _pending.get(email)
    if not entry or time.time() - entry[2] > PIN_TTL_S:
        _pending.pop(email, None)
        raise LoginError("No login in progress for this email, or it expired. Request a new PIN.")
    client, polling_id, started, attempts = entry
    try:
        client._auth_by_pin(polling_id, pin.strip())
    except Exception as e:
        if _blocked(str(e)):
            raise LoginError("TGTG blocked the request with a CAPTCHA (bot protection). Wait a few hours and retry.")
        attempts += 1
        if attempts >= MAX_PIN_ATTEMPTS:
            _pending.pop(email, None)
            raise LoginError("Too many wrong PINs. Request a new PIN.")
        _pending[email] = (client, polling_id, started, attempts)
        raise LoginError("TGTG rejected that PIN. Check the latest email and try again.")
    _pending.pop(email, None)
    if save:
        _save_creds(client, email)


def login_status() -> dict:
    if not config.CREDENTIALS_PATH.exists():
        return {"logged_in": False}
    creds = json.loads(config.CREDENTIALS_PATH.read_text())
    return {"logged_in": bool(creds.get("access_token")), "email": creds.get("email")}


def logout() -> None:
    """Forget the saved tokens on this computer."""
    config.CREDENTIALS_PATH.unlink(missing_ok=True)


def get_client():
    from tgtg import TgtgClient

    if not config.CREDENTIALS_PATH.exists():
        raise SystemExit("No TGTG credentials yet. Run: python -m app.cli login")
    creds = json.loads(config.CREDENTIALS_PATH.read_text())
    return TgtgClient(url=config.TGTG_BASE_URL, **creds)


def _save_creds(client, email=None):
    config.CREDENTIALS_PATH.write_text(json.dumps({
        "email": email or client.email,
        "access_token": client.access_token,
        "refresh_token": client.refresh_token,
        "cookie": client.cookie,
    }, indent=2))


def grid_points(lat: float, lng: float, radius_km: float, tile_km: float):
    """Centres of overlapping circles (radius tile_km) that cover a circle of radius_km."""
    if radius_km <= tile_km:
        return [(lat, lng)]
    step = tile_km * math.sqrt(2)  # square inscribed in each tile circle -> no gaps
    n = math.ceil(radius_km / step)
    dlat = step / 111.32
    dlng = step / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            if math.hypot(i * step, j * step) <= radius_km + step:
                pts.append((lat + i * dlat, lng + j * dlng))
    return pts


def scan(lat: float, lng: float, radius_km: float, tile_km: float = 3.0,
         page_size: int = 50, pause_s: float = 2.0, max_pages: int = 20, log=print) -> int:
    """Fetch every listing (in stock or not) in the area and store it. Returns item count."""
    client = get_client()
    seen = set()
    points = grid_points(lat, lng, radius_km, tile_km)
    log(f"Scanning {len(points)} tile(s) of {tile_km} km around ({lat}, {lng})")
    with db.connect() as conn:
        for n, (plat, plng) in enumerate(points, 1):
            for page in range(1, max_pages + 1):
                items = client.get_items(latitude=plat, longitude=plng, radius=tile_km,
                                         page_size=page_size, page=page,
                                         favorites_only=False, with_stock_only=False)
                for raw in items:
                    store_row, item_row = parse_item(raw)
                    if item_row["item_id"] in seen:
                        continue
                    seen.add(item_row["item_id"])
                    db.upsert_store(conn, store_row)
                    db.upsert_item(conn, item_row)
                conn.commit()
                time.sleep(pause_s)  # be gentle: TGTG rate-limits and blocks aggressive clients
                if len(items) < page_size:
                    break
            log(f"  tile {n}/{len(points)}: {len(seen)} unique items so far")
    _save_creds(client)  # tokens may have been refreshed
    return len(seen)
