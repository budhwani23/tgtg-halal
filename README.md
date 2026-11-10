# TGTG Halal Finder

Pulls Too Good To Go listings for an area and gives each store a halal estimate, then shows the bags on a map you can filter.

## How it works

1. **Fetching TGTG listings** uses [tgtg-python](https://github.com/ahivert/tgtg-python), an unofficial client for the TGTG app API. TGTG has no endpoint that returns everything, so `scan` covers the area with overlapping circles and pages through each one.
2. **Checking halal evidence** (`enrich`) scores each store from these signals:

   | Signal | Points |
   |---|---|
   | TGTG listing is in a `HALAL` diet category, or its text says halal | +4 to +5 (−4 if it says *not* halal) |
   | Google Maps name or place type contains "halal" | +4 |
   | Google editorial summary mentions halal | +3 / +4 (−3 if negated) |
   | Google reviews mention halal (up to 5 reviews, capped at ±4 total) | +1.5 each, −2 for "not halal" |
   | Place appears in Google's own "halal food" search nearby | +1 |
   | *(optional)* google-maps-scraper finds the "Halal food" offering | +4 |

   The total gives a level: **likely** (≥ 4), **possible** (≥ 1.5), **unknown**, or **unlikely** (≤ −2). Click **Why?** on any card to see the evidence behind its score.
3. **The web UI** (FastAPI + Leaflet) has these filters: halal level, in-stock only, category, and search.

### Why the Google Places API and not the scraper

The **Google Places API (New)** is official, stable and cached here, so each store costs about one lookup every 30 days. It doesn't expose the "Halal food" attribute directly, which is why the app combines reviews, the editorial summary and Google's "halal food" search ranking.

**[gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper)** *does* capture the "Halal food" offering from the Maps "About" tab. That's the strongest signal, but scraping Google Maps breaks Google's terms and is slow and brittle, so it's an optional import rather than a default.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # then fill in GOOGLE_MAPS_API_KEY and TGTG_EMAIL
```

### Try it with sample data

```bash
python -m app.cli demo
python -m app.cli serve         # http://127.0.0.1:8000
```

### Real data

```bash
python -m app.cli login                                   # TGTG emails you a PIN; type it in
python -m app.cli scan --lat 50.1109 --lng 8.6821 --radius 5
python -m app.cli enrich                                  # add --no-google to skip the Places API
python -m app.cli serve
```

### Free option: google-maps-scraper (no API key)

Needs Docker Desktop running. This searches Google Maps once for every stored TGTG store (each search is tagged with the TGTG store ID, and the result nearest the store within 300 m is kept), plus about 20 "halal …" searches across Frankfurt districts. Then it re-scores every store. 425 stores take about 20 minutes.

```bash
python run.py scrape
python run.py enrich --force
```

The **Refresh halal data** button in the web app runs the same steps in the background.

Note: the current scraper version only returns the Accessibility part of a place's About tab, so the "Halal food" offering isn't available. The evidence comes from the place's categories, description and reviews instead.

## Hosted version: sign in with Too Good To Go

With `AUTH_MODE=tgtg` (used on the server), visitors sign in with their own Too Good To Go email and the PIN TGTG emails them. Any TGTG account can sign in. TGTG is only used to confirm the person owns that account; their TGTG tokens are discarded right away. The site then sets its own signed cookie, valid for 30 days. `SESSION_SECRET` signs the cookies; on the server it comes from the SSM parameter `/learnable/dev/tgtg-halal-password`.

Sign-in methods are set with `AUTH_MODE=users` and `AUTH_METHODS=google,email`. Google needs `GOOGLE_CLIENT_ID` (a "Web application" OAuth client whose authorized JavaScript origin is your site). Emailed codes need `MAIL_FROM`, an Amazon SES-verified sender; `scripts/grant-ses-send.ps1 -Sender you@example.com` lets the server's EC2 role send from it. TGTG's own PIN (`tgtg`) still works locally but is blocked from cloud servers by TGTG's bot protection.

PIN and code requests are rate-limited: one per email per minute, five per IP address per 15 minutes, and 40 per hour across the whole site. A PIN request can't be retried more than 5 times with a wrong PIN.

## Caveats

- **The halal level is an estimate, not a certification.** It reflects public text only. Mixed bags from bakeries and supermarkets can contain non-halal items even when the shop sells some halal products. Always confirm with the store.
- **tgtg-python is unofficial.** It can break when TGTG updates its app, and TGTG uses DataDome bot protection. Heavy scanning can get you rate-limited (HTTP 429/403) or get the account blocked. Use a dedicated account, keep the default 2 s pause, and don't scan more often than you need. Check TGTG's terms before using this beyond personal use.
- **Google Places API is paid.** Text Search with reviews is billed at the Enterprise + Atmosphere tier. Results are cached in `data/tgtg_halal.sqlite3` (30 days for store matches, 7 days for the halal search). Set a budget alert in Google Cloud.
- `data/` holds your TGTG tokens. It's git-ignored, so keep it that way.

## Tests

```bash
python -m pytest -q
```
