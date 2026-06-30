"""
iAuto Send  v0.1.0
==================
The send path for the iAuto letter queue, folded into the unified app. Bridges
propintel.db <-> the template engine <-> the machine API client:

    queue_letter()   write an outreach row (channel='iauto', status='queued')
    send_outreach()  load the lead, merge the template, POST to the machine,
                     update the outreach row's status. Dry-run merges only.
    run_send()       send several queued rows; returns structured results.

Field mapping  propintel.db -> template placeholders (config/iauto_templates.json):
    first_name, last_name       <- contacts
    property_address            <- properties.property_street (clean street)
    property_city               <- properties.property_city
    mail_street/city/state/zip  <- the property address (homeowner at home)

While the machine is offline, send_outreach() catches the connection error,
marks the row 'failed' with a plain reason, and never raises. The merge step
runs regardless, so queueing and previewing work with no machine present.
"""

import json
import os

import requests

import propintel_db_v0_1_0 as pdb
import iauto_api_v0_1_0 as iauto_api
import iauto_template_v0_1_0 as iauto_template

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, pdb.DEFAULT_DB_FILENAME)
BUTTONS_CONFIG = os.path.join(HERE, "config", "iauto_templates.json")


def load_buttons():
    with open(BUTTONS_CONFIG, encoding="utf-8") as f:
        return json.load(f)["buttons"]


def load_config():
    """The whole iauto_templates.json (buttons + _about/_field_notes)."""
    with open(BUTTONS_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    """Write the whole config back, preserving structure and unicode."""
    with open(BUTTONS_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def build_lead_values(row):
    """Flat dict the template engine fills from. Missing fields become blank."""
    g = lambda k: (row[k] or "").strip() if k in row.keys() and row[k] else ""
    street = g("property_street")
    return {
        "first_name": g("first_name"),
        "last_name": g("last_name"),
        "property_address": street,
        "property_city": g("property_city"),
        "mail_street": street,
        "mail_city": g("property_city"),
        "mail_state": g("property_state"),
        "mail_zip": g("property_zip"),
    }


def lead_row(conn, contact_id, property_id):
    return conn.execute(
        "SELECT ct.first_name, ct.last_name, p.property_street, p.property_city, "
        "p.property_state, p.property_zip "
        "FROM contacts ct, properties p WHERE ct.id=? AND p.id=?",
        (contact_id, property_id),
    ).fetchone()


def queue_letter(conn, contact_id, property_id, button_key):
    """Add a letter to the queue. Returns the new outreach row id."""
    cur = conn.execute(
        "INSERT INTO outreach (contact_id, property_id, channel, template, status, queued_at, created_at)"
        " VALUES (?,?,?,?,?, datetime('now'), datetime('now'))",
        (contact_id, property_id, "iauto", button_key, "queued"),
    )
    conn.commit()
    return cur.lastrowid


def _set_status(conn, outreach_id, status, detail, mark_sent=False):
    if mark_sent:
        conn.execute("UPDATE outreach SET status=?, detail=?, sent_at=datetime('now') WHERE id=?",
                     (status, detail, outreach_id))
    else:
        conn.execute("UPDATE outreach SET status=?, detail=? WHERE id=?",
                     (status, detail, outreach_id))
    conn.commit()


def merge_for_outreach(conn, outreach_row, kind):
    """Return (merged_bytes, report, error). kind is 'letter' or 'envelope'."""
    buttons = load_buttons()
    btn = buttons.get(outreach_row["template"])
    if not btn:
        return None, None, f"unknown template button '{outreach_row['template']}'"
    spec = btn.get(kind)
    if not spec:
        return None, None, f"button '{outreach_row['template']}' has no {kind}"
    row = lead_row(conn, outreach_row["contact_id"], outreach_row["property_id"])
    if not row:
        return None, None, "lead/property not found"
    values = build_lead_values(row)
    path = os.path.join(HERE, spec["path"])
    merged_bytes, report = iauto_template.merge_to_bytes(path, spec["fields"], values)
    return merged_bytes, report, None


def send_outreach(conn, outreach_id, kind="letter", dry_run=False, client=None,
                  logged_in=False):
    """
    Merge and (unless dry_run) POST one queued letter/envelope to the machine.
    Returns a result dict; never raises on a network failure.
    """
    o = conn.execute("SELECT * FROM outreach WHERE id=?", (outreach_id,)).fetchone()
    if not o:
        return {"outreach_id": outreach_id, "status": "error", "detail": "no such outreach row"}
    name_row = lead_row(conn, o["contact_id"], o["property_id"])
    name = f"{name_row['first_name']} {name_row['last_name']}".strip() if name_row else "?"

    merged_bytes, report, err = merge_for_outreach(conn, o, kind)
    if err:
        if not dry_run:
            _set_status(conn, outreach_id, "failed", err)
        return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "failed", "detail": err}

    if dry_run:
        return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "dry",
                "detail": f"{len(merged_bytes)} bytes",
                "applied": report["applied"]}

    # Live send. Catch connection problems so an offline machine just fails the row.
    try:
        if client is None:
            client, creds = iauto_api.IAutoClient.from_config(HERE)
            client.login(creds["uin"], creds["passwd"])
        elif not logged_in:
            pass  # caller is responsible for logging in a shared client
        result = client.write_template(merged_bytes, filename=f"{kind}_{outreach_id}.json")
        code = result.get("error")
        if code == 0:
            _set_status(conn, outreach_id, "sent", f"{kind} accepted by machine", mark_sent=True)
            return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "sent",
                    "detail": f"{kind} accepted by machine"}
        detail = f"{kind} rejected: error {code} ({result.get('error_meaning')})"
        _set_status(conn, outreach_id, "failed", detail)
        return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "failed", "detail": detail}
    except (requests.ConnectionError, requests.Timeout) as e:
        detail = f"machine unreachable ({type(e).__name__}). Is it powered on and on the LAN?"
        _set_status(conn, outreach_id, "failed", detail)
        return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "failed", "detail": detail}
    except iauto_api.IAutoError as e:
        detail = f"machine API error: {e}"
        _set_status(conn, outreach_id, "failed", detail)
        return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "failed", "detail": detail}
    except requests.RequestException as e:
        detail = f"send failed: {type(e).__name__}: {e}"
        _set_status(conn, outreach_id, "failed", detail)
        return {"outreach_id": outreach_id, "name": name, "kind": kind, "status": "failed", "detail": detail}


def run_send(conn, outreach_ids=None, kind="letter", dry_run=False):
    """Send a set of queued rows (default: all 'queued' iauto rows). Shares one
    logged-in client across the batch. Returns {counts, results}."""
    if outreach_ids is None:
        outreach_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM outreach WHERE channel='iauto' AND status='queued' ORDER BY id")]
    results = []
    client = None
    if not dry_run and outreach_ids:
        try:
            client, creds = iauto_api.IAutoClient.from_config(HERE)
            client.login(creds["uin"], creds["passwd"])
        except Exception:
            client = None  # send_outreach will re-attempt per-row and record the failure
    for oid in outreach_ids:
        results.append(send_outreach(conn, oid, kind=kind, dry_run=dry_run,
                                     client=client, logged_in=client is not None))
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"counts": counts, "results": results}
