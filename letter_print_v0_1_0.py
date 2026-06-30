"""
Printed seller letters - the typed half of the print + iAuto hybrid (Part 1).

This renders a print-ready HTML letter for one lead: the typed body with the
lead's name/address merged in, a generic letterhead/footer, and a reserved blank
zone near the sign-off where the iAuto will later pen a short handwritten note
plus the signature (Part 2). You open it in a browser and Print.

Kept deliberately separate from the iAuto send path (iauto_send) so the print
side can evolve and fail on its own without touching the proven machine path. It
reuses iauto_send.build_lead_values so a printed letter and an iAuto letter fill
from the exact same variables.

Templates live in config/letter_templates.json (seeded with the Soft Master on
first use). The body is HTML with {placeholders}; merging is a literal token
replace (values HTML-escaped), so CSS braces in the page chrome are never touched.

  python letter_print_v0_1_0.py --preview     # write a sample letter to a temp file
"""
import html
import json
import os
from datetime import datetime

import iauto_send_v0_1_0 as iautosend

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config", "letter_templates.json")

# The locked Soft Master body (from Aubie's "Best Overall"). HTML paragraphs;
# {first_name} and {property_address} are the only merge fields, by design.
_SOFT_MASTER_BODY = (
    "<p>Hi {first_name},</p>"
    "<p>I noticed you recently took a look at the value of your home at "
    "{property_address}, and I wanted to send a quick note your way.</p>"
    "<p>I'm not sure if the automated value answered what you were hoping to "
    "understand.</p>"
    "<p>For some homeowners, that number is enough. For others, it leaves gaps, "
    "especially when condition, improvements, layout, land, privacy, or market "
    "timing come into play.</p>"
    "<p>I also don't want to assume that checking your value means you're planning "
    "to sell. A lot of people are simply curious, keeping an eye on their equity, "
    "or beginning to think through future possibilities.</p>"
    "<p>If there is a bigger question behind it, such as what your home might "
    "realistically sell for, how much equity you may have, or whether certain "
    "improvements are worth making, I'd be happy to help you get a clearer "
    "picture.</p>"
)

_DEFAULT_CONFIG = {
    "_about": (
        "Printed seller letters for the print + iAuto handwriting hybrid. Each "
        "template's 'body' is HTML with {placeholders} filled from the lead record "
        "(same variables as the iAuto templates). The handwritten note + signature "
        "are added by the iAuto in the reserved zone, not printed here."
    ),
    # Generic brand block - swap in the real logo/contact/QR later, no rebuild.
    "brand": {
        "team": "JUSTLISTED Northwest Team",
        "agent": "Aubie Pouncey",
        "title": "Broker | Keller Williams PNW",
        "footer": "Aubie Pouncey  ·  Keller Williams PNW  ·  206-229-3737  ·  Aubie@KW.com",
    },
    "templates": {
        "soft_master": {
            "label": "Soft Master",
            "closing": "Warmly,",
            "body": _SOFT_MASTER_BODY,
        }
    },
}


