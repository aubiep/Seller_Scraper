"""
PropIntel Dashboard  v0.3.4
===========================
A local web app over propintel.db. Runs entirely on your machine; the only
outbound actions are ones you trigger: Homebot enrollment and iAuto letter sends.
This is the unified-app home: see leads, work the review queue, pull mailing
lists, queue and send iAuto handwritten notes, and enroll seller leads on Homebot.

Run:
    python propintel_app_v0_3_4.py
Then open http://127.0.0.1:5000 (this PC) or http://<this-PC-LAN-IP>:5000
(a phone/tablet on the same WiFi - the startup prints the exact URL).

Screens:
    /              Dashboard - daily command center: new & unprocessed leads,
                   follow-up due, priority worklist, review queue, status tiles
    /priority      Priority worklist - leads ranked by listing likelihood + why
    /leads         Leads + contacts (merged) - one row per person+property, repeat
                   badge, filters, Add-contact form, per-row queue + enroll
    /property/<id> Full lead detail - assessor record, photos, every submission
    /letters       iAuto letter queue - queue/re-template a note, send, enroll
    /letters/bulk  Bulk mail - filter a lead list, then queue letters in one pass
    /homebot       Homebot - enroll verified seller leads on the Market Digest
    /contacts      -> redirects to /leads (merged in v0.3.0)

New in v0.3.4 (supersedes v0.3.3):
    - Row thumbnails fall back to the county assessor photo when Google has no
      Street View image for the address (rural roads). street_thumb() now takes
      the assessor file too; the daily home, priority worklist, and /leads
      queries carry p.assessor_photo_file. Pairs with streetview_backfill_v0_1_0,
      which re-fetched real Street View photos for the 43 older rows that had none
      (Google metadata pre-check skips the gray "no imagery" placeholder).

New in v0.3.3 (supersedes v0.3.2):
    - "Re-run assessor lookup" button on every lead row of the property detail
      page (POST /lead/<cid>/<pid>/reenrich -> reenrich_v0_1_0.reenrich). On a
      match it upgrades the property in place (real parcel + owner + value) and
      flips the verdict, preserving the original lead date - the manual condo
      re-enrichment, now one click. On a failure it stores WHAT the assessor
      returned (owner found that didn't match, candidate condo unit owners, or
      "no parcel found") in properties.last_lookup_* (schema v4).
    - "Last assessor lookup" panel on the property detail page shows that stored
      outcome (status + detail + timestamp), so a failed re-run is visible and
      explained instead of silent. The /leads verdict filter (UNENRICHED /
      MISMATCH / REVIEW) remains the all-failures list.

New in v0.3.2 (supersedes v0.3.1):
    - Serves on the local network (binds 0.0.0.0), so a phone/tablet on the same
      WiFi can open it at http://<this-PC-LAN-IP>:5000. The startup prints the
      exact phone URL. No auth - home WiFi only. (First run may pop a Windows
      Firewall prompt; allow Python on Private networks.)

New in v0.3.1 (supersedes v0.3.0):
    - Edit-contact form: an "edit" link on every contact (the /leads list and the
      property detail page) opens /contact/<id>/edit to fix the name's casing or
      add/correct an email or phone. Saved verbatim (no auto-casing on manual edit).

New in v0.3.0 (supersedes v0.2.8):
    - Dashboard rebuilt into a start-of-day command center: status tiles, then
      New & unprocessed leads (hero), Follow-up due (initial letter 2+ weeks old),
      the Priority worklist, and the ownership review queue - each with inline
      queue/enroll actions. New DB helpers new_unprocessed_leads / followup_due.
    - Contacts + Leads merged into one repeat-aware /leads page: one row per
      person+property, a gold "Nx" repeat badge (pdb.submission_counts) flagging
      multiple submissions, name/city/zip/verdict/lead-type filters, the
      Add-contact form, and per-row Queue-letter + Enroll-in-Homebot. /contacts
      now redirects here; the Contacts nav item is gone.
    - Inline Homebot cell shows the blocking reason (e.g. "needs an email") instead
      of a bare dash when a lead is ineligible.

New in v0.2.8 (supersedes v0.2.7):
    - Letters queue: change a letter's template right in the queue (dropdown per
      queued row, POST /iauto/queue/template). A letter queued from any page (which
      defaults to seller_lead_initial) is no longer locked - re-point it before
      sending. Sent rows show the template read-only.
    - Inline "Enroll in Homebot" button on the Letters queue rows and the
      /property/<id> lead rows (POST /homebot/enroll_one), with the ENROLLED /
      IN HOMEBOT status pill when already done. The dedicated /homebot hub stays.

New in v0.2.7 (supersedes v0.2.6):
    - Radius filter on /letters/bulk: "within N miles of <address>". The center
      is geocoded on the fly (geocode_v0_1_0), distance is great-circle per lead,
      results carry a Distance column and can arrange by it. Leads missing
      coordinates are skipped (with a note) and can be geocoded on demand via a
      button that runs geocode_v0_1_0.backfill (covers new leads with no scraper
      change). Needs the schema-v3 lat/long columns (auto-migrated).

New in v0.2.6 (supersedes v0.2.5):
    - Bulk letter queue (/letters/bulk): build a mailing list by city, county,
      zip, neighborhood, lead type, verdict, or received date; arrange it (incl.
      by listing-likelihood score); optionally cap to the top N; then queue
      letters for every checked lead in one pass. Filters live in a registry
      (BULK_FILTERS) so adding one (e.g. geocoded radius) is a one-entry change.
    - Letters queue now shows the friendly template label (not the raw key) and
      a Sent timestamp column.

New in v0.2.5 (supersedes v0.2.4):
    - Priority worklist (/priority): leads ranked 0-100 by listing likelihood
      (lead_priority), each with its Street View thumb, the "why" factors, and a
      one-click Queue iAuto letter. This is the morning "work these first" screen.
    - DB auto-backup on launch + before every ingest (propintel_backup).

v0.2.4:
    - Street View thumbnails on the Leads list (Google Maps photo, not assessor).

v0.2.3:
    - Lead detail page (/property/<id>): the full assessor record on one screen -
      owner of record, all property facts and values, sale history, the ownership
      reasoning, and BOTH photos (assessor + Street View) shown inline, plus a
      one-click "Queue iAuto letter" per contact. Names on Leads and Contacts are
      now clickable into it. Photos served via /photo/<id>/<which>.

v0.2.2:
    - /contacts "Add contact" form for walk-ups, clients, open-house contacts.
v0.2.1:
    - /letters working queue: queue a letter, Send letter / Send envelope per row.
"""

import os
from flask import Flask, request, render_template_string, redirect, url_for, send_file, abort

import propintel_db_v0_1_0 as pdb
import homebot_push_v0_1_0 as hbpush
import iauto_send_v0_1_0 as iautosend
import propintel_backup_v0_1_0 as backup
import lead_priority_v0_1_0 as priority
import geocode_v0_1_0 as geocode
import reenrich_v0_1_0 as reenrich

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), pdb.DEFAULT_DB_FILENAME)


def db():
    conn = pdb.connect(DB_PATH)
    pdb.init_db(conn)
    return conn


