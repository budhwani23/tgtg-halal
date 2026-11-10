from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from . import config, db, tgtg_source, user_auth

STATIC = Path(__file__).resolve().parent.parent / "static"
LEVEL_RANK = {"likely": 0, "possible": 1, "unknown": 2, "unchecked": 3, "unlikely": 4}
OPEN_PATHS = {"/login", "/login/config", "/login/start", "/login/verify", "/login/email/start",
              "/login/email/verify", "/login/google", "/healthz", "/privacy"}
USER_MODE = config.USER_MODE

app = FastAPI(title="TGTG Halal Finder", docs_url=None, redoc_url=None, openapi_url=None)


# ---- Visitor sign-in (AUTH_MODE=users): Google, emailed code, or TGTG PIN -----------
@app.middleware("http")
async def require_signin(request: Request, call_next):
    if not USER_MODE or request.url.path in OPEN_PATHS:
        return await call_next(request)
    email = user_auth.read_session(request.cookies.get(user_auth.COOKIE))
    if email:
        request.state.user = email
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


class LoginStart(BaseModel):
    email: str


class LoginPin(BaseModel):
    email: str
    pin: str


def _valid_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 254:
        raise HTTPException(400, "Enter a valid email address.")
    return email


@app.get("/login")
def login_page(request: Request):
    if not USER_MODE:
        return RedirectResponse("/", status_code=303)
    if user_auth.read_session(request.cookies.get(user_auth.COOKIE)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "login.html")


def _require_method(name: str):
    if not USER_MODE or name not in config.AUTH_METHODS:
        raise HTTPException(404)


def _rate_check(email: str, request: Request):
    try:
        user_auth.check_rate(email, user_auth.client_ip(request.headers, request.client.host if request.client else "?"))
    except user_auth.RateLimited as e:
        raise HTTPException(429, str(e))


def _signed_in(email: str, request: Request) -> JSONResponse:
    resp = JSONResponse({"ok": True, "email": email})
    secure = request.headers.get("cloudfront-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(user_auth.COOKIE, user_auth.make_session(email), max_age=user_auth.SESSION_DAYS * 86400,
                    httponly=True, secure=secure, samesite="lax")
    return resp


@app.get("/login/config")
def login_config():
    """What the sign-in page should show."""
    methods = [m for m in config.AUTH_METHODS
               if not (m == "google" and not config.GOOGLE_CLIENT_ID) and not (m == "email" and not config.MAIL_FROM)]
    return {"methods": methods, "google_client_id": config.GOOGLE_CLIENT_ID if "google" in methods else None}


class GoogleCredential(BaseModel):
    credential: str


@app.post("/login/google")
def login_google(body: GoogleCredential, request: Request):
    _require_method("google")
    try:
        email = user_auth.verify_google_credential(body.credential)
    except user_auth.AuthError as e:
        raise HTTPException(400, str(e))
    return _signed_in(email, request)


class CodeVerify(BaseModel):
    email: str
    code: str


@app.post("/login/email/start")
def login_email_start(body: LoginStart, request: Request):
    _require_method("email")
    email = _valid_email(body.email)
    _rate_check(email, request)
    try:
        user_auth.send_email_code(email)
    except user_auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/login/email/verify")
def login_email_verify(body: CodeVerify, request: Request):
    _require_method("email")
    email = _valid_email(body.email)
    try:
        user_auth.verify_email_code(email, body.code)
    except user_auth.AuthError as e:
        raise HTTPException(400, str(e))
    return _signed_in(email, request)


# TGTG's own email PIN (identity check only). Blocked from cloud servers by TGTG's bot
# protection, so it's off unless AUTH_METHODS includes "tgtg".
@app.post("/login/start")
def login_start(body: LoginStart, request: Request):
    _require_method("tgtg")
    email = _valid_email(body.email)
    _rate_check(email, request)
    try:
        tgtg_source.start_login(email)
    except tgtg_source.LoginError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/login/verify")
def login_verify(body: LoginPin, request: Request):
    _require_method("tgtg")
    email = _valid_email(body.email)
    try:
        tgtg_source.finish_login(email, body.pin, save=False)  # tokens discarded
    except tgtg_source.LoginError as e:
        raise HTTPException(400, str(e))
    return _signed_in(email, request)


