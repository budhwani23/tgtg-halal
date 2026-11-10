"""Turns raw signals into a halal score with human-readable evidence.

This is a heuristic, not a certification check. A score only says how much public
text points towards the place being halal; the UI shows the evidence so a user can
judge it themselves and confirm with the store.
"""
import re

HALAL_RE = re.compile(r"\bhalal\b", re.I)
# English + German phrasing (e.g. "nicht halal", "kein Halal-Fleisch", "Halal-zertifiziert")
NEGATION_RE = re.compile(
    r"(\bnot\b|n't\b|\bno\b|\bnon[- ]?$|\bnever\b|\bnor\b|\bnicht\b|\bkein\w*|\bnie\b)[\w\s%-]{0,15}$", re.I)
STRONG_RE = re.compile(
    r"(100\s?%|fully|certified|all (the )?(meat|food) is|only|zertifiziert|ausschlie(ß|ss)lich|komplett|nur|alles( ist)?)\s*(halal)?"
    r"|\b(hmc|hfa)\b", re.I)
PARTIAL_RE = re.compile(
    r"halal[- ](options?|choices?|dishes|items|menu|optionen|gerichte|auswahl|produkte)"
    r"|(some|einige|teilweise|auch) halal|halal (meat|chicken) (is )?available", re.I)

LIKELY, POSSIBLE, UNKNOWN, UNLIKELY = "likely", "possible", "unknown", "unlikely"


def classify_text(text: str) -> list[str]:
    """Return one label per 'halal' mention: 'strong', 'positive', 'partial' or 'negative'."""
    labels = []
    for m in HALAL_RE.finditer(text or ""):
        before = text[max(0, m.start() - 30):m.start()]
        window = text[max(0, m.start() - 30):m.end() + 30]
        if NEGATION_RE.search(before):
            labels.append("negative")
        elif PARTIAL_RE.search(window):
            labels.append("partial")
        elif STRONG_RE.search(window):
            labels.append("strong")
        else:
            labels.append("positive")
    return labels


def _snippet(text: str, width: int = 70) -> str:
    m = HALAL_RE.search(text or "")
    if not m:
        return (text or "")[:width]
    start = max(0, m.start() - width // 2)
    s = text[start:start + width].replace("\n", " ").strip()
    return ("…" if start else "") + s + ("…" if start + width < len(text) else "")


def _text_signal(labels: list[str], pos: float, strong: float, neg: float) -> float:
    if not labels:
        return 0.0
    if "negative" in labels and not any(l in ("strong", "positive") for l in labels):
        return neg
    if "strong" in labels:
        return strong
    if "positive" in labels:
        return pos
    return pos / 2  # partial only


def score_store(store: dict, items: list[dict], place: dict | None = None,
                in_halal_search: bool = False, gosom_hits: list[str] | None = None) -> dict:
    score, evidence = 0.0, []

    def add(points, source, detail):
        nonlocal score
        if points:
            score += points
            evidence.append({"source": source, "points": round(points, 1), "detail": detail})

    # 1. What the store says about itself on TGTG
    tgtg_text = " ".join([store.get("name", ""), store.get("description", "")] +
                         [f"{i.get('display_name', '')} {i.get('description', '')}" for i in items])
    diets = {d.upper() for i in items for d in (i.get("diet_categories") or [])}
    if "HALAL" in diets:
        add(5, "tgtg", "Listed under the HALAL diet category on Too Good To Go")
    else:
        labels = classify_text(tgtg_text)
        add(_text_signal(labels, 4, 5, -4), "tgtg", f"TGTG listing: \"{_snippet(tgtg_text)}\"")

    # 2. Google Maps listing
    if place:
        gname = (place.get("displayName") or {}).get("text", "")
        if HALAL_RE.search(gname):
            add(4, "google_name", f"Google Maps name: {gname}")
        # Categories are picked by the business owner (chains often apply them to every
        # branch), so on their own they only make a place "possible", not "likely".
        halal_types = [t for t in (place.get("types") or []) if "halal" in t.lower()]
        if halal_types:
            add(3, "google_type", f"Business lists itself on Google Maps as: {', '.join(halal_types)}")
        summary = (place.get("editorialSummary") or {}).get("text", "")
        add(_text_signal(classify_text(summary), 3, 4, -3), "google_summary", f"Google summary: \"{_snippet(summary)}\"")

        review_pts = 0.0
        for r in place.get("reviews") or []:
            text = (r.get("text") or r.get("originalText") or {}).get("text", "")
            labels = classify_text(text)
            pts = _text_signal(labels, 1.5, 2, -2)
            if pts:
                review_pts += pts
                kind = "says not halal" if pts < 0 else "mentions halal"
                evidence.append({"source": "google_review", "points": pts,
                                 "detail": f"Review {kind}: \"{_snippet(text)}\""})
        score += max(min(review_pts, 4), -4)

    # 3. Google's own "halal food" search ranking
    if in_halal_search:
        add(1, "google_search", "Appears in Google Maps results for \"halal food\" nearby")

    # 4. Optional google-maps-scraper import ("Halal food" under Offerings)
    for hit in gosom_hits or []:
        add(4, "gmaps_scraper", f"Google Maps attribute: {hit}")
        break

    if score >= 4:
        level = LIKELY
    elif score >= 1.5:
        level = POSSIBLE
    elif score <= -2:
        level = UNLIKELY
    else:
        level = UNKNOWN

    return {
        "score": round(score, 1),
        "level": level,
        "evidence": evidence,
        "place_id": (place or {}).get("id"),
        "place_name": ((place or {}).get("displayName") or {}).get("text"),
        "maps_uri": (place or {}).get("googleMapsUri"),
    }
