"""
Market Leader / HouseValues .md importer  v0.1.0
================================================
Imports the complete HouseValues/Market Leader lead export (a CSV saved as .md)
into propintel.db. This export carries what the notification EMAILS can't: the
real submission date, email, and phone, all in one row. So it's the authoritative
source for these leads (use the live inbox watcher for Zurple/Brivity).

Each row -> a structured lead -> the SAME proven enrich + ingest pipeline the
scraper/watcher use (assessor lookup, ownership match, geocode, dedup), with the
lead's REAL date carried through as received_date (so dashboard recency and the
repeat signal are accurate, not stamped with the import day).

File format (header row required):
    Date,Name,Email,Phone,Property Address,Activity

Run:
    python lead_md_import_v0_1_0.py --dry-run     # parse + show new vs existing, NO write
    python lead_md_import_v0_1_0.py               # live: enrich + ingest (backs up first)
    python lead_md_import_v0_1_0.py --file imports/Other.md --limit 5

Dry-run does no network and no DB write. Live enrichment hits the county sites
(a few minutes for a full file) and is safe to re-run (ingest dedups).
"""

import argparse
import csv
import os
import re
import sys

import propintel_db_v0_1_0 as pdb
import lead_intake_v0_1_0 as intake

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(HERE, "imports", "AllHVLeadsFromFeb2026.md")


def clean_phone(raw):
    """Normalize a phone to 10 digits ('4252735753'); drop a US leading 1.
    Returns '' if there aren't enough digits to be a real number."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def split_name(raw):
    """Split a single 'Name' field into (first, last). first token is the first
    name, last token the surname; middle names are dropped for the match key.
    Casing is fixed downstream by pdb.titlecase_name at ingest."""
    parts = (raw or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def looks_like_junk(name):
    """Skip obviously garbled rows (mojibake, no letters)."""
    if not name or not re.search(r"[A-Za-z]", name):
        return True
    if "â" in name:  # 'â' mojibake, e.g. 'Itâs the'
        return True
    return False


def parse_file(path):
    """Read the .md/CSV file into structured leads. Returns (leads, skipped)."""
    leads, skipped = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("Name") or "").strip()
            addr = (row.get("Property Address") or "").strip()
            date = (row.get("Date") or "").strip()
            email = (row.get("Email") or "").strip()
            phone = clean_phone(row.get("Phone"))
            if looks_like_junk(name) or not addr:
                skipped.append((name or "(no name)", addr or "(no address)"))
                continue
            first, last = split_name(name)
            leads.append({
                "first_name": first, "last_name": last,
                "email": email, "phone": phone,
                "property_address": addr,
                "source": "HouseValues", "lead_type": "Seller",
                "received_date": date,
                "activity": (row.get("Activity") or "").strip(),
            })
    return leads, skipped


def overlap_report(conn, leads):
    """Split leads into (already-in-db, brand-new) by email, else by name."""
    existing, new = [], []
    for ld in leads:
        hit = None
        if ld["email"]:
            hit = conn.execute("SELECT id FROM contacts WHERE lower(email)=? AND email<>''",
                               (ld["email"].lower(),)).fetchone()
        if not hit and (ld["first_name"] or ld["last_name"]):
            hit = conn.execute(
                "SELECT id FROM contacts WHERE lower(first_name)=? AND lower(last_name)=?",
                (pdb.titlecase_name(ld["first_name"]).lower(),
                 pdb.titlecase_name(ld["last_name"]).lower())).fetchone()
        (existing if hit else new).append(ld)
    return existing, new


def main():
    ap = argparse.ArgumentParser(description="Import a HouseValues/Market Leader .md export.")
    ap.add_argument("--file", default=DEFAULT_FILE, help="path to the .md/CSV export")
    ap.add_argument("--dry-run", action="store_true", help="parse + report only; no write")
    ap.add_argument("--limit", type=int, help="cap the number of leads processed")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        return 1

    leads, skipped = parse_file(args.file)
    if args.limit:
        leads = leads[:args.limit]

    conn = pdb.connect()
    pdb.init_db(conn)
    existing, new = overlap_report(conn, leads)

    print(f"Parsed {len(leads)} lead(s) from {os.path.basename(args.file)} "
          f"({len(skipped)} skipped as junk/no-address).")
    print(f"  Already in DB (will backfill email/phone + add a dated event): {len(existing)}")
    print(f"  Brand new (will be created + enriched):                        {len(new)}")
    if skipped:
        print("  Skipped:", ", ".join(f"{n}" for n, _ in skipped))

    print("\nSample of cleaned rows:")
    for ld in leads[:8]:
        nm = f"{pdb.titlecase_name(ld['first_name'])} {pdb.titlecase_name(ld['last_name'])}".strip()
        print(f"  {ld['received_date']} | {nm:24} | {ld['email'] or '(no email)':32} "
              f"| {ld['phone'] or '(no phone)':10} | {ld['property_address'][:40]}")

    if args.dry_run:
        conn.close()
        print("\nDRY RUN: nothing written. Re-run without --dry-run to enrich + ingest.")
        return 0

    conn.close()
    print(f"\nLIVE: enriching + ingesting {len(leads)} lead(s) (DB backed up first). "
          f"This hits the county sites and may take a few minutes...")
    results = intake.enrich_and_ingest(leads, verbose=True)
    enriched = sum(1 for r in results if r["status"] == "enriched")
    failed = sum(1 for r in results if r["status"] == "lookup_failed")
    print(f"\nDone. Enriched + ingested {enriched}; lookup failed {failed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
