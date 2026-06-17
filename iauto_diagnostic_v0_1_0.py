"""
iAuto Phase 1 Diagnostic  v0.1.0
================================
Proves the plumbing between this code and the physical iAuto-01 machine before
any UI is wired up. Throwaway / run-on-demand, not part of the app.

What it does, in order, reporting each step:
  1. Load config (machine + credentials + the seller_lead_initial button).
  2. GET /machine_status  (no auth) and print the machine list.
  3. GET /login           and confirm {"error":0}.
  4. Load the real letter template, merge SAMPLE lead data, and show every
     cell's before -> after. Write the merged JSON to disk so you can inspect it.
  5. Pause for an explicit "SEND" confirmation.
  6. POST /write_template and print the result code in plain English.

Run (machine must be powered on, loaded with paper, and reachable on the LAN):
    python iauto_diagnostic_v0_1_0.py

Nothing is sent to the machine unless you type SEND at the prompt. The letter
goes to the machine's active write queue, so expect it to start writing.
"""

import json
import os
import sys

import iauto_api_v0_1_0 as iauto_api
import iauto_template_v0_1_0 as iauto_template

HERE = os.path.dirname(os.path.abspath(__file__))

# A sample seller lead. Real sends will pull these from propintel.db.
SAMPLE_LEAD = {
    "first_name": "Jordan",
    "last_name": "Sample",
    "property_address": "13533 Boulder Ridge Rd",
    "property_city": "Snohomish",
    "mail_street": "13533 Boulder Ridge Rd",
    "mail_city": "Snohomish",
    "mail_state": "WA",
    "mail_zip": "98290",
}


def _step(n, msg):
    print(f"\n[{n}] {msg}")


def main():
    print("=" * 64)
    print("iAuto Phase 1 Diagnostic v0.1.0")
    print("=" * 64)

    # 1. Config
    _step(1, "Loading config")
    try:
        client, creds = iauto_api.IAutoClient.from_config(HERE)
    except FileNotFoundError as e:
        print(f"  FAIL: missing config file: {e}")
        return 1
    with open(os.path.join(HERE, "config", "iauto_templates.json"), encoding="utf-8") as f:
        buttons = json.load(f)["buttons"]
    button = buttons["seller_lead_initial"]
    print(f"  base_url   = {client.base_url}")
    print(f"  mid        = {client.mid}")
    print(f"  login user = {creds.get('uin')!r}  (password {'set' if creds.get('passwd') else 'MISSING'})")
    print(f"  button     = {button['label']!r}")

    # 2. Status (no auth)
    _step(2, "GET /machine_status (no auth)")
    try:
        status = client.machine_status()
        print(f"  {json.dumps(status, ensure_ascii=False)}")
    except Exception as e:
        print(f"  FAIL: cannot reach the machine: {e}")
        print("  Check: machine powered on? same LAN? base_url IP correct?")
        return 1

    # 3. Login
    _step(3, "GET /login")
    try:
        client.login(creds["uin"], creds["passwd"])
        print("  login OK  ({\"error\":0})")
    except iauto_api.IAutoError as e:
        print(f"  FAIL: {e}")
        print("  If this fails, log in manually in the iAuto software once, then retry.")
        return 1
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1

    # 4. Merge the letter template with the sample lead
    _step(4, "Merge letter template with SAMPLE lead")
    letter = button["letter"]
    tmpl_path = os.path.join(HERE, letter["path"])
    merged_bytes, report = iauto_template.merge_to_bytes(
        tmpl_path, letter["fields"], SAMPLE_LEAD)
    for a in report["applied"]:
        print(f"  {a['cell']:>4}: {a['old']!r}  ->  {a['new']!r}")
    if report["missing"]:
        print(f"  WARNING: field-map cells not found in template: {report['missing']}")
    preview = os.path.join(HERE, "_iauto_diagnostic_preview.json")
    with open(preview, "wb") as f:
        f.write(merged_bytes)
    print(f"  merged template written to: {preview}")
    print(f"  ({len(merged_bytes):,} bytes) - open it to inspect before sending.")

    # 5. Confirm
    _step(5, "Confirm send")
    print("  This will POST the letter to the machine's write queue.")
    print("  It will begin writing on real paper. Type SEND to proceed, anything else to abort.")
    try:
        answer = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().upper() != "SEND":
        print("  Aborted. No send. (The merge above still proves the template path.)")
        return 0

    # 6. Send
    _step(6, "POST /write_template")
    try:
        result = client.write_template(merged_bytes, filename="diagnostic_letter.json")
        print(f"  response: {json.dumps(result, ensure_ascii=False)}")
        code = result.get("error")
        if code == 0:
            print("  SUCCESS - the machine accepted the letter.")
        else:
            print(f"  Machine returned error {code}: {result.get('error_meaning')}")
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1

    print("\nDiagnostic complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
