"""Launcher that works from any folder:  python C:\\path\\to\\tgtg-halal\\run.py <command>

Python puts this script's folder on sys.path, so the `app` package is always found,
whatever directory the terminal is in.
"""
from app.cli import run

if __name__ == "__main__":
    run()
