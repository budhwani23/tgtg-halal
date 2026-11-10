"""Command line entry point: python -m app.cli <command>"""
import argparse

from . import config


def main():
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("login", help="Log in to Too Good To Go (PIN sent by email)")
    lg.add_argument("--email", default=config.TGTG_EMAIL)

    sc = sub.add_parser("scan", help="Pull every TGTG listing in an area")
    sc.add_argument("--lat", type=float, required=True)
    sc.add_argument("--lng", type=float, required=True)
    sc.add_argument("--radius", type=float, default=5, help="km to cover")
    sc.add_argument("--tile", type=float, default=3, help="km radius per TGTG query")

    en = sub.add_parser("enrich", help="Score every store for halal evidence")
    en.add_argument("--force", action="store_true", help="re-check stores checked recently")
    en.add_argument("--no-google", action="store_true")

    sub.add_parser("scrape", help="Run google-maps-scraper (Docker) for every stored store, then import")

    ig = sub.add_parser("import-gosom", help="Import existing google-maps-scraper JSON output")
    ig.add_argument("path")
    ig.add_argument("--kind", choices=["store", "area"], default="area")

    sub.add_parser("demo", help="Load sample data (no accounts needed)")

    sv = sub.add_parser("serve", help="Start the web app")
    sv.add_argument("--port", type=int, default=8000)

    a = p.parse_args()
    if a.cmd == "login":
        from .tgtg_source import login
        if not a.email:
            raise SystemExit("Pass --email or set TGTG_EMAIL in .env")
        print(f"Saved credentials to {login(a.email)}")
    elif a.cmd == "scan":
        from .tgtg_source import scan
        print(f"Stored {scan(a.lat, a.lng, a.radius, a.tile)} items")
    elif a.cmd == "enrich":
        from .enrich import enrich_all
        print(enrich_all(force=a.force, use_google=False if a.no_google else None))
    elif a.cmd == "scrape":
        from .gosom_import import scrape_all
        print(f"Imported scraped places: {scrape_all()}")
    elif a.cmd == "import-gosom":
        from .gosom_import import import_file
        print(f"Imported {import_file(a.path, a.kind)} places")
    elif a.cmd == "demo":
        from .demo import load_demo
        load_demo()
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("app.server:app", host="127.0.0.1", port=a.port)


def run():
    try:
        main()
    except Exception as e:  # turn TGTG bot-protection blocks into a readable message
        if "captcha-delivery" in str(e) or "TgtgLoginError" in type(e).__name__ and "403" in str(e):
            raise SystemExit(
                "TGTG blocked this request with a CAPTCHA (DataDome bot protection, HTTP 403).\n"
                "This tool can't solve CAPTCHAs. Wait a few hours before retrying, and check\n"
                "https://github.com/ahivert/tgtg-python/issues for a library update."
            ) from None
        raise


if __name__ == "__main__":
    run()
