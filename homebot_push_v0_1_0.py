"""
Homebot Push  v0.1.0
====================
Enrolls verified seller leads from propintel.db onto the Homebot Market Digest
by creating a Homebot Client (+ Home) for each. Folded into the unified app:
reads the same DB the dashboard shows, records each result in the `outreach`
table (channel='homebot') so the dashboard can display send state.

Selection (the roadmap's rule): lead_type = 'Seller', ownership CONFIRMED or
LIKELY, and a non-empty email. One Homebot Client is keyed by email; we dedupe
against Homebot first (find_client_by_email) so re-running does not double-add.

Field mapping  propintel.db -> Homebot:
    Client:  first-name <- first_name,  last-name <- last_name,
             email <- email,  mobile <- phone (normalized to +1XXXXXXXXXX),
             locale <- config default
    Home:    address-street <- property_street,  address-zip <- 5-digit zip
    Empty/missing values are omitted from the payload, never sent blank.

VERIFIED against the live API (2026-06-04, create+delete round-trip):
  - data.type literals "clients" / "homes" are correct.
  - `lead-source` is NOT settable on create (400 "Param not allowed"); omitted.
  - Homebot DERIVES home value/beds/baths/sqft from the address via its own AVM:
    those fields come back null on create even when sent, so we send only the
    address. address-street and address-zip do persist.

USAGE (dry run is the default and makes NO network calls):
    python homebot_push_v0_1_0.py                 # preview every payload
    python homebot_push_v0_1_0.py --email a@b.com # preview one lead
    python homebot_push_v0_1_0.py --live          # actually create in Homebot
    python homebot_push_v0_1_0.py --live --limit 1  # push just the first

Live mode requires an API token in config/homebot.json (or HOMEBOT_API_TOKEN).
Run homebot_diagnostic_v0_1_0.py first to prove auth and the create path.
"""

import argparse
import json
import os
import sys

import propintel_db_v0_1_0 as pdb
import homebot_api_v0_1_0 as hb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, pdb.DEFAULT_DB_FILENAME)


# ── field parsing ────────────────────────────────────────────────────────────

def _zip5(s):
    if not s:
        return None
    digits = str(s).strip()[:5]
    return digits or None


def _mobile(s):
    """'425-626-9087' -> '+14256269087'. Returns None unless it yields a clean
    10-digit (or 1+10) US number; never sends a malformed value."""
    if not s:
        return None
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


# ── payload builders ─────────────────────────────────────────────────────────

def build_client_attributes(row, defaults):
    return {
        "first-name": (row["first_name"] or "").strip() or None,
        "last-name": (row["last_name"] or "").strip() or None,
        "email": (row["email"] or "").strip() or None,
        "mobile": _mobile(row["phone"] if "phone" in row.keys() else None),
        "locale": defaults.get("locale"),
    }


def build_home_attributes(row):
    # Homebot derives value/beds/baths/sqft from the address (its own AVM); those
    # fields are ignored on create. Send only the address, which is what persists.
    return {
        "address-street": (row["property_street"] or "").strip() or None,
        "address-zip": _zip5(row["property_zip"]),
    }


# ── selection ────────────────────────────────────────────────────────────────

SELECT_SQL = """
SELECT le.id AS lead_event_id, le.contact_id, le.property_id, le.lead_type,
       le.ownership_match, ct.first_name, ct.last_name, ct.email, ct.phone,
       p.property_street, p.property_zip, p.property_city
FROM lead_events le
JOIN contacts ct   ON ct.id = le.contact_id
JOIN properties p  ON p.id = le.property_id
WHERE le.lead_type = 'Seller'
  AND le.ownership_match IN ('CONFIRMED', 'LIKELY')
  AND ct.email IS NOT NULL AND TRIM(ct.email) != ''
ORDER BY ct.last_name, ct.first_name
"""


def select_leads(conn, email=None, limit=None):
    rows = conn.execute(SELECT_SQL).fetchall()
    if email:
        rows = [r for r in rows if (r["email"] or "").lower() == email.lower()]
    if limit:
        rows = rows[:limit]
    return rows


# ── outreach logging ─────────────────────────────────────────────────────────

