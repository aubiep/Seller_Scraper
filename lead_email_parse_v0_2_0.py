"""
Lead Email Parser  v0.2.0
=========================
Rule-based parser for lead-notification emails, used by the unattended local
watcher (which can't use Claude as the parser). Handles the three sources Aubie
actually receives, verified against real emails 2026-06-06:

  - Zurple   (no-reply@zurple.com): data in the HTML body, label-then-value
             layout. "Homeowner Asked for a CMA" carries the property address;
             "No Matching Address" / "New Signup" do not. Has email + phone.
  - Brivity  (messages@/leads@brivity.com): clean text body, "Label: value" on
             one line. "Congratulations new lead" carries the address; buyer
             "registered on your site" does not. Has email + phone. Sometimes a
             free-text lead message. Addresses have NO commas.
  - Market   Leader (noreply@marketleader.com): "New HouseValues Contact" has
             NAME + ADDRESS only (NO email/phone - those are behind the CRM).

parse_lead_email(subject, plaintext, html="", sender="") -> dict:
    source, name, first_name, last_name, email, phone, property_address,
    lead_type, message, has_address

The downstream scraper handles WA address cleaning (comma and no-comma), so we
keep property_address as the raw string the email gave us.
"""

import html as _html
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")


def _lines(text):
    if not text:
        return []
    if "<" in text and ">" in text:
        text = re.sub(r"<[^>]+>", "\n", text)
    text = _html.unescape(text)
    out = []
    for line in text.splitlines():
        s = line.replace("*", " ")  # markdown bold markers (Brivity/ML) -> space
        s = re.sub(r"[ \t\xa0]+", " ", s).strip()
        if s and s != "-->":
            out.append(s)
    return out


def _split_name(name):
    toks = [t for t in name.replace(",", " ").split() if t]
    if not toks:
        return "", ""
    if len(toks) == 1:
        return toks[0], ""
    return toks[0], toks[1]


def detect_source(sender, subject, body):
    blob = f"{sender} {subject} {body}".lower()
    if "zurple" in blob:
        return "Zurple"
    if "brivity" in blob:
        return "Brivity"
    if "marketleader" in blob or "housevalues" in blob or "house values" in blob:
        return "Market Leader"
    return "Unknown"


def _value_after_label(lines, label):
    """For 'label-then-value' layouts (Zurple): value is the next line."""
    for i, l in enumerate(lines):
        if l.rstrip(":").lower() == label.rstrip(":").lower() and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def _value_inline(lines, label):
    """For 'Label: value' layouts (Brivity, ML)."""
    pat = re.compile(rf"^{re.escape(label)}\s*:?\s*(.+)$", re.I)
    for l in lines:
        m = pat.match(l)
        if m:
            return m.group(1).strip()
    return ""


def parse_zurple(body, subject=""):
    lines = _lines(body)
    addr = _value_after_label(lines, "PROPERTY:")
    if addr and ("," not in addr or not re.search(r"\d", addr)):
        addr = ""  # "No Matching Address Found" leaves a non-address value
    name = ""
    for i, l in enumerate(lines):
        if l == "Lead Details":
            for nxt in lines[i + 1:i + 4]:
                if "@" not in nxt and not nxt.lower().startswith(("email", "phone", "view")):
                    name = nxt
                    break
            break
    if not name and " - " in subject:
        name = subject.rsplit(" - ", 1)[-1].strip()
    email = _value_after_label(lines, "Email:")
    phone = _value_after_label(lines, "Phone:")
    return _assemble("Zurple", name, email, phone, addr,
                     _value_after_label(lines, "Lead Status:"), "")


def parse_brivity(body, subject=""):
    lines = _lines(body)
    name = ""
    for i, l in enumerate(lines):
        if l.lower() == "lead information" and i + 1 < len(lines):
            name = lines[i + 1].strip()
            break
    email = _value_inline(lines, "Email")
    phone = _value_inline(lines, "Phone")
    addr = _value_inline(lines, "Address")
    lead_type = _value_inline(lines, "Lead Type")
    msg = ""
    for i, l in enumerate(lines):
        if "left a message" in l.lower():
            collected = []
            for nxt in lines[i + 1:]:
                if nxt.lower().startswith(("additional information", "source")):
                    break
                collected.append(nxt)
            msg = " ".join(collected).strip()
            break
    return _assemble("Brivity", name, email, phone, addr, lead_type, msg)


def parse_marketleader(body, subject=""):
    lines = _lines(body)
    # Name from subject: "New HouseValues Contact: <Name>" or "<Name> New Contact Registration"
    name = ""
    s = re.sub(r"^Fwd:\s*", "", subject, flags=re.I).strip()
    m = re.search(r"New HouseValues Contact:\s*(.+)$", s, re.I)
    if m:
        name = m.group(1).strip()
    else:
        m = re.match(r"(.+?)\s+New Contact Registration", s, re.I)
        if m:
            name = m.group(1).strip()
    if not name:
        for l in lines:
            m = re.match(r"(.+?)\s+requested a home value", l, re.I)
            if m:
                name = m.group(1).strip()
                break
    addr = _value_inline(lines, "Address")
    # ML emails do NOT expose the lead's email/phone (behind the CRM).
    return _assemble("Market Leader", name, "", "", addr, "", "")


def _assemble(source, name, email, phone, addr, lead_type, message):
    addr = (addr or "").strip()
    # tidy phone if it carried an extra <+1...> tail
    if phone:
        m = PHONE_RE.search(phone)
        phone = m.group(0).strip() if m else phone.strip()
    first, last = _split_name(name or "")
    return {
        "source": source, "name": name.strip(), "first_name": first, "last_name": last,
        "email": (email or "").strip(), "phone": (phone or "").strip(),
        "property_address": addr, "lead_type": (lead_type or "").strip(),
        "message": (message or "").strip(),
        "has_address": bool(addr and re.search(r"\d", addr)),
    }


def parse_lead_email(subject="", plaintext="", html="", sender=""):
    """Dispatch by source. Zurple data lives in HTML (its plaintext is empty);
    Brivity/Market Leader have clean plaintext. We pass the richer of the two."""
    body = plaintext if (plaintext and plaintext.strip()) else html
    src = detect_source(sender, subject, body or html)
    if src == "Zurple":
        return parse_zurple(html or body, subject)
    if src == "Brivity":
        return parse_brivity(body or html, subject)
    if src == "Market Leader":
        return parse_marketleader(body or html, subject)
    # Unknown source: best-effort generic extraction.
    lines = _lines(body or html)
    text = "\n".join(lines)
    email = (EMAIL_RE.search(text) or [None])[0] if EMAIL_RE.search(text) else ""
    email = EMAIL_RE.search(text).group(0) if EMAIL_RE.search(text) else ""
    phone = PHONE_RE.search(text).group(0) if PHONE_RE.search(text) else ""
    addr = _value_inline(lines, "Address") or _value_after_label(lines, "PROPERTY:")
    return _assemble(src, "", email, phone, addr, "", "")
