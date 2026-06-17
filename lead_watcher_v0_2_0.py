"""
Lead Watcher  v0.2.0
====================
The unattended local piece of the email-intake pipeline. Reads new lead emails
from Gmail over IMAP (using a Gmail app password, so no Claude/MCP needed),
parses each with the rule-based multi-source parser, enriches + ingests them via
the proven scraper path, and records which messages it has handled so it never
double-processes. Built to run on a schedule (Windows Task Scheduler) on Aubie's
machine, where it can reach propintel.db and the assessor sites.

Flow:  IMAP search -> for each new message: parse -> collect -> enrich_and_ingest
       -> mark message-id processed (local state file, no mailbox mutation).

Config: config/imap.json (host, user, app_password, mailbox, gmail_search).
State:  lead_watcher_state.json (set of processed Message-IDs).

Run:
    python lead_watcher_v0_2_0.py --dry-run                  # parse + print, no ingest
    python lead_watcher_v0_2_0.py --dry-run --since 2026/01/23  # historical preview
    python lead_watcher_v0_2_0.py                            # live: enrich + ingest + mark
    python lead_watcher_v0_2_0.py --since 2026/01/23         # live historical backfill

v0.2.0: SELLER-ONLY search (CMA / HouseValues / home value - buyers scrubbed);
--since <YYYY/MM/DD> historical backfill (swaps the rolling newer_than window for
after:<date>); X-GM-RAW search sent as an IMAP literal so quoted phrases no longer
cause a 'Could not parse command' error; address-less seller leads (Zurple 'asked
for a CMA - no matching address') are captured as NO ADDRESS contacts for
follow-up (via intake.ingest_addressless) instead of being dropped.

Exit codes: 0 ok (even if 0 leads). Non-zero only on a hard failure (bad login).
"""

import argparse
import email
import imaplib
import json
import os
import re
import sys
from email.header import decode_header, make_header

import lead_email_parse_v0_2_0 as parser
import lead_intake_v0_1_0 as intake

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config", "imap.json")
STATE = os.path.join(HERE, "lead_watcher_state.json")


def _load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                return set(json.load(f).get("processed_ids", []))
        except Exception:
            return set()
    return set()


def _save_state(ids):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"processed_ids": sorted(ids)}, f, indent=1)


def _decode(s):
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def _bodies(msg):
    """Return (plaintext, html) from an email.message.Message."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if ctype == "text/plain":
                plain += text
            elif ctype == "text/html":
                html += text
    else:
        try:
            text = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", "replace")
        except Exception:
            text = msg.get_payload() or ""
        if msg.get_content_type() == "text/html":
            html = text
        else:
            plain = text
    return plain, html


def fetch_lead_messages(cfg, since=None):
    """Connect and return a list of (message_id, subject, sender, plaintext, html).
    `since` ('YYYY/MM/DD') switches the rolling 'newer_than:Nd' window to a fixed
    'after:<date>' for a historical backfill."""
    imap = imaplib.IMAP4_SSL(cfg["host"], cfg.get("port", 993))
    imap.login(cfg["user"], cfg["app_password"])
    imap.select(cfg.get("mailbox", "INBOX"))
    query = cfg["gmail_search"]
    if since:
        query = re.sub(r"\bnewer_than:\S+\s*", "", query).strip()
        query = f"{query} after:{since}".strip()
    # Gmail raw search via X-GM-RAW. The query is sent as an IMAP literal so the
    # quoted phrases inside it (e.g. "Lead Alert") don't break command parsing.
    imap.literal = query.encode("utf-8")
    typ, data = imap.uid("SEARCH", "X-GM-RAW")
    out = []
    if typ == "OK" and data and data[0]:
        for uid in data[0].split():
            typ, msgdata = imap.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msgdata or not msgdata[0]:
                continue
            msg = email.message_from_bytes(msgdata[0][1])
            mid = _decode(msg.get("Message-ID", "")) or f"uid:{uid.decode()}"
            subject = _decode(msg.get("Subject", ""))
            sender = _decode(msg.get("From", ""))
            plain, html = _bodies(msg)
            out.append((mid, subject, sender, plain, html))
    imap.logout()
    return out


def run(dry_run=False, since=None, verbose=True):
    cfg = _load_config()
    if not cfg.get("app_password"):
        print("ERROR: no app_password in config/imap.json. Create a Gmail app "
              "password for", cfg.get("user"), "and add it.")
        return 2
    try:
        messages = fetch_lead_messages(cfg, since=since)
    except imaplib.IMAP4.error as e:
        print(f"ERROR: IMAP login/search failed: {e}")
        print("Check the app password, that IMAP is enabled, and the username.")
        return 2

    processed = _load_state()
    leads, new_ids, skipped = [], [], 0
    for mid, subject, sender, plain, html in messages:
        if mid in processed:
            skipped += 1
            continue
        lead = parser.parse_lead_email(subject, plain, html, sender)
        lead["_message_id"] = mid
        lead["_subject"] = subject
        leads.append(lead)
        new_ids.append(mid)

    print(f"Watcher [{'DRY RUN' if dry_run else 'LIVE'}]: {len(messages)} matched, "
          f"{skipped} already processed, {len(leads)} new.")
    for l in leads:
        flag = "" if l["has_address"] else "  (no address - capture as seller contact)"
        print(f"  [{l['source']}] {l['name'] or '?'} <{l['email'] or '-'}> "
              f"{l['property_address'] or ''}{flag}")

    if dry_run or not leads:
        print("Dry run / nothing new: no ingest, state unchanged." if dry_run
              else "Nothing new to ingest.")
        return 0

    # The seller-only search targets Zurple, whose listed 'address' is usually a
    # browsed listing, not the seller's home. So capture EVERY matched lead as a
    # contact (any address is noted UNVERIFIED, not attached) rather than enriching
    # the wrong property. A future reliable-address source would instead route the
    # has_address ones through intake.enrich_and_ingest.
    captured = intake.ingest_addressless(leads, verbose=verbose)
    processed.update(new_ids)
    _save_state(processed)
    print(f"\nCaptured {captured} seller lead(s) as contacts (address-less or "
          f"unverified-address); marked {len(new_ids)} message(s) processed.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Watch Gmail for new leads and ingest them.")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and print only; no enrichment, ingest, or state change")
    ap.add_argument("--since", help="historical backfill: only mail after this date "
                    "(YYYY/MM/DD), replacing the rolling newer_than window")
    args = ap.parse_args()
    since = args.since.replace("-", "/") if args.since else None
    return run(dry_run=args.dry_run, since=since)


if __name__ == "__main__":
    sys.exit(main())