BASE = """
<!doctype html><html><head><meta charset="utf-8"><title>PropIntel - {{ title }}</title>
<style>
  :root{--bg:#0f1216;--panel:#171c22;--panel2:#1d242c;--line:#262e38;--txt:#e6eaef;
        --mut:#8a97a6;--accent:#3b82f6;--good:#1f9d55;--warn:#b78103;--bad:#c0392b;}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);
    font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial}
  header{display:flex;align-items:center;gap:18px;padding:12px 20px;background:var(--panel);
    border-bottom:1px solid var(--line)}
  header .brand{font-weight:700;letter-spacing:.3px}
  nav a{color:var(--mut);text-decoration:none;margin-right:16px;padding:6px 4px;font-weight:600}
  nav a.active,nav a:hover{color:var(--txt);border-bottom:2px solid var(--accent)}
  .wrap{padding:20px;max-width:1200px;margin:0 auto}
  .cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 18px;min-width:130px}
  .card .n{font-size:26px;font-weight:700} .card .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.5px;background:var(--panel2)}
  tr:last-child td{border-bottom:none}
  .pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:12px;font-weight:700}
  .CONFIRMED{background:rgba(31,157,85,.18);color:#56d68a}
  .LIKELY{background:rgba(59,130,246,.18);color:#79b0ff}
  .REVIEW{background:rgba(183,129,3,.20);color:#e8b54b}
  .MISMATCH{background:rgba(192,57,43,.18);color:#f0857a}
  .NO{background:rgba(138,151,166,.18);color:var(--mut)}
  .mut{color:var(--mut)} .reason{color:var(--mut);font-size:13px}
  form.filters{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}
  input,select{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
    padding:8px 10px;border-radius:8px;font:inherit}
  button{background:var(--accent);border:none;color:#fff;padding:8px 16px;border-radius:8px;font-weight:600;cursor:pointer}
  button.ghost{background:transparent;border:1px solid var(--line);color:var(--txt)}
  button.danger{background:var(--bad)} button.sm{padding:5px 10px;font-size:13px}
  h2{margin:24px 0 10px;font-size:16px} .sub{color:var(--mut);margin-top:-4px}
  .empty{padding:30px;text-align:center;color:var(--mut)}
  .banner{background:rgba(59,130,246,.12);border:1px solid var(--accent);border-radius:8px;padding:10px 14px;margin-bottom:16px}
  .actions{display:flex;gap:10px;align-items:center;margin:14px 0;flex-wrap:wrap}
  form.bulkfilters{display:flex;gap:12px;margin:12px 0 6px;flex-wrap:wrap;align-items:flex-end}
  .flab{display:flex;flex-direction:column;gap:3px;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut)}
  .rowform{display:inline;margin:0}
  code{background:var(--panel2);padding:1px 6px;border-radius:5px}
  .note{background:var(--panel2);border-left:3px solid var(--warn);padding:8px 12px;border-radius:6px;margin:10px 0;color:var(--mut)}
  a.rowlink{color:var(--txt);text-decoration:none;font-weight:600} a.rowlink:hover{color:var(--accent)}
  .back{color:var(--mut);text-decoration:none;font-size:13px} .back:hover{color:var(--txt)}
  .detail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px;margin:6px 0 4px}
  .kv{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
  .kv .k{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .kv .v{font-size:15px;font-weight:600;margin-top:3px;word-break:break-word}
  .kv.hi .v{font-size:22px;color:#56d68a}
  .photos{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0}
  .photos figure{margin:0} .photos figcaption{color:var(--mut);font-size:12px;margin-top:5px}
  .photos img{height:240px;border-radius:10px;border:1px solid var(--line);display:block;object-fit:cover}
  .thumb{height:44px;width:64px;object-fit:cover;border-radius:6px;border:1px solid var(--line);display:block}
  .thumb.ph{background:var(--panel2)}
  .score{display:inline-block;min-width:38px;text-align:center;padding:4px 8px;border-radius:8px;font-weight:700;font-size:15px}
  .s-hot{background:rgba(31,157,85,.20);color:#56d68a}
  .s-warm{background:rgba(59,130,246,.18);color:#79b0ff}
  .s-cool{background:rgba(183,129,3,.20);color:#e8b54b}
  .s-cold{background:rgba(138,151,166,.16);color:var(--mut)}
  .facts{color:var(--mut);font-size:12.5px}
  .rpt{display:inline-block;background:rgba(183,129,3,.22);color:#e8b54b;font-weight:700;
    font-size:12px;padding:2px 8px;border-radius:20px;white-space:nowrap}
  .home-sec{margin:18px 0 6px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
  .home-sec h2{margin:0} .home-sec .seemore{color:var(--accent);text-decoration:none;font-size:13px}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:120px}
  .tile .n{font-size:22px;font-weight:700} .tile .l{color:var(--mut);font-size:12px}
  .tile a{color:inherit;text-decoration:none}
</style></head><body>
<header>
  <span class="brand">PropIntel</span>
  <nav>
    <a href="/" class="{{ 'active' if title=='Dashboard' else '' }}">Dashboard</a>
    <a href="/priority" class="{{ 'active' if title=='Priority' else '' }}">Priority</a>
    <a href="/leads" class="{{ 'active' if title=='Leads' else '' }}">Leads</a>
    <a href="/letters" class="{{ 'active' if title=='Letters' else '' }}">Letters</a>
    <a href="/letters/bulk" class="{{ 'active' if title=='Bulk' else '' }}">Bulk mail</a>
    <a href="/homebot" class="{{ 'active' if title=='Homebot' else '' }}">Homebot</a>
  </nav>
</header>
<div class="wrap">{{ body|safe }}</div>
</body></html>
"""


def page(title, body):
    return render_template_string(BASE, title=title, body=body)


def pill(status):
    cls = status if status in ("CONFIRMED", "LIKELY", "REVIEW", "MISMATCH") else "NO"
    return f'<span class="pill {cls}">{status}</span>'


def esc(s):
    return (str(s) if s is not None else "").replace("<", "&lt;").replace(">", "&gt;")


def _v(val):
    """Display value: blank/None -> em dash."""
    s = str(val).strip() if val is not None else ""
    return esc(s) if s else "&mdash;"


def kvc(label, val, hi=False):
    cls = "kv hi" if hi else "kv"
    return f"<div class='{cls}'><div class='k'>{esc(label)}</div><div class='v'>{_v(val)}</div></div>"


def street_thumb(pid, photo_file, assessor_file=None):
    """Row thumbnail. Prefers the Google Street View photo; falls back to the
    county assessor photo when no Street View image exists for the row (rural
    addresses Google doesn't cover). Blank placeholder when neither exists."""
    if photo_file and os.path.exists(photo_file):
        which = "street"
    elif assessor_file and os.path.exists(assessor_file):
        which = "assessor"
    else:
        return "<span class='thumb ph'></span>"
    return (f"<a href='/property/{pid}'>"
            f"<img class='thumb' src='/photo/{pid}/{which}' alt='' loading='lazy'></a>")


def repeat_badge(sub_counts, contact_id):
    """An 'Nx' badge when a person has submitted as a lead more than once - the
    motivation signal. sub_counts comes from pdb.submission_counts()."""
    info = sub_counts.get(contact_id)
    if not info or info["n"] <= 1:
        return ""
    span = f" ({info['first']} → {info['last']})" if (info["first"] or info["last"]) else ""
    return f" <span class='rpt' title='{esc(str(info['n']) + ' submissions' + span)}'>{info['n']}x</span>"


def queue_letter_btn(cid, pid, name, label="Queue letter"):
    """One-click 'queue an iAuto letter' button (defaults to seller_lead_initial;
    the template is changeable later in the Letters queue)."""
    return (
        "<form class='rowform' method='post' action='/iauto/queue' "
        f"onsubmit=\"return confirm('Queue an iAuto letter for {esc(name)}?');\">"
        f"<input type='hidden' name='lead' value='{cid}:{pid}'>"
        "<input type='hidden' name='template' value='seller_lead_initial'>"
        f"<button class='sm'>{esc(label)}</button></form>")


def _sec(title, more_href=None, more_label=None):
    """A home-page section header, optionally with a 'see all ->' link."""
    more = (f"<a class='seemore' href='{more_href}'>{more_label} &rarr;</a>"
            if more_href else "")
    return f"<div class='home-sec'><h2>{title}</h2>{more}</div>"


@app.route("/")
def dashboard():
    """Start-of-day command center: what just came in, what's due for follow-up,
    today's priority worklist, and a compact status row."""
    conn = db()
    s = pdb.stats_summary(conn)
    subs = pdb.submission_counts(conn)
    hb_status = _homebot_status_map(conn)
    new_leads = pdb.new_unprocessed_leads(conn, limit=25)
    fu = pdb.followup_due(conn, days=14)
    ranked = priority.ranked_leads(conn)[:8]
    review = pdb.review_queue(conn, limit=6)

    n_new = conn.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM lead_events le WHERE NOT EXISTS "
        "(SELECT 1 FROM outreach o WHERE o.contact_id=le.contact_id "
        "AND o.property_id=le.property_id) GROUP BY le.contact_id, le.property_id)"
    ).fetchone()[0]
    n_queued = conn.execute("SELECT COUNT(*) FROM outreach WHERE channel='iauto' AND status='queued'").fetchone()[0]
    n_enrolled = conn.execute("SELECT COUNT(*) FROM outreach WHERE channel='homebot' AND status='sent'").fetchone()[0]

    tiles = "".join(
        f"<div class='tile'><div class='n'>{v:,}</div><div class='l'>{lbl}</div></div>" if not href
        else f"<a class='tile' href='{href}'><div class='n'>{v:,}</div><div class='l'>{lbl}</div></a>"
        for lbl, v, href in [
            ("New &amp; unprocessed", n_new, None),
            ("Follow-up due", len(fu), None),
            ("Needs review", s["needs_review"], "/leads?verdict=MISMATCH"),
            ("Letters queued", n_queued, "/letters"),
            ("In Homebot", n_enrolled, "/homebot"),
            ("Total leads", s["lead_events"], "/leads")])
    tiles = f"<div class='cards'>{tiles}</div>"

    # ① New & unprocessed (the hero) -----------------------------------------
    if new_leads:
        nl = ""
        for r in new_leads:
            name = f"{r['first_name']} {r['last_name']}".strip()
            pid = r["property_id"]
            nl += (
                f"<tr><td>{street_thumb(pid, r['photo_file'], r['assessor_photo_file'])}</td>"
                f"<td><a class='rowlink' href='/property/{pid}'>{esc(name)}</a>"
                f"{repeat_badge(subs, r['contact_id'])}"
                f"<div class='mut'>{esc(r['property_city'] or '')}</div></td>"
                f"<td>{pill(r['ownership_match'] or '—')}</td>"
                f"<td class='mut'>{esc((r['property_address'] or '')[:40])}</td>"
                f"<td class='mut'>{esc(r['lead_source'] or '')}<br>{esc(r['received_date'] or '')}</td>"
                f"<td>{queue_letter_btn(r['contact_id'], pid, name)}</td>"
                f"<td>{homebot_action_cell(conn, r['contact_id'], pid, hb_status, next_pid=pid)}</td></tr>")
        new_tbl = ("<table><tr><th></th><th>Lead</th><th>Verdict</th><th>Property</th>"
                   f"<th>Source / received</th><th>Letter</th><th>Homebot</th></tr>{nl}</table>")
    else:
        new_tbl = "<div class='empty'>All caught up - every lead has been actioned.</div>"

    # ② Follow-up due ---------------------------------------------------------
    if fu:
        fr = ""
        for r in fu:
            name = f"{r['first_name']} {r['last_name']}".strip()
            fr += (
                f"<tr><td><a class='rowlink' href='/property/{r['property_id']}'>{esc(name)}</a></td>"
                f"<td class='mut'>{esc((r['property_address'] or '')[:44])}</td>"
                f"<td class='mut'>letter sent {esc((r['sent_at'] or '')[:10])}</td>"
                f"<td>{queue_letter_btn(r['contact_id'], r['property_id'], name, label='Queue follow-up')}</td></tr>")
        fu_tbl = (f"<table><tr><th>Lead</th><th>Property</th><th>When</th><th>Action</th></tr>{fr}</table>")
    else:
        fu_tbl = "<div class='empty'>Nothing due for follow-up yet.</div>"

    # ③ Priority worklist (top of the ranked list) ---------------------------
    if ranked:
        pr = ""
        for item in ranked:
            r = item["row"]
            name = f"{r['first_name']} {r['last_name']}".strip()
            why = ", ".join(lbl for lbl, _ in item["factors"]) or "—"
            pr += (
                f"<tr><td><span class='score {_score_class(item['score'])}'>{item['score']}</span></td>"
                f"<td>{street_thumb(r['property_id'], r['photo_file'], r['assessor_photo_file'])}</td>"
                f"<td><a class='rowlink' href='/property/{r['property_id']}'>{esc(name)}</a>"
                f"<div class='mut'>{esc(r['property_city'] or '')}</div></td>"
                f"<td>{pill(r['ownership_match'] or '—')}</td>"
                f"<td class='facts'>{esc(why)}</td>"
                f"<td>{queue_letter_btn(r['contact_id'], r['property_id'], name)}</td></tr>")
        pr_tbl = ("<table><tr><th>Score</th><th></th><th>Lead</th><th>Verdict</th>"
                  f"<th>Why</th><th>Letter</th></tr>{pr}</table>")
    else:
        pr_tbl = "<div class='empty'>No leads to rank yet.</div>"

    # ④ Review queue (compact) -----------------------------------------------
    if review:
        rv = "".join(
            f"<tr><td>{esc(r['first_name'])} {esc(r['last_name'])}</td>"
            f"<td>{pill(r['ownership_match'])} <span class='mut'>{esc(r['match_confidence'])}</span></td>"
            f"<td class='mut'>{esc((r['property_address'] or '')[:44])}</td>"
            f"<td class='reason'>{esc(r['match_reason'] or '')}</td></tr>" for r in review)
        rv_tbl = (f"<table><tr><th>Lead</th><th>Verdict</th><th>Property</th><th>Why</th></tr>{rv}</table>")
    else:
        rv_tbl = "<div class='empty'>Nothing needs review. Every lead is a confident match.</div>"

    body = (
        "<h2 style='margin-top:4px'>Today</h2>"
        "<div class='sub'>Your start-of-day view. Work top to bottom.</div>"
        f"{tiles}"
        + _sec("New &amp; unprocessed leads")
        + "<div class='sub'>Came in, nothing done yet. Queue a letter or enroll, and they drop off this list.</div>"
        + new_tbl
        + _sec("Follow-up due")
        + "<div class='sub'>Initial letter went out 2+ weeks ago with no follow-up since.</div>"
        + fu_tbl
        + _sec("Priority worklist", "/priority", "see all")
        + "<div class='sub'>Top leads by listing likelihood.</div>"
        + pr_tbl
        + _sec("Ownership review", "/leads?verdict=MISMATCH", "see all")
        + "<div class='sub'>Leads where the owner of record needs a human glance.</div>"
        + rv_tbl)
    conn.close()
    return page("Dashboard", body)


