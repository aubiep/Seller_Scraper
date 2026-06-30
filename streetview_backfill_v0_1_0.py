"""Backfill missing Street View photos for existing property rows.

Some leads were enriched in an earlier run before the Street View step (or before
Google billing was on), so their `properties.photo_file` is blank even though
Google DOES have street-level imagery for the address. This re-fetches the
Street View photo from Google for every property that has an address but no
usable photo file on disk, and writes the path back to `photo_file`.

Reuses the scraper's exact download function and filename convention, so the
result is identical to what a fresh scrape would have produced.

  python streetview_backfill_v0_1_0.py --dry-run   # show what would be fetched
  python streetview_backfill_v0_1_0.py             # fetch + update the DB

It never overwrites a photo that already exists on disk; it only fills gaps.
"""
import argparse
import os
import sys

import requests

import propintel_db_v0_1_0 as pdb
import snoco_scraper_v2_8_4 as scraper

HERE = os.path.dirname(os.path.abspath(__file__))
PHOTO_FOLDER = os.path.join(HERE, "property_photos")
META_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"


def _needs_photo(row):
    """True when the row has an address but no Street View image on disk."""
    if not (row["property_address"] or "").strip():
        return False
    pf = row["photo_file"] or ""
    return not (pf and os.path.exists(pf))


def _has_imagery(address, api_key):
    """Free metadata pre-check: True only when Google actually has Street View
    here. Skips the gray 'no imagery' placeholder that the static endpoint would
    otherwise save as a normal JPEG."""
    try:
        r = requests.get(META_URL, params={"location": address, "key": api_key},
                         timeout=15)
        return r.json().get("status") == "OK"
    except Exception:
        return False


def backfill(dry_run=False):
    api_key = scraper.load_api_key(HERE)
    if not api_key:
        print("No config.txt / API key found - cannot fetch Street View photos.")
        return 1

    conn = pdb.connect()
    rows = conn.execute(
        "SELECT id, property_address, owner1_last, photo_file "
        "FROM properties ORDER BY id").fetchall()

    targets = [r for r in rows if _needs_photo(r)]
    print(f"{len(rows)} properties, {len(targets)} missing a Street View photo.\n")

    fetched = skipped = failed = 0
    for r in targets:
        addr = r["property_address"]
        if not _has_imagery(addr, api_key):
            failed += 1
            print(f"  [no imagery]  #{r['id']}  {addr}")
            continue
        if dry_run:
            print(f"  [would fetch] #{r['id']}  {addr}")
            continue
        path = scraper.download_street_view(addr, r["owner1_last"] or "",
                                            api_key, PHOTO_FOLDER)
        if path:
            conn.execute("UPDATE properties SET photo_file=?, updated_at=CURRENT_TIMESTAMP "
                         "WHERE id=?", (path, r["id"]))
            conn.commit()
            fetched += 1
            print(f"  [saved]  #{r['id']}  {addr}")
        else:
            failed += 1
            print(f"  [no imagery]  #{r['id']}  {addr}")

    if dry_run:
        would = len(targets) - failed
        print(f"\nDry run: {would} would be fetched, {failed} have no Street View imagery. "
              f"Re-run without --dry-run to apply.")
    else:
        print(f"\nDone. Fetched {fetched}, no imagery for {failed}.")
    conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill missing Street View photos.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be fetched without calling Google or writing the DB.")
    args = ap.parse_args()
    sys.exit(backfill(dry_run=args.dry_run))
