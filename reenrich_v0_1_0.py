"""Re-run the county assessor lookup for a single existing lead, in place.

The dashboard "Re-run assessor lookup" button calls reenrich(). On a successful
match it upgrades the lead's property row in place (real parcel + owner + value)
and flips the lead_event verdict while PRESERVING the original lead date - the
same in-place upgrade proven on the 2026-06-11 King County condo leads. On a
failure it records WHAT the assessor returned (the parcel/owner it found,
candidate condo unit owners, or "no parcel found") on the property's
last_lookup_* fields, so the lead detail page can show why it didn't match
instead of just failing silently.

Single write path, mirrors the scraper/intake ingest semantics (county+parcel
dedup, latest-non-blank-wins) but targeted at one existing lead. The caller owns
the connection; reenrich() commits its own change.
"""
import os

import propintel_db_v0_1_0 as pdb
import snoco_scraper_v2_8_1 as scraper

HERE = os.path.dirname(os.path.abspath(__file__))

# Verdicts that mean "this really is the lead's property" -> safe to attach and
# upgrade in place. MISMATCH (or an owner-less master) is treated as a failure
# whose finding is recorded but not attached.
_ATTACH_VERDICTS = {"CONFIRMED", "LIKELY", "PARTIAL", "REVIEW"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _lead_context(conn, contact_id, property_id):
    c = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
    p = conn.execute("SELECT * FROM properties WHERE id=?", (property_id,)).fetchone()
    le = conn.execute(
        "SELECT * FROM lead_events WHERE contact_id=? AND property_id=? "
        "ORDER BY id DESC LIMIT 1", (contact_id, property_id)).fetchone()
    return c, p, le


def _owner_str(data):
    return " ".join(filter(None, [pdb._norm(data.get("Owner 1 First Name")),
                                  pdb._norm(data.get("Owner 1 Last Name"))])).strip()


def _condo_candidates(master_pin, limit=6):
    """A few unit owner names under a condo master parcel - shown when no unit
    matched the lead, so the user can see who the assessor lists there."""
    import requests
    sess = requests.Session()
    sess.headers.update(scraper.HTTP_HEADERS)
    major = master_pin[:6]
    names, empty = [], 0
    for m in range(10, 2001, 10):
        owner = scraper._kc_unit_owner(f"{major}{m:04d}", sess)
        if owner:
            full = " ".join(filter(None, [owner.get("Owner 1 Last Name", ""),
                                          owner.get("Owner 1 First Name", "")])).strip()
            if full:
                names.append(full)
            empty = 0
        elif names:
            empty += 1
            if empty >= 12:
                break
    return len(names), names[:limit]


def _diagnose_failure(address, county, lead_data, owner_less_master=False):
    """Build a human-readable explanation of why the lookup didn't produce a
    matching owner, including what the assessor DID return."""
    ll = pdb._norm(lead_data.get("Lead Last Name")) or "(no name)"
    if county != "king":
        return (f"Snohomish County's Public Access portal returned no unambiguous "
                f"match for '{address}'. Verify the street number/spelling (the "
                "portal matches on house number + street name), or look it up at "
                "wa-snohomish.publicaccessnow.com and correct the address via Edit "
                "contact.")
    resolved = scraper.kc_resolve_address_live(address)
    if not resolved:
        return (f"King County's address layer found no parcel for '{address}'. "
                "The address may be new, unaddressed, or recorded differently by "
                "the county. Verify the spelling/number and re-run.")
    pin = resolved["pin"]
    if owner_less_master or scraper.kc_is_condo(pin):
        n, names = _condo_candidates(pin)
        sample = "; ".join(names) if names else "none readable"
        return (f"Address resolves to a condominium/townhome complex (master "
                f"parcel {pin}) with {n} units, but none are owned by '{ll}'. "
                f"Sample unit owners found: {sample}. The lead may own under a "
                "different name, own a unit numbered outside the scanned range, or "
                "not own in this complex (e.g. a renter).")
    return (f"Found King County parcel {pin} for this address, but its assessor "
            "record carries no owner or value (vacant, exempt, or a master "
            "parcel). Nothing to match against.")


def _upgrade_in_place(conn, p, le, data, when):
    """Attach the resolved assessor record to this lead's existing rows without
    creating duplicates or losing the original lead date. Returns the effective
    property id the lead now points at."""
    real_parcel = pdb._norm(data.get("Parcel Number"))
    real_county = pdb._norm(data.get("County"))
    status, nr, conf, rel, reason = pdb._analyze_match(data)

    clash = conn.execute(
        "SELECT id FROM properties WHERE county=? AND parcel_number=? AND id<>?",
        (real_county, real_parcel, p["id"])).fetchone()

    if clash:
        # The real parcel already exists as another property row. Re-point this
        # lead_event to it and flip the verdict; drop the now-empty placeholder.
        eff_pid = clash["id"]
        if le:
            conn.execute(
                "UPDATE lead_events SET property_id=?, ownership_match=?, "
                "needs_review=?, match_confidence=?, match_relationship=?, "
                "match_reason=? WHERE id=?",
                (eff_pid, status, int(nr), int(conf), rel, reason, le["id"]))
        leftover = conn.execute(
            "SELECT COUNT(*) FROM lead_events WHERE property_id=?", (p["id"],)).fetchone()[0]
        if leftover == 0 and pdb._norm(p["parcel_number"]).startswith(("UNENRICHED-", "NOADDR-")):
            conn.execute("DELETE FROM properties WHERE id=?", (p["id"],))
        return eff_pid

    # Re-point the existing (often placeholder) row at the real parcel, then let
    # upsert_property merge the assessor fields onto that same row in place.
    conn.execute("UPDATE properties SET parcel_number=?, county=? WHERE id=?",
                 (real_parcel, real_county, p["id"]))
    prop_fields = {col: data.get(csv_h, "") for csv_h, col in pdb.CSV_TO_PROPERTY.items()}
    received = (pdb._norm(le["received_date"]) if le else "") or when
    pid = pdb.upsert_property(conn, prop_fields, received, when)
    if le:
        conn.execute(
            "UPDATE lead_events SET ownership_match=?, needs_review=?, "
            "match_confidence=?, match_relationship=?, match_reason=? WHERE id=?",
            (status, int(nr), int(conf), rel, reason, le["id"]))
    return pid


def _record(conn, property_id, when, status, detail, verdict=None, effective_pid=None):
    pid = effective_pid or property_id
    conn.execute(
        "UPDATE properties SET last_lookup_at=?, last_lookup_status=?, "
        "last_lookup_detail=? WHERE id=?", (when, status, detail, pid))
    conn.commit()
    return {"ok": status == "MATCHED", "status": status, "detail": detail,
            "verdict": verdict, "property_id": pid}


# ── entry point ──────────────────────────────────────────────────────────────

def reenrich(conn, contact_id, property_id, when=None):
    """Re-run the assessor lookup for one lead. Returns a result dict:
    {ok, status, detail, verdict, property_id}. status is one of
    MATCHED / NO MATCH / NO ADDRESS / ERROR."""
    when = when or pdb._now()
    c, p, le = _lead_context(conn, contact_id, property_id)
    if not c or not p:
        return {"ok": False, "status": "ERROR", "detail": "Lead not found.",
                "verdict": None, "property_id": property_id}

    address = pdb._norm(p["property_address"]) or pdb._norm(p["property_street"])
    if not address:
        return _record(conn, property_id, when, "NO ADDRESS",
                       "No address on file to look up. Add one via Edit contact, "
                       "then re-run.")

    lead_data = {
        "Lead First Name": pdb._norm(c["first_name"]),
        "Lead Last Name": pdb._norm(c["last_name"]),
        "Lead Email": pdb._norm(c["email"]),
        "Lead Source": pdb._norm(le["lead_source"]) if le else "",
        "Lead Type": pdb._norm(le["lead_type"]) if le else "",
    }

    api_key = scraper.load_api_key(HERE)
    photo_folder = os.path.join(HERE, "property_photos")
    county = scraper.detect_county(address)

    try:
        if county == "king":
            data = scraper.lookup_property_kc_live(address, lead_data, api_key, photo_folder)
        else:
            sess, base = scraper.get_session()
            data = scraper.scrape_property(sess, address, base, api_key, photo_folder)
    except Exception as e:  # network / parse failure - report, don't crash the page
        return _record(conn, property_id, when, "ERROR",
                       f"Lookup error ({county.title()} County): {e}")

    if not data:
        return _record(conn, property_id, when, "NO MATCH",
                       _diagnose_failure(address, county, lead_data))

    data.update(lead_data)
    data = scraper.fix_owner_names_with_lead(data, lead_data)
    verdict = scraper.compute_ownership_match(data, lead_data)
    found_owner = bool(pdb._norm(data.get("Owner 1 Last Name")))
    parcel = pdb._norm(data.get("Parcel Number"))
    val = pdb._norm(data.get("Assessed Value"))
    owner = _owner_str(data)

    if found_owner and verdict in _ATTACH_VERDICTS:
        eff_pid = _upgrade_in_place(conn, p, le, data, when)
        status, *_ = pdb._analyze_match(data)
        detail = (f"Matched to {county.title()} parcel {parcel}: owner {owner}"
                  + (f", assessed ${val}" if val else "")
                  + f". Verdict {status}. Lead date preserved.")
        return _record(conn, property_id, when, "MATCHED", detail,
                       verdict=status, effective_pid=eff_pid)

    if found_owner:
        detail = (f"Found {county.title()} parcel {parcel}: owner {owner}"
                  + (f" (assessed ${val})" if val else "")
                  + f", which does NOT match lead "
                  f"{lead_data['Lead First Name']} {lead_data['Lead Last Name']} "
                  f"-> {verdict}. The property may have sold, or the lead is a "
                  "renter / different person.")
    else:
        detail = _diagnose_failure(address, county, lead_data, owner_less_master=True)
    return _record(conn, property_id, when, "NO MATCH", detail)
