"""
PropIntel Geocoder  v0.1.0
==========================
Turns a street address into latitude/longitude so the dashboard can do radius
("leads within N miles of a point") and, later, map filtering.

Source order (first hit wins):
    1. Google Geocoding API  - rooftop accuracy, uses the existing key in
       config.txt. Requires billing + the Geocoding API enabled on the Google
       Cloud project. If it returns REQUEST_DENIED / OVER_QUERY_LIMIT / no
       result, we fall through to the free sources, so the tool works even
       before billing is on; flip billing on and Google silently takes over.
    2. US Census one-line geocoder - free, no key, good rural coverage, but
       has gaps (misses some suburban addresses).
    3. Nominatim / OpenStreetMap - free, no key, 1 request/second. Catches the
       Census misses. Backfill sleeps between calls to respect the rate limit.

Use:
    python geocode_v0_1_0.py --test "13533 Boulder Ridge Rd, Snohomish, WA 98290"
    python geocode_v0_1_0.py --backfill            # geocode rows missing coords
    python geocode_v0_1_0.py --backfill --force    # re-geocode everything

The dashboard imports geocode_address() and haversine_miles() directly.
"""

import os
import sys
import math
import time

import requests

import propintel_db_v0_1_0 as pdb

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_TXT = os.path.join(HERE, "config.txt")

GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim asks for a descriptive UA that identifies the app + contact.
HTTP_HEADERS = {"User-Agent": "PropIntel/0.1 (real estate lead tool; aubiep@gmail.com)"}

# Polite pause between Nominatim hits (their usage policy is max 1 req/sec).
NOMINATIM_SLEEP = 1.1


def google_key():
    """Read the Google Maps key from config.txt, or '' if absent."""
    try:
        with open(CONFIG_TXT, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _try_google(address, session, timeout):
    key = google_key()
    if not key:
        return None
    try:
        r = session.get(GOOGLE_URL, params={"address": address, "key": key},
                        headers=HTTP_HEADERS, timeout=timeout)
        j = r.json()
    except Exception:
        return None
    if j.get("status") != "OK" or not j.get("results"):
        # REQUEST_DENIED (billing off), OVER_QUERY_LIMIT, ZERO_RESULTS -> fall through.
        return None
    g = j["results"][0]["geometry"]
    loc = g["location"]
    return {"lat": loc["lat"], "lng": loc["lng"], "source": "google",
            "accuracy": g.get("location_type", "")}


def _try_census(address, session, timeout):
    try:
        r = session.get(CENSUS_URL, params={"address": address,
                        "benchmark": "Public_AR_Current", "format": "json"},
                        headers=HTTP_HEADERS, timeout=timeout)
        matches = r.json()["result"]["addressMatches"]
    except Exception:
        return None
    if not matches:
        return None
    c = matches[0]["coordinates"]  # x = lng, y = lat
    return {"lat": c["y"], "lng": c["x"], "source": "census", "accuracy": "interpolated"}


def _try_nominatim(address, session, timeout):
    try:
        r = session.get(NOMINATIM_URL, params={"q": address, "format": "json",
                        "limit": 1, "countrycodes": "us"},
                        headers=HTTP_HEADERS, timeout=timeout)
        res = r.json()
    except Exception:
        return None
    if not res:
        return None
    return {"lat": float(res[0]["lat"]), "lng": float(res[0]["lon"]),
            "source": "nominatim", "accuracy": res[0].get("type", "")}


def geocode_address(address, session=None, timeout=20):
    """Resolve an address to {lat, lng, source, accuracy} or None.
    Tries Google, then Census, then Nominatim. Caller throttles Nominatim in
    batch loops (NOMINATIM_SLEEP)."""
    address = (address or "").strip()
    if not address:
        return None
    sess = session or requests.Session()
    for fn in (_try_google, _try_census, _try_nominatim):
        hit = fn(address, sess, timeout)
        if hit:
            return hit
    return None


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles between two lat/lng points."""
    r = 3958.7613  # earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def count_missing(conn):
    """How many properties (with a usable street) still lack coordinates."""
    return conn.execute(
        "SELECT COUNT(*) FROM properties "
        "WHERE latitude IS NULL AND TRIM(COALESCE(property_street,''))!=''"
    ).fetchone()[0]


def backfill(conn, force=False, limit=None, verbose=True):
    """Geocode properties that have an address but no coordinates (or all, if
    force). Updates latitude/longitude/geocode_source/geocoded_at. Prefers the
    full property_address, falling back to street + city + state + zip.
    Returns {'geocoded': n, 'failed': n, 'by_source': {...}}."""
    where = "TRIM(COALESCE(property_street,''))!=''"
    if not force:
        where += " AND latitude IS NULL"
    sql = ("SELECT id, property_address, property_street, property_city, "
           "property_state, property_zip FROM properties WHERE " + where + " ORDER BY id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    sess = requests.Session()
    out = {"geocoded": 0, "failed": 0, "by_source": {}}
    used_nominatim = False
    for r in rows:
        addr = (r["property_address"] or "").strip()
        if not addr:
            parts = [r["property_street"], r["property_city"], r["property_state"], r["property_zip"]]
            addr = ", ".join(p for p in (parts[:2]) if p)
            tail = " ".join(p for p in (parts[2:]) if p)
            addr = f"{addr} {tail}".strip()
        hit = geocode_address(addr, session=sess)
        if hit:
            conn.execute(
                "UPDATE properties SET latitude=?, longitude=?, geocode_source=?, "
                "geocoded_at=? WHERE id=?",
                (hit["lat"], hit["lng"], hit["source"], pdb._now(), r["id"]))
            out["geocoded"] += 1
            out["by_source"][hit["source"]] = out["by_source"].get(hit["source"], 0) + 1
            if verbose:
                print(f"  [{hit['source']:9}] {addr}  ->  {hit['lat']:.6f},{hit['lng']:.6f}")
            if hit["source"] == "nominatim":
                used_nominatim = True
        else:
            out["failed"] += 1
            if verbose:
                print(f"  [FAILED   ] {addr}")
        # Throttle only when we actually leaned on Nominatim this round.
        if used_nominatim:
            time.sleep(NOMINATIM_SLEEP)
            used_nominatim = False
    conn.commit()
    return out


def main():
    args = sys.argv[1:]
    if "--test" in args:
        i = args.index("--test")
        addr = args[i + 1] if i + 1 < len(args) else ""
        hit = geocode_address(addr)
        print(hit if hit else "No geocode result.")
        return
    if "--backfill" in args:
        force = "--force" in args
        conn = pdb.connect()
        pdb.init_db(conn)
        missing = count_missing(conn)
        print(f"Properties missing coordinates: {missing}"
              + ("  (--force: re-geocoding ALL)" if force else ""))
        res = backfill(conn, force=force)
        conn.close()
        print(f"\nDone. Geocoded {res['geocoded']}, failed {res['failed']}. "
              f"By source: {res['by_source']}")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