def _score_class(s):
    return "s-hot" if s >= 85 else "s-warm" if s >= 65 else "s-cool" if s >= 40 else "s-cold"


@app.route("/priority")
def priority_view():
    conn = db()
    msg = request.args.get("msg", "")
    ranked = priority.ranked_leads(conn)
    rows = ""
    for item in ranked:
        r = item["row"]
        pid = r["property_id"]
        name = f"{r['first_name']} {r['last_name']}".strip()
        why = ", ".join(f"{lbl}" for lbl, _ in item["factors"]) or "—"
        queue_btn = (
            "<form class='rowform' method='post' action='/iauto/queue' "
            f"onsubmit=\"return confirm('Queue an iAuto letter for {esc(name)}?');\">"
            f"<input type='hidden' name='lead' value='{r['contact_id']}:{pid}'>"
            "<input type='hidden' name='template' value='seller_lead_initial'>"
            "<button class='sm'>Queue letter</button></form>")
        rows += (
            f"<tr><td><span class='score {_score_class(item['score'])}'>{item['score']}</span></td>"
            f"<td>{street_thumb(pid, r['photo_file'], r['assessor_photo_file'])}</td>"
            f"<td><a class='rowlink' href='/property/{pid}'>{esc(name)}</a>"
            f"<div class='mut'>{esc(r['property_city'] or '')}</div></td>"
            f"<td>{pill(r['ownership_match'])}</td>"
            f"<td class='facts'>{esc(why)}</td>"
            f"<td>{queue_btn}</td></tr>")
    banner = f"<div class='banner'>{esc(msg)}</div>" if msg else ""
    body = (f"<h2>Priority worklist</h2>"
            f"<div class='sub'>Leads ranked by listing likelihood. Work top-down. "
            f"Score reflects confirmed ownership, owner-occupancy, tenure, repeat "
            f"interest, and equity.</div>{banner}"
            f"<table><tr><th>Score</th><th></th><th>Lead</th><th>Verdict</th>"
            f"<th>Why</th><th>Action</th></tr>{rows}</table>")
    conn.close()
    return page("Priority", body)


_CONTACT_TYPES = [("seller_lead", "Seller lead"), ("client", "Client"),
                  ("open_house", "Open house"), ("buyer", "Buyer"),
                  ("prospect", "Prospect"), ("other", "Other")]


@app.route("/contacts")
def contacts():
    # Contacts merged into the unified Leads page (v0.3.0). Keep this path as a
    # redirect so old links/bookmarks still work.
    return redirect(url_for("leads", **request.args.to_dict()))


@app.route("/contacts/add", methods=["POST"])
def contacts_add():
    conn = db()
    f = request.form
    first = f.get("first_name", "").strip()
    last = f.get("last_name", "").strip()
    email = f.get("email", "").strip()
    phone = f.get("phone", "").strip()
    street = f.get("street", "").strip()
    city = f.get("city", "").strip()
    state = f.get("state", "").strip() or "WA"
    zipc = f.get("zip", "").strip()
    ctype = f.get("contact_type", "").strip() or "other"

    if not (first or last):
        conn.close()
        return redirect(url_for("leads", msg="Could not add: a name is required."))
    if not (street and city):
        conn.close()
        return redirect(url_for("leads",
                                msg="Could not add: a street and city are required to make a contact mailable."))

    when = pdb._now()
    cid = pdb.find_or_create_contact(conn, first, last, email, phone, ctype, when)
    addr = f"{street}, {city}, {state} {zipc}".strip()
    prop_fields = {"county": "", "parcel_number": "", "property_address": addr,
                   "property_street": street, "property_city": city,
                   "property_state": state, "property_zip": zipc}
    pid = pdb.upsert_property(conn, prop_fields, when, when)
    lead_type = "Seller" if ctype == "seller_lead" else ctype.replace("_", " ").title()
    pdb.add_lead_event(conn, cid, pid, {
        "lead_type": lead_type, "lead_source": "Manual entry",
        "ownership_match": "MANUAL", "needs_review": 0, "match_confidence": 0,
        "match_relationship": "", "match_reason": "Entered manually; not verified against assessor.",
        "received_date": when[:10], "source_row": None}, when)
    conn.commit()
    conn.close()
    return redirect(url_for("leads", msg=f"Added {first} {last} ({ctype.replace('_', ' ')})."))


@app.route("/contact/<int:cid>/edit", methods=["GET", "POST"])
def contact_edit(cid):
    """Edit a contact's name / email / phone (fix casing, add CRM-only email or
    phone, correct typos). Values are stored verbatim - no auto-casing here, so a
    deliberate spelling like 'DeAngelo' is respected."""
    conn = db()
    c = conn.execute("SELECT id, first_name, last_name, email, phone, contact_type "
                     "FROM contacts WHERE id=?", (cid,)).fetchone()
    if not c:
        conn.close()
        abort(404)
    next_pid = request.values.get("next_pid", "")

    if request.method == "POST":
        f = request.form
        conn.execute(
            "UPDATE contacts SET first_name=?, last_name=?, email=?, phone=?, "
            "contact_type=?, updated_at=? WHERE id=?",
            (f.get("first_name", "").strip(), f.get("last_name", "").strip(),
             f.get("email", "").strip(), f.get("phone", "").strip(),
             f.get("contact_type", "").strip() or (c["contact_type"] or ""),
             pdb._now(), cid))
        conn.commit()
        conn.close()
        name = f"{f.get('first_name','').strip()} {f.get('last_name','').strip()}".strip()
        if next_pid:
            try:
                return redirect(url_for("property_detail", pid=int(next_pid),
                                        msg=f"Updated {name}."))
            except (ValueError, TypeError):
                pass
        return redirect(url_for("leads", msg=f"Updated {name}."))

    type_opts = "".join(
        f"<option value='{v}'{' selected' if v == (c['contact_type'] or '') else ''}>{lbl}</option>"
        for v, lbl in _CONTACT_TYPES)
    back = (url_for("property_detail", pid=int(next_pid)) if next_pid.isdigit()
            else url_for("leads"))
    body = (
        f"<a class='back' href='{back}'>&larr; back</a>"
        f"<h2 style='margin-top:8px'>Edit contact</h2>"
        "<div class='sub'>Fix the name's capitalization, add an email/phone you pulled "
        "from the CRM, or correct a typo. Saved exactly as typed.</div>"
        "<form class='filters' method='post' style='flex-direction:column;align-items:stretch;max-width:420px'>"
        f"<input name='first_name' placeholder='first name' value='{esc(c['first_name'] or '')}'>"
        f"<input name='last_name' placeholder='last name' value='{esc(c['last_name'] or '')}'>"
        f"<input name='email' placeholder='email' value='{esc(c['email'] or '')}'>"
        f"<input name='phone' placeholder='phone' value='{esc(c['phone'] or '')}'>"
        f"<select name='contact_type'>{type_opts}</select>"
        f"<input type='hidden' name='next_pid' value='{esc(next_pid)}'>"
        "<button>Save changes</button></form>")
    conn.close()
    return page("Leads", body)