@app.post("/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(user_auth.COOKIE)
    return resp


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/privacy")
def privacy():
    return FileResponse(STATIC / "privacy.html")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/listings")
def listings(
    halal: str = Query("any", description="any | likely | possible (likely or possible) | unlikely"),
    in_stock: bool = False,
    category: str | None = None,
    q: str | None = None,
):
    with db.connect() as conn:
        rows = db.listings(conn)
    if halal == "likely":
        rows = [r for r in rows if r["halal_level"] == "likely"]
    elif halal == "possible":
        rows = [r for r in rows if r["halal_level"] in ("likely", "possible")]
    elif halal == "unlikely":
        rows = [r for r in rows if r["halal_level"] == "unlikely"]
    if in_stock:
        rows = [r for r in rows if (r["items_available"] or 0) > 0]
    if category:
        rows = [r for r in rows if r["category"] == category]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in f"{r['store_name']} {r['display_name']} {r['address']}".lower()]
    rows.sort(key=lambda r: (LEVEL_RANK.get(r["halal_level"], 9), -(r["halal_score"] or 0)))
    return {"count": len(rows), "items": rows}


# ---- Background job: scrape Google Maps + re-score -------------------------------
_job = {"running": False, "log": [], "error": None, "finished_at": None}


def _run_refresh():
    import time
    from . import enrich, gosom_import

    def log(msg):
        _job["log"] = (_job["log"] + [str(msg)])[-200:]

    try:
        log(f"Scraped places: {gosom_import.scrape_all(log=log)}")
        log("Scoring stores…")
        log(f"Done: {enrich.enrich_all(force=True, log=lambda m: None)}")
    except Exception as e:  # surface to the UI instead of dying silently
        _job["error"] = str(e)
        log(f"Failed: {e}")
    finally:
        _job["running"] = False
        _job["finished_at"] = time.time()


@app.post("/api/refresh")
def refresh():
    import threading

    if not config.SCRAPER_ENABLED:
        raise HTTPException(403, "The scraper is turned off on this server.")
    if _job["running"]:
        raise HTTPException(409, "A refresh is already running.")
    _job.update(running=True, log=["Starting Google Maps scraper (Docker)…"], error=None, finished_at=None)
    threading.Thread(target=_run_refresh, daemon=True).start()
    return _job


@app.get("/api/refresh")
def refresh_status():
    with db.connect() as conn:
        last = conn.execute("SELECT MAX(checked_at) FROM halal").fetchone()[0]
    return {**_job, "enabled": config.SCRAPER_ENABLED, "last_checked": last}


# ---- The scanner's own TGTG login (local use only) ---------------------------------
# When visitors sign in (AUTH_MODE=tgtg) these are disabled, so no visitor can replace
# or remove the account the scanner uses.
def _scanner_login_allowed():
    if USER_MODE:
        raise HTTPException(403, "Not available on this server.")


@app.get("/api/auth/status")
def auth_status(request: Request):
    if USER_MODE:
        return {"mode": "user", "email": getattr(request.state, "user", None)}
    return {"mode": "scanner", **tgtg_source.login_status()}


@app.post("/api/auth/start")
def auth_start(body: LoginStart):
    _scanner_login_allowed()
    email = _valid_email(body.email)
    try:
        tgtg_source.start_login(email)
    except tgtg_source.LoginError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/auth/pin")
def auth_pin(body: LoginPin):
    _scanner_login_allowed()
    try:
        tgtg_source.finish_login(body.email, body.pin)
    except tgtg_source.LoginError as e:
        raise HTTPException(400, str(e))
    return {"mode": "scanner", **tgtg_source.login_status()}


@app.post("/api/auth/logout")
def auth_logout():
    _scanner_login_allowed()
    tgtg_source.logout()
    return {"mode": "scanner", "logged_in": False}


@app.get("/api/stats")
def stats():
    with db.connect() as conn:
        rows = db.listings(conn)
    by_level, cats = {}, set()
    for r in rows:
        by_level[r["halal_level"]] = by_level.get(r["halal_level"], 0) + 1
        if r["category"]:
            cats.add(r["category"])
    return {"total": len(rows), "by_level": by_level, "categories": sorted(cats)}