def _record(conn, row, status, detail):
    conn.execute(
        "INSERT INTO outreach (contact_id, property_id, channel, template, status, detail, created_at)"
        " VALUES (?,?,?,?,?,?, datetime('now'))",
        (row["contact_id"], row["property_id"], "homebot", "market_digest", status, detail),
    )
    conn.commit()


# ── run ──────────────────────────────────────────────────────────────────────

def enroll_one(client, conn, row, defaults, live):
    """Process a single lead. Returns a result dict (no printing). For dry runs,
    builds the payloads and reports status 'dry' without any network call."""
    name = f"{row['first_name']} {row['last_name']}".strip()
    client_attrs = {k: v for k, v in build_client_attributes(row, defaults).items() if v is not None}
    home_attrs = {k: v for k, v in build_home_attributes(row).items() if v is not None}
    res = {"name": name, "email": row["email"], "ownership": row["ownership_match"],
           "client_attrs": client_attrs, "home_attrs": home_attrs,
           "status": "dry", "detail": ""}
    if not live:
        return res
    try:
        existing = client.find_client_by_email(row["email"])
        if existing:
            cid = existing.get("id")
            _record(conn, row, "skipped", f"client exists id={cid}")
            res.update(status="skipped", detail=f"already in Homebot (id={cid})")
            return res
        try:
            created = client.create_client(client_attrs)
        except hb.HomebotError as ce:
            # A bad phone shouldn't cost an enrollment; the digest needs only
            # email + address. Retry once without mobile.
            if client_attrs.get("mobile"):
                created = client.create_client(
                    {k: v for k, v in client_attrs.items() if k != "mobile"})
            else:
                raise
        cid = created.get("id")
        client.create_home(cid, home_attrs)
        _record(conn, row, "sent", f"client id={cid} + home created")
        res.update(status="sent", detail=f"created client id={cid} + home")
    except hb.HomebotError as e:
        _record(conn, row, "failed", str(e)[:300])
        res.update(status="failed", detail=str(e)[:300])
    return res


def run(email=None, limit=None, live=False, conn=None):
    """Core entry point. Returns {mode, counts, results, error}. Used by both the
    CLI and the dashboard. Opens its own DB connection if one isn't passed."""
    own_conn = conn is None
    if own_conn:
        conn = pdb.connect(DB_PATH)
        pdb.init_db(conn)
    client, cfg = hb.HomebotClient.from_config(HERE)
    defaults = cfg.get("defaults", {})
    rows = select_leads(conn, email=email, limit=limit)
    out = {"mode": "live" if live else "dry", "counts": {"sent": 0, "skipped": 0, "dry": 0, "failed": 0},
           "results": [], "error": None}
    if live and not client.has_token():
        out["error"] = "No API token (config/homebot.json or HOMEBOT_API_TOKEN)."
        if own_conn:
            conn.close()
        return out
    for r in rows:
        res = enroll_one(client, conn, r, defaults, live)
        out["results"].append(res)
        out["counts"][res["status"]] = out["counts"].get(res["status"], 0) + 1
    if own_conn:
        conn.close()
    return out


def push(email=None, limit=None, live=False):
    """CLI wrapper: run() + print."""
    out = run(email=email, limit=limit, live=live)
    mode = "LIVE" if live else "DRY RUN (no network calls)"
    print(f"Homebot push  [{mode}]  -  {len(out['results'])} lead(s) selected")
    if out["error"]:
        print("ERROR:", out["error"])
        return 1
    print("=" * 70)
    for res in out["results"]:
        print(f"\n{res['name']}  <{res['email']}>  [{res['ownership']}]")
        print("  CLIENT:", json.dumps(res["client_attrs"]))
        print("  HOME:  ", json.dumps(res["home_attrs"]))
        if res["status"] != "dry":
            print(f"  -> {res['status']}: {res['detail']}")
    print("\n" + "=" * 70)
    print("Summary:", json.dumps(out["counts"]))
    if not live:
        print("This was a dry run. Re-run with --live (and a token) to actually enroll.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Enroll verified seller leads on the Homebot Market Digest.")
    ap.add_argument("--live", action="store_true", help="actually create records (default: dry run)")
    ap.add_argument("--email", help="limit to a single lead by email")
    ap.add_argument("--limit", type=int, help="cap the number of leads processed")
    args = ap.parse_args()
    return push(email=args.email, limit=args.limit, live=args.live)


if __name__ == "__main__":
    sys.exit(main())
