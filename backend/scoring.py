"""Explainable fraud scoring. Returns a 0-100 trust score plus human-readable reasons.

trust = 100 - sum(penalty_i * weight_i)     (each penalty is 0-100)
>=70 Verified | 40-69 Needs review | <40 Flagged
NOTE: prices.json holds SAMPLE averages - replace with real data (Kaggle / scraped public listings).
"""
import json
import math
import re
from pathlib import Path

PRICES = json.loads((Path(__file__).parent / "prices.json").read_text())
WEIGHTS = {"price": 0.35, "text": 0.25, "duplicate": 0.25, "lister": 0.10, "consistency": 0.05}

SCAM_PATTERNS = [
    (r"pay (an? )?advance|advance (payment|amount)|token (amount|money)|booking amount", 35, "asks for advance / token money"),
    (r"owner (is )?(abroad|overseas|out of (the )?country)|\babroad\b|\bnri\b", 30, "owner claims to be abroad"),
    (r"whats ?app only|only whats ?app|no calls", 25, "WhatsApp-only contact"),
    (r"urgent|hurry|first come|limited time", 15, "pressure / urgency wording"),
    (r"without (a )?(visit|seeing)|no (site )?(visit|viewing)|cannot show|keys? (will be )?(couriered|sent|posted)", 35, "no site visit / keys by courier"),
    (r"western union|gift card|crypto|bitcoin|upi first", 30, "unusual payment method"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two GPS coordinates in kilometers."""
    r = 6371.0  # Earth's mean radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _price(d):
    p = PRICES.get(d["locality"])
    if not p:
        return 25, [("med", f"No price benchmark available for {d['locality']}")], []
    rent = d["type"] == "rent"
    avg = p["rent_psf"] if rent else p["sale_psf"]
    unit = "/sq ft/month" if rent else "/sq ft"
    ppsf = d["price"] / d["sqft"]
    diff = (avg - ppsf) / avg * 100
    if diff >= 10:
        pen = min(100, (diff - 10) / 30 * 100)
        return pen, [("high" if pen >= 60 else "med",
                      f"Price is {diff:.0f}% below the {d['locality']} average (Rs {ppsf:.1f} vs Rs {avg} {unit})")], []
    if diff <= -100:
        return 40, [("med", f"Price is {-diff:.0f}% above the {d['locality']} average - unusually high")], []
    return 0, [], [f"Price (Rs {ppsf:.1f}{unit}) is within the normal range for {d['locality']} (average Rs {avg})"]


def _text(desc):
    hits, total = [], 0
    for pat, w, label in SCAM_PATTERNS:
        m = re.search(pat, desc or "", re.I)
        if m:
            hits.append(f'"{m.group(0).strip()}" ({label})')
            total += w
    if hits:
        return min(100, total), [("high" if total >= 50 else "med", "Scam-style wording: " + "; ".join(hits))], []
    return 0, [], ["Description has no scam-style wording"]


def _consistency(d, n_photos):
    pen, reasons, good = 0, [], []
    if n_photos < 3:
        pen += 30
        reasons.append(("low", f"Only {n_photos} photo(s) uploaded (3+ expected)"))
    if len((d.get("description") or "").strip()) < 30:
        pen += 25
        reasons.append(("low", "Description is missing or very short"))
    per_bhk = d["sqft"] / d["bhk"]
    if not 250 <= per_bhk <= 1100:
        pen += 40
        reasons.append(("med", f"{d['sqft']} sq ft for {d['bhk']} BHK looks unrealistic"))
    addr_lower = (d.get("address") or "").lower()
    loc_lower = d.get("locality", "").lower()
    other_localities = [l.lower() for l in PRICES if l.lower() != loc_lower]
    contradiction = next((l for l in other_localities if l in addr_lower), None)
    if contradiction:
        pen += 30
        reasons.append(("med", f"Address mentions {contradiction.title()} but selected area is {d.get('locality')}"))
    elif loc_lower in addr_lower:
        good.append(f"Address explicitly confirms area ({d.get('locality')})")

    # Location consistency check: compare pin coordinates with area center
    has_coords = "lat" in d and "lng" in d and d["lat"] is not None and d["lng"] is not None
    p = PRICES.get(d.get("locality"))
    if has_coords and p and "lat" in p and "lng" in p:
        try:
            plat = float(d["lat"])
            plng = float(d["lng"])
            dist = haversine_km(plat, plng, p["lat"], p["lng"])
            if dist > 5.0:
                pen += min(100, int(60 + (dist - 5.0) * 4))
                reasons.append(("high" if dist >= 10.0 else "med",
                               f"Pin location is {dist:.1f} km away from {d['locality']} centre (exceeds 5 km threshold)"))
            else:
                good.append(f"Pin location matches {d['locality']} area ({dist:.1f} km from centre)")
        except (ValueError, TypeError):
            pass

    if not reasons:
        good.append("Details are internally consistent")
    return min(100, pen), reasons, good


def _lister(info):
    verified, reports = info.get("verified", 0), info.get("reports", 0)
    pen = 50 if verified == 0 else 20 if verified < 3 else 0
    reasons, good = [], []
    if verified == 0:
        reasons.append(("low", "Lister wallet has no verified listings yet"))
    else:
        good.append(f"Lister has {verified} verified listing(s) on-chain")
    if reports:
        pen += 20 * reports
        reasons.append(("med", f"Lister has {reports} report(s) against their listings"))
    return min(100, pen), reasons, good


def score_listing(d, n_photos, duplicates, lister_info):
    reasons, good, breakdown = [], [], {}
    for name, (pen, r, g) in {
        "price": _price(d),
        "text": _text(d.get("description", "")),
        "duplicate": (100, [("high", f"Photo already used in listing #{x['listing_id']} by {x['wallet'][:8]}... (Hamming distance {x['distance']})") for x in duplicates[:3]], [])
        if duplicates else (0, [], ["No duplicate photos found"]),
        "lister": _lister(lister_info),
        "consistency": _consistency(d, n_photos),
    }.items():
        breakdown[name] = {"penalty": round(pen), "weight": WEIGHTS[name]}
        reasons += r
        good += g
    score = round(100 - sum(v["penalty"] * v["weight"] for v in breakdown.values()))
    if duplicates:
        score = min(score, 60)  # hard rule: reused photos can never be auto-verified
    score = max(0, min(100, score))
    verdict = "Verified" if score >= 70 else "Needs review" if score >= 40 else "Flagged"
    order = {"high": 0, "med": 1, "low": 2}
    reasons.sort(key=lambda r: order[r[0]])
    return {"score": score, "verdict": verdict,
            "reasons": [{"sev": s, "text": t} for s, t in reasons],
            "positives": good, "breakdown": breakdown}