@app.route("/leads")
def leads():
    """Unified people + leads view (replaces the old Contacts and Leads tabs).
    One row per person+property, repeat-aware, filterable, with inline actions."""
    conn = db()
    msg = request.args.get("msg", "")
    q = request.args.get("q", "").strip()
    city = request.args.get("city", "").strip()
    zipc = request.args.get("zip", "").strip()
    verdict = request.args.get("verdict", "").strip()
    ltype = request.args.get("lead_type", "").strip()

    rows = conn.execute(
        "SELECT le.contact_id, le.property_id AS pid, MAX(le.id) leid, "
        "c.first_name, c.last_name, c.email, c.phone, c.contact_type, "
        "le.lead_type, le.lead_source, le.ownership_match, le.match_confidence, "
        "le.received_date, p.photo_file, p.assessor_photo_file, p.property_city, p.property_zip, "
        "p.property_address "
        "FROM lead_events le "
        "JOIN contacts c   ON c.id = le.contact_id "
        "JOIN properties p ON p.id = le.property_id "
        "WHERE (?='' OR p.property_city LIKE ?) AND (?='' OR p.property_zip LIKE ?) "
        "AND (?='' OR c.first_name LIKE ? OR c.last_name LIKE ?) "
        "AND (?='' OR le.ownership_match=?) AND (?='' OR le.lead_type=?) "
        "GROUP BY le.contact_id, le.property_id "
        "ORDER BY le.ownership_match='MISMATCH' DESC, c.last_name, c.first_name",
        (city, f"%{city}%", zipc, f"{zipc}%", q, f"%{q}%", f"%{q}%",
         verdict, verdict, ltype, ltype),
    ).fetchall()

    subs = pdb.submission_counts(conn)
    hb_status = _homebot_status_map(conn)
    body_rows = ""
    for r in rows:
        name = f"{r['first_name']} {r['last_name']}".strip()
        body_rows += (
            f"<tr><td>{street_thumb(r['pid'], r['photo_file'], r['assessor_photo_file'])}</td>"
            f"<td><a class='rowlink' href='/property/{r['pid']}'>{esc(name)}</a>"
            f"{repeat_badge(subs, r['contact_id'])} "
            f"<a class='back' href='/contact/{r['contact_id']}/edit?next_pid={r['pid']}'>edit</a>"
            f"<div class='mut'>{esc(r['contact_type'] or r['lead_type'] or '')}</div></td>"
            f"<td>{pill(r['ownership_match'] or '—')} <span class='mut'>{esc(r['match_confidence'])}</span></td>"
            f"<td class='mut'>{esc(r['email'] or '')}<br>{esc(r['phone'] or '')}</td>"
            f"<td>{esc(r['property_city'] or '')} {esc(r['property_zip'] or '')}"
            f"<div class='mut'>{esc((r['property_address'] or '')[:42])}</div></td>"
            f"<td class='mut'>{esc(r['lead_source'] or '')}<br>{esc(r['received_date'] or '')}</td>"
            f"<td>{queue_letter_btn(r['contact_id'], r['pid'], name)}</td>"
            f"<td>{homebot_action_cell(conn, r['contact_id'], r['pid'], hb_status, next_pid=r['pid'])}</td></tr>")
    if not body_rows:
        body_rows = "<tr><td colspan='8' class='empty'>No matches.</td></tr>"

    verdicts = [x["v"] for x in conn.execute(
        "SELECT DISTINCT ownership_match v FROM lead_events "
        "WHERE TRIM(COALESCE(ownership_match,''))!='' ORDER BY 1")]
    ltypes = [x["v"] for x in conn.execute(
        "SELECT DISTINCT lead_type v FROM lead_events "
        "WHERE TRIM(COALESCE(lead_type,''))!='' ORDER BY 1")]

    def sel(vals, cur, any_label):
        out = [f"<option value=''>{any_label}</option>"]
        for v in vals:
            out.append(f"<option value='{esc(v)}'{' selected' if v == cur else ''}>{esc(v)}</option>")
        return "".join(out)

    type_opts = "".join(f"<option value='{v}'>{lbl}</option>" for v, lbl in _CONTACT_TYPES)
    add_form = (
        "<h2>Add a contact</h2>"
        "<div class='sub'>For walk-ups, clients, and open-house contacts - anyone not "
        "from a CRM import. Added contacts are immediately mailable and auto-geocoded. "
        "(Manual entry is not verified against the assessor.)</div>"
        "<form class='filters' method='post' action='/contacts/add'>"
        "<input name='first_name' placeholder='first name'>"
        "<input name='last_name' placeholder='last name'>"
        "<input name='email' placeholder='email (optional)'>"
        "<input name='phone' placeholder='phone (optional)'>"
        "<input name='street' placeholder='street address'>"
        "<input name='city' placeholder='city'>"
        "<input name='state' placeholder='state' value='WA' style='width:60px'>"
        "<input name='zip' placeholder='zip' style='width:90px'>"
        f"<select name='contact_type'>{type_opts}</select>"
        "<button>Add contact</button></form>")

    filt = (
        "<form class='filters' method='get'>"
        f"<input name='q' placeholder='name' value='{esc(q)}'>"
        f"<input name='city' placeholder='city' value='{esc(city)}'>"
        f"<input name='zip' placeholder='zip' value='{esc(zipc)}'>"
        f"<select name='verdict'>{sel(verdicts, verdict, '(any verdict)')}</select>"
        f"<select name='lead_type'>{sel(ltypes, ltype, '(any type)')}</select>"
        f"<button>Filter</button>"
        f"<span class='mut' style='align-self:center'>{len(rows)} result(s)</span></form>")

    banner = f"<div class='banner'>{esc(msg)}</div>" if msg else ""
    body = (
        f"{banner}{add_form}"
        "<h2>Leads &amp; contacts</h2>"
        "<div class='sub'>Everyone who's come in - one row per person + property - with the "
        "ownership verdict, contact info, and a gold repeat badge when they've submitted "
        "more than once (a strong motivation signal). Click a name for the full record and "
        "every submission. Filter to pull a mailing list, then queue a letter or enroll "
        "in Homebot per row.</div>"
        f"{filt}"
        "<table><tr><th></th><th>Lead</th><th>Verdict</th><th>Contact</th><th>Property</th>"
        f"<th>Source / received</th><th>Letter</th><th>Homebot</th></tr>{body_rows}</table>")
    conn.close()
    return page("Leads", body)


# ── iAuto letter queue ───────────────────────────────────────────────────────

_IAUTO_PILL = {"queued": ("QUEUED", "REVIEW"), "sent": ("SENT", "CONFIRMED"),
               "failed": ("FAILED", "MISMATCH"), "draft": ("DRAFT", "NO")}


# ── Bulk letter queue: filter registry + query builder ───────────────────────
# Each entry is one filter control. To add a new filter (e.g. a geocoded radius
# once properties carry lat/long), append a dict here; the form renderer and the
# WHERE builder both read this list, so no other code changes.
BULK_FILTERS = [
    {"key": "city",         "label": "City",         "kind": "text",   "col": "p.property_city",     "op": "LIKE", "wrap": "%{}%"},
    {"key": "zip",          "label": "Zip",          "kind": "text",   "col": "p.property_zip",      "op": "LIKE", "wrap": "{}%"},
    {"key": "county",       "label": "County",       "kind": "select", "col": "p.county",            "op": "=",    "wrap": None},
    {"key": "neighborhood", "label": "Neighborhood", "kind": "text",   "col": "p.neighborhood_code", "op": "LIKE", "wrap": "%{}%"},
    {"key": "lead_type",    "label": "Lead type",    "kind": "select", "col": "le.lead_type",        "op": "=",    "wrap": None},
    {"key": "status",       "label": "Verdict",      "kind": "select", "col": "le.ownership_match",   "op": "=",    "wrap": None},
    {"key": "date_from",    "label": "Received from","kind": "date",   "col": "le.received_date",    "op": ">=",   "wrap": None},
    {"key": "date_to",      "label": "Received to",  "kind": "date",   "col": "le.received_date",    "op": "<=",   "wrap": None},
]

# arrange-by key -> (label, sort-descending?)
BULK_SORTS = {
    "priority":  ("Priority score", True),
    "distance":  ("Distance",       False),
    "date":      ("Date received",  True),
    "status":    ("Verdict",        False),
    "lead_type": ("Lead type",      False),
    "city":      ("City",           False),
    "county":    ("County",         False),
    "zip":       ("Zip",            False),
    "name":      ("Name",           False),
}

# Which select filters pull their options from which column.
_BULK_OPTION_COLS = {"county": ("properties", "county"),
                     "lead_type": ("lead_events", "lead_type"),
                     "status": ("lead_events", "ownership_match")}


