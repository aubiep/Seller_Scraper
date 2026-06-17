"""
Homebot Diagnostic  v0.1.0
==========================
Proves the Homebot API plumbing before any bulk enrollment. Unlike a physical
letter, the safe first call here is a READ: filtering clients by an email costs
nothing and creates nothing, so it verifies the token and base URL with zero
side effects. A guarded single create is offered only after the read succeeds.

Run (needs an API token in config/homebot.json or env HOMEBOT_API_TOKEN):
    python homebot_diagnostic_v0_1_0.py

Steps:
  1. Load config; confirm a token is present.
  2. READ: GET /clients?filter[email]=<a probably-absent address>. Proves auth.
  3. Build (but do not send) a sample Client + Home payload from a real DB lead.
  4. Offer a single guarded create (type CREATE to proceed). This DOES enroll
     that one real person on the Market Digest, so it is opt-in.
"""

import json
import os
import sys

import propintel_db_v0_1_0 as pdb
import homebot_api_v0_1_0 as hb
import homebot_push_v0_1_0 as push

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE_EMAIL = "propintel-diagnostic-no-such-user@example.com"


def _step(n, msg):
    print(f"\n[{n}] {msg}")


def main():
    print("=" * 64)
    print("Homebot Diagnostic v0.1.0")
    print("=" * 64)

    _step(1, "Load config + token")
    client, cfg = hb.HomebotClient.from_config(HERE)
    print(f"  base_url = {client.base_url}")
    print(f"  auth     = {client.auth_scheme} <token>")
    if not client.has_token():
        print("  FAIL: no API token. Put it in config/homebot.json or set HOMEBOT_API_TOKEN.")
        return 1
    print(f"  token    = present ({len(client.token)} chars)")

    _step(2, "READ probe: GET /clients?filter[email]=<absent> (no side effects)")
    try:
        found = client.find_client_by_email(PROBE_EMAIL)
        print(f"  auth OK. Probe returned: {found!r} (None/empty is expected and fine).")
    except hb.HomebotError as e:
        print(f"  FAIL: {e}")
        if e.status in (401, 403):
            print("  -> token rejected. Check the token value and the auth scheme.")
        return 1

    _step(3, "Build a sample payload from a real DB lead (not sent)")
    conn = pdb.connect(push.DB_PATH)
    pdb.init_db(conn)
    rows = push.select_leads(conn, limit=1)
    if not rows:
        print("  No eligible seller leads in the DB to sample. Auth is verified; stopping here.")
        conn.close()
        return 0
    r = rows[0]
    client_attrs = {k: v for k, v in push.build_client_attributes(r, cfg.get("defaults", {})).items() if v is not None}
    home_attrs = {k: v for k, v in push.build_home_attributes(r).items() if v is not None}
    name = f"{r['first_name']} {r['last_name']}".strip()
    print(f"  sample lead: {name} <{r['email']}>")
    print("  CLIENT envelope:", json.dumps(client._envelope("client", client_attrs)))
    print("  HOME attributes:", json.dumps(home_attrs))

    _step(4, "Optional: create this ONE client + home for real")
    print(f"  This will enroll {name} on the Market Digest. Type CREATE to proceed, anything else to skip.")
    try:
        answer = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer != "CREATE":
        print("  Skipped. Auth and payload are verified; no record created.")
        conn.close()
        return 0

    try:
        existing = client.find_client_by_email(r["email"])
        if existing:
            print(f"  Client already exists (id={existing.get('id')}). Not creating a duplicate.")
            conn.close()
            return 0
        created = client.create_client(client_attrs)
        cid = created.get("id")
        print(f"  created client id={cid}")
        home = client.create_home(cid, home_attrs)
        print(f"  created home id={home.get('id')}")
        print("  SUCCESS. Verify in Homebot that the client + home appear and the digest is queued.")
    except hb.HomebotError as e:
        print(f"  FAIL: {e}")
        conn.close()
        return 1
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
