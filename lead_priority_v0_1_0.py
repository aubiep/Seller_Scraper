"""
Lead Priority  v0.1.0
=====================
Turns the enriched data into a daily "work these first" list. Each lead gets a
0-100 Listing-Likelihood score with a transparent breakdown of WHY, so the
dashboard can show "call these five today" instead of a flat table.

Signals (all from data that's reliably populated; see WEIGHTS to tune):
  - Ownership match: CONFIRMED means the lead really owns the property (can
    actually list it); MISMATCH means they don't, so they sink.
  - Owner-occupancy: the owner's mailing address matches the property -> they
    live in the home they asked about -> real potential seller.
  - Tenure: years since last sale. Longer = more equity and more likely to move.
  - Repeat lead: asked for a value more than once = high intent.
  - Appreciation: market value minus last sale price = equity to move on.
  - Recency: a brand-new lead is worth acting on fast ("speed wins").

The weights are deliberately simple and editable - this is a starting model to
tune against real results, not gospel.
"""

import re
from datetime import datetime

import propintel_db_v0_1_0 as pdb

WEIGHTS = {
    "confirmed": 35, "likely": 20, "mismatch": 0,
    "owner_occupied": 20,
    "tenure_max": 18,        # full points at >= tenure_years_full
    "tenure_years_full": 15,
    "repeat": 15,
    "appreciation_max": 12,  # full points at >= appreciation_full (in $)
    "appreciation_full": 300000,
    "recent": 8,             # lead received within recent_days
    "recent_days": 7,
}


def _num(s):
    if s is None:
        return None
    t = re.sub(r"[^\d.]", "", str(s))
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _years_since(date_str):
    if not date_str:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            d = datetime.strptime(date_str.strip(), fmt)
            return (datetime.now() - d).days / 365.25
        except ValueError:
            continue
    return None


def _norm_street(addr):
    """First address segment, alphanumeric-lowercased, for owner-occupancy compare."""
    if not addr:
        return ""
    first = str(addr).split(",")[0]
    return re.sub(r"[^a-z0-9]", "", first.lower())


def _days_since(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return (datetime.now() - datetime.strptime(date_str.strip(), fmt)).days
        except ValueError:
            continue
    return None


def score_lead(r, repeat_count=1):
    """r is a joined row (lead_events + contacts + properties). Returns
    (score:int, factors:list[(label, points)]). repeat_count from the caller."""
    w = WEIGHTS
    factors = []
    score = 0.0

    match = (r["ownership_match"] or "").upper()
    if match == "CONFIRMED":
        score += w["confirmed"]; factors.append(("Confirmed owner", w["confirmed"]))
    elif match == "LIKELY":
        score += w["likely"]; factors.append(("Likely owner", w["likely"]))
    elif match == "MISMATCH":
        factors.append(("Lead is not the owner of record", 0))

    # Owner-occupancy: owner/tax mailing address matches the property street.
    prop = _norm_street(r["property_address"] or r["property_street"])
    mail = _norm_street(r["tax_address"]) or _norm_street(r["owner_address"])
    if prop and mail and prop == mail:
        score += w["owner_occupied"]; factors.append(("Owner-occupied", w["owner_occupied"]))

    tenure = _years_since(r["most_recent_sale_date"])
    if tenure is not None:
        pts = round(min(tenure / w["tenure_years_full"], 1.0) * w["tenure_max"])
        if pts:
            score += pts; factors.append((f"Owned ~{tenure:.0f} yrs", pts))

    if repeat_count > 1:
        score += w["repeat"]; factors.append((f"Asked {repeat_count}x", w["repeat"]))

    sale = _num(r["most_recent_sale_amount"])
    market = _num(r["market_total"])
    if sale and market and market > sale:
        gain = market - sale
        pts = round(min(gain / w["appreciation_full"], 1.0) * w["appreciation_max"])
        if pts:
            score += pts; factors.append((f"+${gain:,.0f} equity since sale", pts))

    days = _days_since(r["received_date"])
    if days is not None and days <= w["recent_days"]:
        score += w["recent"]; factors.append(("New lead (act fast)", w["recent"]))

    return int(round(score)), factors


_SQL = """
SELECT le.id, le.ownership_match, le.received_date, le.lead_type,
       le.match_confidence, le.contact_id, le.property_id,
       c.first_name, c.last_name, c.email, c.phone,
       p.photo_file, p.assessor_photo_file,
       p.property_address, p.property_street, p.property_city,
       p.most_recent_sale_date, p.most_recent_sale_amount, p.market_total,
       p.assessed_value, p.tax_address, p.owner_address
FROM lead_events le
JOIN contacts c   ON c.id = le.contact_id
JOIN properties p ON p.id = le.property_id
"""


def ranked_leads(conn):
    rows = conn.execute(_SQL).fetchall()
    repeats = {}
    for r in rows:
        k = (r["contact_id"], r["property_id"])
        repeats[k] = repeats.get(k, 0) + 1
    scored = []
    seen = set()
    for r in rows:
        key = (r["contact_id"], r["property_id"])
        if key in seen:          # collapse repeat-lead duplicates to one row
            continue
        seen.add(key)
        n = repeats[key]
        score, factors = score_lead(r, repeat_count=n)
        scored.append({"row": r, "score": score, "factors": factors})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


if __name__ == "__main__":
    import os
    conn = pdb.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    pdb.DEFAULT_DB_FILENAME))
    pdb.init_db(conn)
    ranked = ranked_leads(conn)
    print(f"{len(ranked)} leads scored. Top 12:\n")
    for s in ranked[:12]:
        r = s["row"]
        name = f"{r['first_name']} {r['last_name']}".strip()
        why = ", ".join(f"{lbl} (+{pts})" if pts else lbl for lbl, pts in s["factors"])
        print(f"  {s['score']:3}  {name:22} {(r['property_city'] or ''):14} | {why}")