def _bulk_sort_key(key):
    def k(r):
        if key == "priority":  return r["_score"]
        if key == "distance":  return r.get("_dist", 9e9)
        if key == "date":      return r["received_date"] or ""
        if key == "status":    return r["ownership_match"] or ""
        if key == "lead_type": return r["lead_type"] or ""
        if key == "city":      return (r["property_city"] or "").lower()
        if key == "county":    return (r["county"] or "").lower()
        if key == "zip":       return r["property_zip"] or ""
        return ((r["last_name"] or "").lower(), (r["first_name"] or "").lower())
    return k


def _bulk_where(args):
    clauses, params = [], {}
    for f in BULK_FILTERS:
        raw = (args.get(f["key"]) or "").strip()
        if not raw:
            continue
        params[f["key"]] = f["wrap"].format(raw) if f["wrap"] else raw
        clauses.append(f"{f['col']} {f['op']} :{f['key']}")
    return ((" AND " + " AND ".join(clauses)) if clauses else ""), params


def bulk_matches(conn, args):
    """Matched leads (deduped by contact+property) with priority score attached,
    honoring the filter registry, the arrange-by sort, and an optional top-N cap.
    Applies a geocoded radius post-filter when a center address + miles are given.
    Returns (rows, arrange_key, info) where info carries radius status/messages."""
    where, params = _bulk_where(args)
    rows = conn.execute(
        "SELECT le.contact_id, le.property_id, c.first_name, c.last_name, "
        "le.lead_type, le.ownership_match, le.received_date, "
        "p.property_city, p.property_zip, p.county, p.neighborhood_code, "
        "p.property_address, p.photo_file, p.latitude, p.longitude "
        "FROM lead_events le "
        "JOIN contacts c   ON c.id = le.contact_id "
        "JOIN properties p ON p.id = le.property_id "
        "WHERE p.property_street IS NOT NULL AND TRIM(p.property_street)!='' " + where,
        params,
    ).fetchall()
    # Priority score for every lead, keyed by (contact_id, property_id).
    score_map = {(it["row"]["contact_id"], it["row"]["property_id"]): it["score"]
                 for it in priority.ranked_leads(conn)}
    # Dedupe by (contact, property), keeping the most recent received_date.
    best = {}
    for r in rows:
        d = dict(r)
        d["_score"] = score_map.get((d["contact_id"], d["property_id"]), 0)
        key = (d["contact_id"], d["property_id"])
        if key not in best or (d["received_date"] or "") > (best[key]["received_date"] or ""):
            best[key] = d
    matched = list(best.values())

    # Radius post-filter. Not a SQL registry entry: it needs the center geocoded
    # and a great-circle distance per row, so it runs after the query.
    info = {"radius": False}
    center = (args.get("center") or "").strip()
    try:
        radius_mi = float(args.get("radius_mi") or 0)
    except ValueError:
        radius_mi = 0
    if center and radius_mi > 0:
        info.update({"radius": True, "center": center, "radius_mi": radius_mi})
        c = geocode.geocode_address(center)
        if not c:
            info["center_failed"] = True
            matched = []
        else:
            info["center_latlng"] = (c["lat"], c["lng"])
            kept, no_coords = [], 0
            for d in matched:
                if d["latitude"] is None or d["longitude"] is None:
                    no_coords += 1
                    continue
                dist = geocode.haversine_miles(c["lat"], c["lng"], d["latitude"], d["longitude"])
                if dist <= radius_mi:
                    d["_dist"] = dist
                    kept.append(d)
            info["no_coords_skipped"] = no_coords
            matched = kept

    arrange = args.get("arrange")
    if arrange not in BULK_SORTS or (arrange == "distance" and not info["radius"]):
        arrange = "distance" if info["radius"] else "priority"
    matched.sort(key=_bulk_sort_key(arrange), reverse=BULK_SORTS[arrange][1])
    try:
        top_n = int(args.get("top_n") or 0)
    except ValueError:
        top_n = 0
    if top_n > 0:
        matched = matched[:top_n]
    return matched, arrange, info


@app.route("/letters/bulk")
def letters_bulk():
    conn = db()
    args = request.args
    msg = args.get("msg", "")
    buttons = iautosend.load_buttons()
    submitted = bool(args.get("go"))
    matched, arrange, info = (bulk_matches(conn, args) if submitted
                              else ([], "priority", {"radius": False}))
    missing_coords = geocode.count_missing(conn)

    def distinct(table, col):
        return [r["v"] for r in conn.execute(
            f"SELECT DISTINCT {col} v FROM {table} "
            f"WHERE {col} IS NOT NULL AND TRIM({col})!='' ORDER BY 1")]
    option_lists = {k: distinct(*tc) for k, tc in _BULK_OPTION_COLS.items()}

    def sel_opts(values, current):
        out = ["<option value=''>(any)</option>"]
        for v in values:
            s = " selected" if v == current else ""
            out.append(f"<option value='{esc(v)}'{s}>{esc(v)}</option>")
        return "".join(out)

    ctrls = []
    for f in BULK_FILTERS:
        cur = args.get(f["key"], "")
        if f["kind"] == "select":
            inner = f"<select name='{f['key']}'>{sel_opts(option_lists[f['key']], cur)}</select>"
        elif f["kind"] == "date":
            inner = f"<input type='date' name='{f['key']}' value='{esc(cur)}'>"
        else:
            inner = f"<input name='{f['key']}' value='{esc(cur)}' placeholder='{esc(f['label'])}'>"
        ctrls.append(f"<label class='flab'>{esc(f['label'])}{inner}</label>")
    arrange_opts = "".join(
        f"<option value='{k}'{' selected' if k == arrange else ''}>{esc(lbl)}</option>"
        for k, (lbl, _) in BULK_SORTS.items())
    tmpl_opts = "".join(
        f"<option value='{esc(k)}'>{esc(v.get('label', k))}</option>" for k, v in buttons.items())

    filter_form = (
        "<form class='bulkfilters' method='get' action='/letters/bulk'>"
        + "".join(ctrls)
        + f"<label class='flab'>Within (miles)<input type='number' min='0' step='0.5' "
          f"name='radius_mi' value='{esc(args.get('radius_mi', ''))}' placeholder='e.g. 3' "
          f"style='width:90px'></label>"
        + f"<label class='flab'>of center address<input name='center' "
          f"value='{esc(args.get('center', ''))}' placeholder='13533 Boulder Ridge Rd, Snohomish WA' "
          f"style='width:260px'></label>"
        + f"<label class='flab'>Arrange by<select name='arrange'>{arrange_opts}</select></label>"
        + f"<label class='flab'>Top N (0=all)<input type='number' min='0' name='top_n' "
          f"value='{esc(args.get('top_n', '0'))}' style='width:90px'></label>"
        + "<input type='hidden' name='go' value='1'><button>Show matches</button></form>")

    # On-demand geocode for any leads still missing coordinates (covers new leads
    # without a scraper change; also retries the rare free-source gap once Google
    # billing is on).
    geo_note = ""
    if missing_coords:
        geo_note = (
            "<div class='note'>"
            f"{missing_coords} propert{'y' if missing_coords == 1 else 'ies'} "
            "lack coordinates, so they cannot match a radius filter. "
            "<form class='rowform' method='post' action='/geocode/backfill'>"
            f"<button class='sm'>Geocode {missing_coords} now</button></form></div>")

    # Radius status line (success, no-center-match, or skipped-for-no-coords).
    radius_msg = ""
    if info.get("radius"):
        if info.get("center_failed"):
            radius_msg = (f"<div class='banner'>Could not locate the center address "
                          f"\"{esc(info['center'])}\". Check the spelling, or it may be a "
                          f"free-source gap (Google geocoding will help once billing is on).</div>")
        else:
            extra = ""
            if info.get("no_coords_skipped"):
                extra = (f" ({info['no_coords_skipped']} match(es) skipped for missing "
                         f"coordinates - use Geocode above.)")
            radius_msg = (f"<div class='banner'>Within {info['radius_mi']:g} mi of "
                          f"\"{esc(info['center'])}\".{extra}</div>")

    dist_th = "<th>Distance</th>" if info.get("radius") else ""
    if not submitted:
        results = ("<div class='sub'>Set any filters and click <b>Show matches</b> to build a "
                   "list, then queue letters for the ones you keep checked.</div>")
    elif matched:
        trs = ""
        for d in matched:
            token = f"{d['contact_id']}:{d['property_id']}"
            name = f"{esc(d['first_name'])} {esc(d['last_name'])}".strip()
            dist_td = (f"<td class='mut'>{d['_dist']:.1f} mi</td>"
                       if info.get("radius") and "_dist" in d else (dist_th and "<td></td>"))
            trs += (
                f"<tr><td><input type='checkbox' name='lead' value='{token}' checked></td>"
                f"<td><span class='score {_score_class(d['_score'])}'>{d['_score']}</span></td>"
                f"<td><a class='rowlink' href='/property/{d['property_id']}'>{name}</a></td>"
                f"<td class='mut'>{esc((d['property_address'] or '')[:42])}</td>"
                f"<td>{esc(d['property_city'] or '')}</td>"
                f"<td class='mut'>{esc(d['lead_type'] or '')}</td>"
                f"<td>{pill(d['ownership_match'] or 'NO')}</td>"
                f"<td class='mut'>{esc(d['received_date'] or '')}</td>{dist_td}</tr>")
        results = (
            radius_msg
            + "<form method='post' action='/iauto/queue_bulk' "
            "onsubmit=\"return confirm('Queue letters for all checked leads?');\">"
            "<div class='actions'>"
            f"<select name='template'>{tmpl_opts}</select>"
            f"<button>Queue letters for checked ({len(matched)})</button>"
            "<label class='mut'><input type='checkbox' checked "
            "onclick=\"for(const c of document.querySelectorAll('input[name=lead]'))c.checked=this.checked\"> "
            "select all</label></div>"
            "<table><tr><th></th><th>Score</th><th>Lead</th><th>Property</th><th>City</th>"
            f"<th>Type</th><th>Verdict</th><th>Received</th>{dist_th}</tr>{trs}</table></form>")
    else:
        results = radius_msg + "<div class='empty'>No leads match those filters.</div>"

    banner = f"<div class='banner'>{esc(msg)}</div>" if msg else ""
    body = (
        "<h2>Bulk letter queue</h2>"
        "<div class='sub'>Build a mailing list by city, county, zip, neighborhood, lead type, "
        "verdict, received date, or radius (within N miles of an address), arrange it "
        "(including by listing-likelihood score or distance), optionally cap to the top N, "
        "then queue letters for the ones you keep checked.</div>"
        f"{banner}{geo_note}{filter_form}{results}"
        "<div class='note'>Queued letters land in the main <a href='/letters'>Letters</a> "
        "queue, where you send them to the machine.</div>")
    conn.close()
    return page("Bulk", body)