def load_templates():
    """Whole letter-templates config, seeding the default file on first use."""
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        save_templates(_DEFAULT_CONFIG)
        return json.loads(json.dumps(_DEFAULT_CONFIG))
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_templates(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def merge_text(text, values):
    """Replace each {token} with its (HTML-escaped) value. Unknown tokens are
    left literal so a typo is visible rather than silently dropped."""
    for k, v in values.items():
        text = text.replace("{" + k + "}", html.escape(v))
    return text


def _today_str(d=None):
    d = d or datetime.now()
    return f"{d.strftime('%B')} {d.day}, {d.year}"


_PAGE_CSS = """
  *{box-sizing:border-box}
  body{margin:0;background:#525659;font-family:Georgia,'Times New Roman',serif;color:#111}
  .bar{position:sticky;top:0;background:#1d242c;padding:10px 16px;display:flex;gap:10px;
    align-items:center;font-family:Arial,Helvetica,sans-serif}
  .bar button{background:#3b82f6;color:#fff;border:none;padding:8px 18px;border-radius:8px;
    font-weight:600;cursor:pointer;font-size:14px}
  .bar .hint{color:#aab3bd;font-size:13px}
  .sheet{background:#fff;width:8.5in;min-height:11in;margin:18px auto;padding:0.9in 1in;
    box-shadow:0 2px 14px rgba(0,0,0,.4)}
  .lh{display:flex;justify-content:space-between;align-items:flex-start;
    border-bottom:2px solid #111;padding-bottom:12px;margin-bottom:6px}
  .logo{font-family:Arial,Helvetica,sans-serif;font-weight:800;letter-spacing:1px;font-size:22px}
  .logo .team{display:block;font-weight:600;letter-spacing:2px;font-size:10px;color:#555;margin-top:2px}
  .logobox{border:1px dashed #aaa;color:#aaa;font-family:Arial,sans-serif;font-size:11px;
    padding:14px 18px;border-radius:4px}
  .date{font-size:14px;color:#333;margin-top:4px}
  .body{font-size:15px;line-height:1.55;margin-top:26px}
  .body p{margin:0 0 13px}
  .closing{font-size:15px;margin-top:8px}
  .penzone{margin:6px 0 2px;min-height:1.25in;position:relative}
  .penlabel{font-family:Arial,sans-serif;font-size:11px;color:#b06;border:1px dashed #d9a;
    border-radius:6px;padding:6px 10px;display:inline-block;background:#fdf3f8}
  .sig{font-size:15px;font-weight:700;margin-top:4px}
  .sigtitle{font-size:13px;color:#444}
  .foot{margin-top:40px;border-top:1px solid #ccc;padding-top:10px;display:flex;
    justify-content:space-between;align-items:center;font-family:Arial,sans-serif;
    font-size:11px;color:#444}
  .qr{display:flex;gap:8px}
  .qr span{width:44px;height:44px;border:1px dashed #bbb;color:#bbb;font-size:9px;
    display:flex;align-items:center;justify-content:center;text-align:center}
  @media print{
    .no-print{display:none!important}
    body{background:#fff}
    .sheet{box-shadow:none;margin:0;width:auto;min-height:auto;padding:0}
    @page{margin:0.7in}
  }
"""


def render_letter(template_key, values, cfg=None):
    """Return (html, error). html is a standalone print-ready page; error is set
    (and html None) if the template key is unknown."""
    cfg = cfg or load_templates()
    tmpl = (cfg.get("templates") or {}).get(template_key)
    if not tmpl:
        return None, f"unknown letter template '{template_key}'"
    brand = cfg.get("brand", {})
    body = merge_text(tmpl.get("body", ""), values)
    closing = html.escape(tmpl.get("closing", "Warmly,"))
    agent = html.escape(brand.get("agent", "Aubie Pouncey"))
    title = html.escape(brand.get("title", ""))
    team = html.escape(brand.get("team", ""))
    footer = html.escape(brand.get("footer", ""))
    label = html.escape(tmpl.get("label", template_key))

    page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Letter - {label}</title><style>{_PAGE_CSS}</style></head><body>
<div class="bar no-print">
  <button onclick="window.print()">Print this letter</button>
  <span class="hint">Generic layout. The handwritten note + signature are added by the iAuto, not printed here.</span>
</div>
<div class="sheet">
  <div class="lh">
    <div class="logo">JUSTLISTED<span class="team">{team}</span></div>
    <div class="date">{_today_str()}</div>
  </div>
  <div class="body">{body}</div>
  <div class="closing">{closing}</div>
  <div class="penzone">
    <span class="penlabel no-print">iAuto pens the handwritten note + &ldquo;Aubie&rdquo; signature here</span>
  </div>
  <div class="sig">{agent}</div>
  <div class="sigtitle">{title}</div>
  <div class="foot">
    <div>{footer}</div>
    <div class="qr"><span>QR</span><span>QR</span><span>QR</span></div>
  </div>
</div>
</body></html>"""
    return page, None


if __name__ == "__main__":
    import sys
    if "--preview" in sys.argv:
        sample = {"first_name": "Kim", "property_address": "18625 71st Ave W"}
        out, err = render_letter("soft_master", sample)
        if err:
            print("error:", err); sys.exit(1)
        path = os.path.join(HERE, "_letter_preview.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        print("wrote", path)
    else:
        print("Usage: python letter_print_v0_1_0.py --preview")
