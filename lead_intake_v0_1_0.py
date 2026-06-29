"""
Lead Intake  v0.1.0
===================
Takes structured leads (parsed from inbox emails) and runs them through the
SAME enrichment + ownership-match + database path the scraper already uses, so
an emailed lead comes out fully verified, valued, photographed, and queued -
with no copy-paste and no CRM click.

This is the ingestion half of the email-intake pipeline. The parsing half is
done by Claude (the LLM) reading the lead emails and producing the structured
dicts this module accepts, so no extra API key or SDK is needed for the
Claude-driven flow. A future standalone watcher could parse with its own LLM
call and feed the same function.

A structured lead is a dict:
    {first_name, last_name, email, phone, property_address,
     source ("Zurple"/"Brivity"/...), lead_type ("Seller"/"Buyer"/"")}

enrich_and_ingest(leads) -> list of per-lead result dicts. Reuses:
    scraper.detect_county / build_lead_data / lookup_property_kc_live /
    scrape_property / fix_owner_names_with_lead / compute_ownership_match /
    save_to_database  (all from snoco_scraper_v2_7_1)

Leads with no property_address are recorded as 'no_address' and skipped for
enrichment (you can still add them as contacts via the dashboard Add form).
"""

import os
from datetime import datetime

import snoco_scraper_v2_7_4 as scraper
import propintel_db_v0_1_0 as pdb  # noqa: F401  (save_to_database uses it)
import propintel_backup_v0_1_0 as backup

HERE = os.path.dirname(os.path.abspath(__file__))


def _to_scraper_lead(lead):
    """Map a parsed-email lead to the dict build_lead_data expects."""
    return {
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "email": lead.get("email", ""),
        "phone": lead.get("phone", ""),
        "source": lead.get("source", "") or lead.get("lead_source", ""),
        "lead_type": lead.get("lead_type", "") or "Seller",
        "address": lead.get("property_address", ""),
    }


def enrich_and_ingest(leads, verbose=True):
    """Enrich each lead via the live assessor lookup and save to propintel.db.
    Returns a list of {lead, status, match} dicts. status is one of:
    'enriched' | 'lookup_failed' | 'no_address'."""
    script_dir = HERE
    api_key = scraper.load_api_key(script_dir)
    photo_folder = os.path.join(script_dir, "property_photos")

    addressed = [l for l in leads if l.get("property_address", "").strip()]
    counties = {scraper.detect_county(l["property_address"]) for l in addressed}

    session = base_resp = None
    if "snohomish" in counties:
        try:
            session, base_resp = scraper.get_session()
        except Exception as e:
            if verbose:
                print(f"[WARN] Snohomish site unreachable: {e}")

    next_row = scraper.get_next_row_number(script_dir)
    today = datetime.now().strftime("%m/%d/%Y")

    all_data, results = [], []
    for lead in leads:
        addr = lead.get("property_address", "").strip()
        name = f"{lead.get('first_name','')} {lead.get('last_name','')}".strip()
        if not addr:
            results.append({"lead": lead, "status": "no_address", "match": None})
            if verbose:
                print(f"  [no address] {name} <{lead.get('email','')}>")
            continue

        lead_data = scraper.build_lead_data(_to_scraper_lead(lead))
        county = scraper.detect_county(addr)
        data = None
        try:
            if county == "king":
                data = scraper.lookup_property_kc_live(addr, lead_data, api_key, photo_folder)
            elif session:
                data = scraper.scrape_property(session, addr, base_resp, api_key, photo_folder)
        except Exception as e:
            if verbose:
                print(f"  [error] {name}: {e}")
            data = None

        if data:
            data.update(lead_data)
            data = scraper.fix_owner_names_with_lead(data, lead_data)
            data["Ownership Match"] = scraper.compute_ownership_match(data, lead_data)
            data["Row #"] = str(next_row)
            # Use the lead's real submission date when the caller supplies one
            # (e.g. the Market Leader/HouseValues .md export); else today.
            data["Date Retrieved"] = lead.get("received_date") or today
            next_row += 1
            all_data.append(data)
            results.append({"lead": lead, "status": "enriched",
                            "match": data["Ownership Match"]})
            if verbose:
                print(f"  [enriched] {name} | {county} | {data['Ownership Match']}")
        else:
            results.append({"lead": lead, "status": "lookup_failed", "match": None})
            if verbose:
                print(f"  [lookup failed] {name} | {addr}")

    if all_data:
        backup.make_backup(verbose=False)  # snapshot before a real write
        scraper.save_to_database(all_data, script_dir)
        if verbose:
            print(f"\nSaved {len(all_data)} enriched lead(s) to propintel.db (backed up first)")
    return results


def ingest_addressless(leads, verbose=True):
    """Capture no-address SELLER leads (name/email/phone, no property) as contacts
    flagged NO ADDRESS, for direct follow-up. Used for Zurple 'asked for a CMA -
    no matching address' alerts. Skips leads with neither a name nor an email.
    Returns the count captured."""
    candidates = [l for l in leads
                  if (l.get("first_name") or l.get("last_name") or l.get("email"))]
    if not candidates:
        return 0
    backup.make_backup(verbose=False)
    conn = pdb.connect()
    pdb.init_db(conn)
    when = pdb._now()
    captured = 0
    for l in candidates:
        cid = pdb.add_addressless_lead(
            conn, l.get("first_name", ""), l.get("last_name", ""),
            l.get("email", ""), l.get("phone", ""),
            l.get("source", "") or "Zurple", l.get("received_date", ""),
            seen_address=l.get("property_address", ""), when=when)
        if cid:
            captured += 1
            if verbose:
                print(f"  [no-addr seller] {l.get('first_name','')} {l.get('last_name','')} "
                      f"<{l.get('email','') or '-'}>")
    conn.commit()
    conn.close()
    return captured


if __name__ == "__main__":
    # Tiny self-check: confirm the scraper wiring imports and a lead maps cleanly.
    sample = {"first_name": "Susan", "last_name": "Prince",
              "email": "Sprince202@aol.com", "phone": "(425) 890-3808",
              "property_address": "12940 177TH PL NE, REDMOND, WA 98052",
              "source": "Zurple", "lead_type": "Seller"}
    print("scraper functions present:",
          all(hasattr(scraper, fn) for fn in
              ("detect_county", "build_lead_data", "lookup_property_kc_live",
               "scrape_property", "compute_ownership_match", "save_to_database")))
    print("county route for sample:", scraper.detect_county(sample["property_address"]))
    print("lead_data:", scraper.build_lead_data(_to_scraper_lead(sample)))
    print("OK (no network/enrichment performed in this self-check)")