@app.route("/geocode/backfill", methods=["POST"])
def geocode_backfill():
    backup.make_backup(verbose=False)
    conn = db()
    res = geocode.backfill(conn, verbose=False)
    conn.close()
    msg = (f"Geocoded {res['geocoded']} propert(y/ies), {res['failed']} failed. "
           f"Sources: {res['by_source'] or '(none)'}.")
    return redirect(url_for("letters_bulk", msg=msg))


@app.route("/letters")
def letters():
    conn = db()
    msg = request.args.get("msg", "")
    buttons = iautosend.load_buttons()

    # Eligible leads for the queue dropdown (any lead with a street address).
    eligible = conn.execute(
        "SELECT le.contact_id, le.property_id, ct.first_name, ct.last_name, "
        "p.property_street, p.property_city "
        "FROM lead_events le JOIN contacts ct ON ct.id=le.contact_id "
        "JOIN properties p ON p.id=le.property_id "
        "WHERE p.property_street IS NOT NULL AND TRIM(p.property_street)!='' "
        "ORDER BY ct.last_name, ct.first_name"
    ).fetchall()
    lead_opts = "".join(
        f"<option value='{r['contact_id']}:{r['property_id']}'>"
        f"{esc(r['first_name'])} {esc(r['last_name'])} - {esc(r['property_street'])}, "
        f"{esc(r['property_city'])}</option>" for r in eligible)
    tmpl_opts = "".join(
        f"<option value='{esc(k)}'>{esc(v.get('label', k))}</option>" for k, v in buttons.items())

    queue_form = (
        "<h2>Queue a letter</h2>"
        "<div class='sub'>Pick a lead and a template. It lands in the queue below, "
        "ready to send to the machine.</div>"
        "<form class='filters' method='post' action='/iauto/queue'>"
        f"<select name='lead'>{lead_opts}</select>"
        f"<select name='template'>{tmpl_opts}</select>"
        "<button>Queue letter</button></form>")

    hb_status = _homebot_status_map(conn)
    rows = conn.execute(
        "SELECT o.id, o.contact_id, o.property_id, c.first_name, c.last_name, "
        "p.property_address, o.template, o.status, o.detail, o.sent_at FROM outreach o "
        "LEFT JOIN contacts c   ON c.id = o.contact_id "
        "LEFT JOIN properties p ON p.id = o.property_id "
        "WHERE o.channel='iauto' ORDER BY o.id DESC"
    ).fetchall()

    if rows:
        trs = ""
        for r in rows:
            label, cls = _IAUTO_PILL.get(r["status"], (str(r["status"]).upper(), "NO"))
            sent_disp = (r["sent_at"] or "")[:16] if r["status"] == "sent" else ""
            # Template: editable dropdown while still queued, read-only label once sent/failed.
            if r["status"] == "queued":
                opts = "".join(
                    f"<option value='{esc(k)}'{' selected' if k == r['template'] else ''}>"
                    f"{esc(v.get('label', k))}</option>" for k, v in buttons.items())
                tmpl_cell = (
                    "<form class='rowform' method='post' action='/iauto/queue/template'>"
                    f"<input type='hidden' name='id' value='{r['id']}'>"
                    f"<select name='template' class='sm' onchange='this.form.submit()'>{opts}</select>"
                    "</form>")
            else:
                tmpl_cell = esc(buttons.get(r["template"], {}).get("label", r["template"]))
            confirm = "return confirm('Send this to the iAuto machine now?');"
            send_letter = (
                f"<form class='rowform' method='post' action='/iauto/send' onsubmit=\"{confirm}\">"
                f"<input type='hidden' name='id' value='{r['id']}'><input type='hidden' name='kind' value='letter'>"
                f"<button class='sm'>Send letter</button></form>")
            send_env = (
                f"<form class='rowform' method='post' action='/iauto/send' onsubmit=\"{confirm}\">"
                f"<input type='hidden' name='id' value='{r['id']}'><input type='hidden' name='kind' value='envelope'>"
                f"<button class='sm ghost'>Send envelope</button></form>")
            hb_cell = homebot_action_cell(conn, r["contact_id"], r["property_id"], hb_status)
            trs += (
                f"<tr><td>{esc(r['first_name'])} {esc(r['last_name'])}</td>"
                f"<td class='mut'>{esc((r['property_address'] or '')[:38])}</td>"
                f"<td>{tmpl_cell}</td>"
                f"<td><span class='pill {cls}'>{label}</span></td>"
                f"<td class='mut'>{esc(sent_disp)}</td>"
                f"<td class='reason'>{esc(r['detail'] or '')}</td>"
                f"<td>{send_letter} {send_env}</td>"
                f"<td>{hb_cell}</td></tr>")
        table = (f"<table><tr><th>Recipient</th><th>Property</th><th>Template</th>"
                 f"<th>Status</th><th>Sent</th><th>Detail</th><th>Send</th><th>Homebot</th></tr>{trs}</table>")
        queued_n = sum(1 for r in rows if r["status"] in ("queued", "failed"))
        send_all = ""
        if queued_n:
            send_all = (
                "<div class='actions'>"
                "<form class='rowform' method='post' action='/iauto/send_all' "
                "onsubmit=\"return confirm('Send all queued letters to the machine now?');\">"
                f"<button>Send all queued letters ({queued_n})</button></form></div>")
    else:
        table = "<div class='empty'>The queue is empty. Queue a letter above to begin.</div>"
        send_all = ""

    note = ("<div class='note'>Load-out reminder: the machine writes the letter on "
            "letter paper, then you swap to envelopes and use <b>Send envelope</b>. "
            "If the machine is off or off-network, a send is marked FAILED with the "
            "reason; fix it and send again.</div>")
    banner = f"<div class='banner'>{esc(msg)}</div>" if msg else ""
    body = (f"<h2>iAuto letter queue</h2>"
            f"<div class='sub'>Queue handwritten notes and send them to the machine.</div>"
            f"{banner}{queue_form}<h2>Queue</h2>{send_all}{table}{note}")
    conn.close()
    return page("Letters", body)


@app.route("/iauto/queue", methods=["POST"])
def iauto_queue():
    conn = db()
    lead = request.form.get("lead", "")
    template = request.form.get("template", "")
    try:
        cid, pid = (int(x) for x in lead.split(":"))
        iautosend.queue_letter(conn, cid, pid, template)
        msg = "Letter queued."
    except (ValueError, KeyError):
        msg = "Could not queue: bad lead selection."
    conn.close()
    return redirect(url_for("letters", msg=msg))


@app.route("/iauto/queue/template", methods=["POST"])
def iauto_queue_template():
    """Change the template on a still-queued letter. Lets a letter queued from any
    page (which defaults to seller_lead_initial) be re-pointed before it's sent."""
    conn = db()
    oid = request.form.get("id")
    template = request.form.get("template", "")
    try:
        conn.execute(
            "UPDATE outreach SET template=? "
            "WHERE id=? AND channel='iauto' AND status='queued'",
            (template, int(oid)))
        conn.commit()
        msg = "Template updated."
    except (ValueError, TypeError):
        msg = "Could not update template: bad request."
    conn.close()
    return redirect(url_for("letters", msg=msg))


@app.route("/iauto/queue_bulk", methods=["POST"])
def iauto_queue_bulk():
    conn = db()
    template = request.form.get("template", "")
    tokens = request.form.getlist("lead")
    queued = 0
    for token in tokens:
        try:
            cid, pid = (int(x) for x in token.split(":"))
            iautosend.queue_letter(conn, cid, pid, template)
            queued += 1
        except (ValueError, KeyError):
            continue
    conn.close()
    if queued:
        msg = f"Queued {queued} letter(s) from the bulk selection."
    else:
        msg = "Nothing queued: no leads were selected."
    return redirect(url_for("letters", msg=msg))


@app.route("/iauto/send", methods=["POST"])
def iauto_send_route():
    conn = db()
    oid = request.form.get("id")
    kind = request.form.get("kind", "letter")
    res = iautosend.send_outreach(conn, int(oid), kind=kind, dry_run=False)
    conn.close()
    if res["status"] == "sent":
        msg = f"{kind.capitalize()} sent to the machine for {res.get('name','')}."
    else:
        msg = f"{kind.capitalize()} not sent: {res.get('detail','')}"
    return redirect(url_for("letters", msg=msg))


