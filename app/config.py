import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "tgtg_halal.sqlite3"
CREDENTIALS_PATH = DATA_DIR / "tgtg_credentials.json"

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# AUTH_MODE=users: visitors must sign in (hosted site). AUTH_MODE=none (default): no
# sign-in, for running on your own PC. ("tgtg" is accepted as an old name for "users".)
AUTH_MODE = os.getenv("AUTH_MODE", "none").lower()
USER_MODE = AUTH_MODE in ("users", "tgtg")
# Which sign-in methods to offer, comma separated: google, email, tgtg.
AUTH_METHODS = [m.strip() for m in os.getenv("AUTH_METHODS", "tgtg" if AUTH_MODE == "tgtg" else "google,email").split(",") if m.strip()]
# Signs session cookies. Required when sign-in is on; keep it secret and stable.
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if USER_MODE and len(SESSION_SECRET) < 16:
    raise RuntimeError("Sign-in needs SESSION_SECRET (16+ characters)")

# Sign in with Google: an OAuth "Web application" client ID (public, not a secret).
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
# Emailed sign-in codes, sent through Amazon SES from a verified address.
MAIL_FROM = os.getenv("MAIL_FROM", "")
SES_REGION = os.getenv("SES_REGION", "eu-west-1")
# The Google Maps scraper needs Docker and ~1 GB of RAM; turn it off on small servers.
SCRAPER_ENABLED = os.getenv("SCRAPER_ENABLED", "true").lower() == "true"
TGTG_EMAIL = os.getenv("TGTG_EMAIL", "")
# tgtg 0.19.0 still defaults to the old apptoogoodtogo.com host; TGTG moved its API here
# (see https://github.com/ahivert/tgtg-python/pull/411).
TGTG_BASE_URL = os.getenv("TGTG_BASE_URL", "https://api.toogoodtogo.com/api/")
