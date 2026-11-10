"""Visitor sign-in for the hosted site (AUTH_MODE=users).

Methods (AUTH_METHODS):
  google - Sign in with Google (Google Identity Services ID token, checked server-side)
  email  - a 6-digit code we email through Amazon SES
  tgtg   - TGTG's own email PIN (only proves account ownership; TGTG tokens are
           discarded). TGTG's bot protection blocks this from cloud servers.

All methods end in our own signed session cookie. Rate limits stop the email forms
being used to flood someone's inbox.
"""
import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque

from . import config

COOKIE = "tgtg_halal_session"
SESSION_DAYS = 30

# limits on "send me a PIN" requests
PER_EMAIL_COOLDOWN_S = 60
PER_IP_MAX, PER_IP_WINDOW_S = 5, 15 * 60
GLOBAL_MAX, GLOBAL_WINDOW_S = 40, 60 * 60

_last_by_email: dict[str, float] = {}
_by_ip: dict[str, deque] = defaultdict(deque)
_global: deque = deque()


class RateLimited(Exception):
    pass


def _sign(payload: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(email: str, now: float | None = None) -> str:
    exp = int((time.time() if now is None else now) + SESSION_DAYS * 86400)
    payload = base64.urlsafe_b64encode(f"{email}|{exp}".encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_session(cookie: str | None) -> str | None:
    """Email of the signed-in user, or None."""
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        email, exp = base64.urlsafe_b64decode(payload.encode()).decode().rsplit("|", 1)
    except Exception:
        return None
    return email if int(exp) > time.time() else None


def _prune(q: deque, window: float, now: float):
    while q and now - q[0] > window:
        q.popleft()


def check_rate(email: str, ip: str, now: float | None = None) -> None:
    """Raise RateLimited if this PIN request should be refused; otherwise record it."""
    now = time.time() if now is None else now
    last = _last_by_email.get(email)
    if last and now - last < PER_EMAIL_COOLDOWN_S:
        raise RateLimited(f"A PIN was just sent to this email. Wait {int(PER_EMAIL_COOLDOWN_S - (now - last)) + 1} s.")
    q = _by_ip[ip]
    _prune(q, PER_IP_WINDOW_S, now)
    if len(q) >= PER_IP_MAX:
        raise RateLimited("Too many login attempts from your network. Try again in 15 minutes.")
    _prune(_global, GLOBAL_WINDOW_S, now)
    if len(_global) >= GLOBAL_MAX:
        raise RateLimited("Too many logins right now. Try again later.")
    _last_by_email[email] = now
    q.append(now)
    _global.append(now)


def client_ip(headers, fallback: str) -> str:
    """Viewer IP. CloudFront appends the real viewer IP as the last X-Forwarded-For entry,
    and only CloudFront can reach the server, so the rightmost entry can't be spoofed."""
    xff = headers.get("x-forwarded-for", "")
    return xff.split(",")[-1].strip() if xff else fallback


def reset_limits():  # for tests
    _last_by_email.clear()
    _by_ip.clear()
    _global.clear()
    _codes.clear()


# ---- Emailed sign-in codes (Amazon SES) ---------------------------------------------
CODE_TTL_S = 10 * 60
CODE_MAX_ATTEMPTS = 5
_codes: dict[str, tuple[str, float, int]] = {}  # email -> (sha256(code), expires_at, wrong_attempts)


class AuthError(Exception):
    pass


def _hash_code(email: str, code: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def send_email_code(email: str, sender=None) -> None:
    """Create a 6-digit code, remember only its hash, and email it."""
    import secrets

    code = f"{secrets.randbelow(1_000_000):06d}"
    (sender or _ses_send)(email, code)
    now = time.time()
    for k in [k for k, v in _codes.items() if v[1] < now]:
        _codes.pop(k, None)
    _codes[email] = (_hash_code(email, code), now + CODE_TTL_S, 0)


def verify_email_code(email: str, code: str) -> None:
    entry = _codes.get(email)
    if not entry or entry[1] < time.time():
        _codes.pop(email, None)
        raise AuthError("That code has expired. Request a new one.")
    digest, exp, attempts = entry
    if not hmac.compare_digest(digest, _hash_code(email, code.strip())):
        attempts += 1
        if attempts >= CODE_MAX_ATTEMPTS:
            _codes.pop(email, None)
            raise AuthError("Too many wrong codes. Request a new one.")
        _codes[email] = (digest, exp, attempts)
        raise AuthError("That code isn't right. Check the latest email.")
    _codes.pop(email, None)


def _ses_send(email: str, code: str) -> None:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    if not config.MAIL_FROM:
        raise AuthError("Email sign-in isn't set up on this server.")
    text = (f"Your TGTG Halal Finder sign-in code is {code}\n\n"
            "It expires in 10 minutes. If you didn't ask for it, ignore this email.")
    html = (f"<p>Your TGTG Halal Finder sign-in code is</p>"
            f"<p style=\"font-size:28px;font-weight:700;letter-spacing:4px\">{code}</p>"
            f"<p style=\"color:#666\">It expires in 10 minutes. If you didn't ask for it, ignore this email.</p>")
    try:
        boto3.client("sesv2", region_name=config.SES_REGION).send_email(
            FromEmailAddress=f"TGTG Halal Finder <{config.MAIL_FROM}>",
            Destination={"ToAddresses": [email]},
            Content={"Simple": {"Subject": {"Data": f"{code} is your TGTG Halal Finder code"},
                                "Body": {"Text": {"Data": text}, "Html": {"Data": html}}}})
    except ClientError as e:
        msg = str(e)
        if "not verified" in msg:  # SES sandbox: only approved recipients
            raise AuthError("This site can only email addresses approved by its owner for now. "
                            "Use Sign in with Google instead.")
        raise AuthError("Couldn't send the email. Try again in a minute.")
    except BotoCoreError:  # e.g. no AWS credentials reachable from the container
        raise AuthError("Email sign-in isn't working on this server right now.")


# ---- Sign in with Google ------------------------------------------------------------
def verify_google_credential(credential: str, fetch=None) -> str:
    """Check a Google Identity Services ID token and return the verified email."""
    import requests

    if not config.GOOGLE_CLIENT_ID:
        raise AuthError("Google sign-in isn't set up on this server.")
    if fetch is None:
        def fetch(token):
            r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": token}, timeout=10)
            return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})
    status, info = fetch(credential)
    if status != 200:
        raise AuthError("Google couldn't confirm the sign-in. Try again.")
    if info.get("aud") != config.GOOGLE_CLIENT_ID:
        raise AuthError("That Google sign-in was meant for a different site.")
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise AuthError("Unexpected Google sign-in issuer.")
    if int(info.get("exp", 0)) < time.time():
        raise AuthError("That Google sign-in expired. Try again.")
    if str(info.get("email_verified")).lower() != "true" or not info.get("email"):
        raise AuthError("Your Google account's email isn't verified.")
    return info["email"].lower()