@app.route("/iauto/send_all", methods=["POST"])
def iauto_send_all():
    conn = db()
    out = iautosend.run_send(conn, kind="letter", dry_run=False)
    conn.close()
    c = out["counts"]
    msg = (f"Send-all done. Sent {c.get('sent', 0)}, failed {c.get('failed', 0)}. "
           f"(Letters only; send envelopes per row after the paper swap.)")
    return redirect(url_for("letters", msg=msg))


# ── Lead / property detail ───────────────────────────────────────────────────

@app.route("/photo/<int:pid>/<which>")
def photo(pid, which):
    conn = db()
    p = conn.execute("SELECT photo_file, assessor_photo_file FROM properties WHERE id=?",
                     (pid,)).fetchone()
    conn.close()
    if not p:
        abort(404)
    path = p["assessor_photo_file"] if which == "assessor" else p["photo_file"]
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path)


@app.route("/lead/<int:cid>/<int:pid>/reenrich", methods=["POST"])
def lead_reenrich(cid, pid):
    """Re-run the county assessor lookup for one lead (reenrich_v0_1_0). On a
    match the property is upgraded in place and the verdict flips, preserving the
    original lead date; on a failure the stored 'Last assessor lookup' panel on
    the detail page explains what the assessor returned and why it didn't match."""
    conn = db()
    try:
        result = reenrich.reenrich(conn, cid, pid)
    except Exception as e:  # never leave the user on a 500 from a lookup hiccup
        conn.close()
        return redirect(url_for("property_detail", pid=pid,
                                msg=f"Re-run failed to run: {e}"))
    conn.close()
    eff_pid = result.get("property_id") or pid
    if result["status"] == "MATCHED":
        msg = "Re-run matched and updated this lead in place. Details below."
    else:
        msg = (f"Re-run finished: {result['status']}. See 'Last assessor lookup' "
               "below for what the assessor returned.")
    return redirect(url_for("property_detail", pid=eff_pid, msg=msg))


@app.route("/property/<int:pid>")
def property_detail(pid):
    conn = db()
    p = conn.execute("SELECT * FROM properties WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        abort(404)
    leads = conn.execute(
        "SELECT le.*, ct.id AS contact_id, ct.first_name, ct.last_name, ct.email, "
        "ct.phone, ct.contact_type "
        "FROM lead_events le JOIN contacts ct ON ct.id=le.contact_id "
        "WHERE le.property_id=? ORDER BY le.id DESC", (pid,)).fetchall()
    msg = request.args.get("msg", "")

    # Photos (only render the ones whose files actually exist on this machine).
    photo_figs = ""
    for which, label, col in [("assessor", "Assessor photo", "assessor_photo_file"),
                              ("street", "Street View", "photo_file")]:
        path = p[col]
        if path and os.path.exists(path):
            photo_figs += (f"<figure><img src='/photo/{pid}/{which}' alt='{esc(label)}'>"
                           f"<figcaption>{esc(label)}</figcaption></figure>")
    photos = f"<div class='photos'>{photo_figs}</div>" if photo_figs else \
             "<div class='note'>No photos saved for this property.</div>"

    owner = " &nbsp;·&nbsp; ".join(filter(None, [
        f"{p['owner1_first']} {p['owner1_last']}".strip(),
        f"{p['owner2_first']} {p['owner2_last']}".strip()])) or "&mdash;"
    owner_grid = (
        f"<div class='kv'><div class='k'>Owner of record</div><div class='v'>{owner}</div></div>"
        + kvc("Owner mailing address", p["owner_address"])
        + kvc("Taxpayer", p["taxpayer_name"])
        + kvc("Parcel", p["parcel_number"])
        + kvc("County", p["county"])
        + kvc("Use / category", " / ".join(filter(None, [p["use_code"], p["property_category"]]))))

    facts = "".join([
        kvc("Year built", p["year_built"]),
        kvc("Bedrooms", p["bedrooms"]),
        kvc("Baths (full / ¾)", p["baths_full_three_quarter"]),
        kvc("Half baths", p["half_baths"]),
        kvc("Finished sqft", p["total_finished_sf"]),
        kvc("Grade", p["property_grade"]),
        kvc("Condition", p["property_condition"]),
        kvc("Heat", p["heat"]),
        kvc("Exterior", p["exterior"]),
        kvc("Roof", p["roof_type"]),
        kvc("Foundation", p["foundation"]),
        kvc("Views", p["views"]),
        kvc("Waterfront", p["waterfront"]),
    ])

    values = "".join([
        kvc("Assessed value", p["assessed_value"], hi=True),
        kvc("Market total", p["market_total"]),
        kvc("Market land", p["market_land"]),
        kvc("Market improvement", p["market_improvement"]),
        kvc("Taxable (regular)", p["taxable_value_regular"]),
        kvc("Annual tax", p["annual_tax_amount"]),
        kvc("Tax year", p["latest_tax_year"]),
        kvc("Last sale date", p["most_recent_sale_date"]),
        kvc("Last sale amount", p["most_recent_sale_amount"]),
    ])
    sale_blob = ""
    if p["sales_history"]:
        sale_blob = ("<div class='kv' style='grid-column:1/-1'><div class='k'>Sale history</div>"
                     f"<div class='v' style='font-weight:400'>{esc(p['sales_history'])}</div></div>")

    hb_status = _homebot_status_map(conn)
    lead_rows = ""
    for le in leads:
        name = f"{le['first_name']} {le['last_name']}".strip()
        queue_btn = (
            "<form class='rowform' method='post' action='/iauto/queue' "
            f"onsubmit=\"return confirm('Queue an iAuto letter for {esc(name)}?');\">"
            f"<input type='hidden' name='lead' value='{le['contact_id']}:{pid}'>"
            "<input type='hidden' name='template' value='seller_lead_initial'>"
            "<button class='sm'>Queue iAuto letter</button></form>")
        enroll_btn = homebot_action_cell(conn, le["contact_id"], pid, hb_status, next_pid=pid)
        reenrich_btn = (
            "<form class='rowform' method='post' action='/lead/"
            f"{le['contact_id']}/{pid}/reenrich' "
            "onsubmit=\"return confirm('Re-run the county assessor lookup for "
            f"{esc(name)}? This can take several seconds.');\">"
            "<button class='sm ghost'>Re-run assessor lookup</button></form>")
        lead_rows += (
            f"<tr><td><b>{esc(name)}</b> "
            f"<a class='back' href='/contact/{le['contact_id']}/edit?next_pid={pid}'>edit</a>"
            f"<div class='mut'>{esc(le['contact_type'] or '')}</div>{reenrich_btn}</td>"
            f"<td>{pill(le['ownership_match'] or '—')}"
            f"<div class='mut'>{esc(le['match_confidence'])} &middot; {esc(le['match_relationship'] or '')}</div></td>"
            f"<td class='mut'>{esc(le['email'] or '')}<br>{esc(le['phone'] or '')}</td>"
            f"<td class='mut'>{esc(le['lead_type'] or '')} &middot; {esc(le['lead_source'] or '')}"
            f"<br>{esc(le['received_date'] or '')}</td>"
            f"<td class='reason'>{esc(le['match_reason'] or '')}</td>"
            f"<td>{queue_btn}</td><td>{enroll_btn}</td></tr>")
    leads_table = (
        "<table><tr><th>Contact</th><th>Verdict</th><th>Contact info</th><th>Lead</th>"
        f"<th>Why</th><th>Letter</th><th>Homebot</th></tr>{lead_rows}</table>") if leads else \
        "<div class='empty'>No leads linked to this property.</div>"

    addr = p["property_address"] or p["property_street"] or f"Property #{pid}"
    banner = f"<div class='banner'>{esc(msg)}</div>" if msg else ""

    # "Last assessor lookup" panel: the stored outcome of the most recent re-run,
    # so a failed re-enrichment shows what the assessor returned (and why it
    # didn't match) instead of disappearing.
    pk = p.keys()
    lookup_panel = ""
    if "last_lookup_at" in pk and p["last_lookup_at"]:
        st = p["last_lookup_status"] or ""
        st_cls = {"MATCHED": "CONFIRMED", "NO MATCH": "MISMATCH",
                  "ERROR": "MISMATCH", "NO ADDRESS": "REVIEW"}.get(st, "NO")
        lookup_panel = (
            "<div class='detail-grid' style='margin:12px 0'>"
            "<div class='kv' style='grid-column:1/-1'>"
            f"<div class='k'>Last assessor lookup &nbsp;"
            f"<span class='pill {st_cls}'>{esc(st)}</span></div>"
            f"<div class='v' style='font-weight:400'>{esc(p['last_lookup_detail'] or '')}"
            f"<div class='mut' style='margin-top:4px'>checked {esc(p['last_lookup_at'])}</div>"
            "</div></div></div>")

    body = (
        "<a class='back' href='/leads'>&larr; back to leads</a>"
        f"<h2 style='margin-top:8px'>{esc(addr)}</h2>"
        f"<div class='sub'>{esc(p['county'] or '')} &middot; parcel {esc(p['parcel_number'] or '—')}</div>"
        f"{banner}{lookup_panel}{photos}"
        f"<h2>Owner of record</h2><div class='detail-grid'>{owner_grid}</div>"
        f"<h2>Property</h2><div class='detail-grid'>{facts}</div>"
        f"<h2>Valuation &amp; sales</h2><div class='detail-grid'>{values}{sale_blob}</div>"
        f"<h2>Leads &amp; contacts</h2>{leads_table}")
    conn.close()
    return page("Leads", body)


# ── Homebot ──────────────────────────────────────────────────────────────────

_HB_PILL = {"sent": ("ENROLLED", "CONFIRMED"), "skipped": ("IN HOMEBOT", "LIKELY"),
            "failed": ("FAILED", "MISMATCH")}


def _homebot_status_map(conn):
    out = {}
    for o in conn.execute("SELECT contact_id, status, detail FROM outreach "
                          "WHERE channel='homebot' ORDER BY id"):
        label, cls = _HB_PILL.get(o["status"], (o["status"].upper(), "NO"))
        out[o["contact_id"]] = (label, cls, o["detail"] or "")
    return out


def is_homebot_eligible(conn, contact_id, property_id):
    """True if this lead qualifies for the Homebot Market Digest: a Seller lead
    with a CONFIRMED/LIKELY ownership match and an email on file. Mirrors the
    eligibility WHERE clause in homebot_push_v0_1_0.SELECT_SQL."""
    return conn.execute(
        "SELECT 1 FROM lead_events le JOIN contacts ct ON ct.id=le.contact_id "
        "WHERE le.contact_id=? AND le.property_id=? AND le.lead_type='Seller' "
        "AND le.ownership_match IN ('CONFIRMED','LIKELY') "
        "AND ct.email IS NOT NULL AND TRIM(ct.email)!='' LIMIT 1",
        (contact_id, property_id)).fetchone() is not None


def _homebot_block_reason(conn, contact_id):
    """Why a lead can't be enrolled, for an informative cell instead of a bare dash.
    Email is the hard requirement (Homebot's digest address + dedupe key)."""
    row = conn.execute("SELECT TRIM(COALESCE(email,''))!='' FROM contacts WHERE id=?",
                       (contact_id,)).fetchone()
    if row is not None and not row[0]:
        return "needs an email"
    return "not a verified seller lead"


def homebot_action_cell(conn, contact_id, property_id, status_map, next_pid=None):
    """Inline Homebot control for a lead row: the status pill if already enrolled
    or already in Homebot, an Enroll button if eligible and not yet enrolled, or a
    short reason if ineligible (so it never looks broken). next_pid (a property id)
    routes the redirect back to that detail page instead of /letters."""
    st = status_map.get(contact_id)
    if st:
        return f"<span class='pill {st[1]}'>{st[0]}</span>"
    if not is_homebot_eligible(conn, contact_id, property_id):
        return ("<span class='mut' title='Homebot needs a Seller lead with a "
                f"CONFIRMED/LIKELY match and an email'>{_homebot_block_reason(conn, contact_id)}</span>")
    nxt = f"<input type='hidden' name='next_pid' value='{next_pid}'>" if next_pid else ""
    return (
        "<form class='rowform' method='post' action='/homebot/enroll_one' "
        "onsubmit=\"return confirm('Enroll this lead in Homebot now (live)?');\">"
        f"<input type='hidden' name='contact_id' value='{contact_id}'>"
        f"<input type='hidden' name='property_id' value='{property_id}'>{nxt}"
        "<button class='sm ghost'>Enroll in Homebot</button></form>")


@app.route("/homebot")
def homebot():
    conn = db()
    msg = request.args.get("msg", "")
    show_preview = request.args.get("preview") == "1"

    rows = hbpush.select_leads(conn)
    smap = _homebot_status_map(conn)
    n_enrolled = sum(1 for r in rows if smap.get(r["contact_id"], ("",))[0] == "ENROLLED")
    n_inhb = sum(1 for r in rows if smap.get(r["contact_id"], ("",))[0] == "IN HOMEBOT")
    n_pending = len(rows) - n_enrolled - n_inhb

    cards = "".join(
        f'<div class="card"><div class="n">{v}</div><div class="l">{k}</div></div>'
        for k, v in [("Eligible", len(rows)), ("Enrolled", n_enrolled),
                     ("Already in Homebot", n_inhb), ("Pending", n_pending)])

    table_rows = ""
    for r in rows:
        st = smap.get(r["contact_id"])
        label, cls, detail = st if st else ("PENDING", "NO", "not yet processed")
        table_rows += (
            f"<tr><td>{esc(r['first_name'])} {esc(r['last_name'])}</td>"
            f"<td class='mut'>{esc(r['email'])}</td>"
            f"<td class='mut'>{esc(r['property_street'])}, {esc(r['property_city'])}</td>"
            f"<td>{pill(r['ownership_match'])}</td>"
            f"<td><span class='pill {cls}'>{label}</span></td>"
            f"<td class='reason'>{esc(detail)}</td></tr>")
    table = (f"<table><tr><th>Lead</th><th>Email</th><th>Property</th><th>Verdict</th>"
             f"<th>Homebot</th><th>Detail</th></tr>{table_rows}</table>") if rows else \
            "<div class='empty'>No eligible seller leads (need Seller + CONFIRMED/LIKELY + email).</div>"

    banner = f"<div class='banner'>{esc(msg)}</div>" if msg else ""
    confirm_js = ("return confirm('Enroll the new leads on the Homebot Market Digest? "
                  "This emails real homeowners and cannot be silently undone.');")
    actions = (
        "<div class='actions'>"
        "<a href='/homebot?preview=1'><button class='ghost' type='button'>Preview (dry run)</button></a>"
        f"<form method='post' action='/homebot/enroll' style='margin:0' onsubmit=\"{confirm_js}\">"
        f"<button class='danger'>Enroll new leads (live)</button></form>"
        "<span class='mut'>Dedupe skips anyone already in Homebot. Status is read from "
        "the local log; run an enrollment to refresh everyone.</span></div>")

    preview_html = ""
    if show_preview:
        out = hbpush.run(live=False, conn=conn)
        items = "".join(
            f"<tr><td>{esc(r['name'])}</td><td class='mut'>{esc(r['client_attrs'].get('email'))}</td>"
            f"<td class='mut'>{esc(r['client_attrs'].get('mobile') or '')}</td>"
            f"<td class='mut'>{esc(r['home_attrs'].get('address-street'))} "
            f"{esc(r['home_attrs'].get('address-zip'))}</td></tr>"
            for r in out["results"])
        preview_html = (
            "<h2>Dry-run preview (no calls made)</h2>"
            "<div class='sub'>Exactly what would be sent for each eligible lead. "
            "Dedupe still skips existing clients at enrollment time.</div>"
            f"<table><tr><th>Name</th><th>Email</th><th>Mobile</th><th>Home (street + zip)</th></tr>"
            f"{items}</table>")

    body = (f"<h2>Homebot Market Digest</h2>"
            f"<div class='sub'>Enroll verified seller leads as Homebot Client + Home "
            f"records. Homebot then sends them the monthly home-value digest.</div>"
            f"{banner}{cards}{actions}{table}{preview_html}")
    conn.close()
    return page("Homebot", body)


@app.route("/homebot/enroll", methods=["POST"])
def homebot_enroll():
    conn = db()
    out = hbpush.run(live=True, conn=conn)
    conn.close()
    if out["error"]:
        msg = "Error: " + out["error"]
    else:
        c = out["counts"]
        msg = (f"Done. Enrolled {c.get('sent', 0)} new, skipped {c.get('skipped', 0)} "
               f"already in Homebot, {c.get('failed', 0)} failed.")
    return redirect(url_for("homebot", msg=msg))


@app.route("/homebot/enroll_one", methods=["POST"])
def homebot_enroll_one():
    """Enroll a single lead in Homebot from an inline button. Reuses hbpush.run()
    filtered to the contact's email (Homebot dedupes by email). Redirects back to
    the originating page (a property detail via next_pid, else the Letters queue)."""
    conn = db()
    cid = request.form.get("contact_id")
    next_pid = request.form.get("next_pid")
    contact = conn.execute("SELECT email, first_name, last_name FROM contacts WHERE id=?",
                           (cid,)).fetchone() if cid else None
    if not contact or not (contact["email"] or "").strip():
        conn.close()
        msg = "Could not enroll: no email on that contact."
    else:
        out = hbpush.run(email=contact["email"].strip(), live=True, conn=conn)
        conn.close()
        name = f"{contact['first_name']} {contact['last_name']}".strip()
        if out["error"]:
            msg = f"Homebot enroll failed for {name}: {out['error']}"
        else:
            c = out["counts"]
            if c.get("sent"):
                msg = f"Enrolled {name} in Homebot."
            elif c.get("skipped"):
                msg = f"{name} was already in Homebot."
            elif c.get("failed"):
                msg = f"Homebot enroll failed for {name}; see the Homebot page."
            else:
                msg = f"No eligible Homebot lead found for {name}."
    if next_pid:
        try:
            return redirect(url_for("property_detail", pid=int(next_pid), msg=msg))
        except (ValueError, TypeError):
            pass
    return redirect(url_for("letters", msg=msg))


if __name__ == "__main__":
    # Safety: snapshot the DB on launch (at most once an hour) and warn about
    # any OneDrive sync-conflict copies before serving.
    snap = backup.safe_backup_on_start(min_interval_minutes=60)
    if snap:
        print(f"DB backup: {os.path.basename(snap)}")
    conflicts = backup.find_conflict_copies()
    if conflicts:
        print(f"WARNING: possible OneDrive conflict copies: {conflicts} "
              f"(run: python propintel_backup_v0_1_0.py --check)")

    # Bind to 0.0.0.0 so phones/tablets on the SAME home WiFi can open it too.
    # Find this PC's LAN IP for the phone URL (best-effort; no traffic sent).
    lan_ip = "127.0.0.1"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    print("PropIntel dashboard  (Ctrl+C to stop)")
    print("  On this PC:        http://127.0.0.1:5000")
    print(f"  On your phone/tablet (same WiFi):  http://{lan_ip}:5000")
    print("  (No password - anyone on your WiFi can view it. Home network only.)")
    app.run(host="0.0.0.0", port=5000, debug=False)
