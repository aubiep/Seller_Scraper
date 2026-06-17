"""
iAuto Template Engine  v0.1.0
=============================
Merges lead/property data into a UUNA TEK iAuto JSON template, producing a new
template ready to POST to the machine's /write_template endpoint.

How iAuto templates work (verified against real exports, 2026-06-04):
  - A template is a JSON array of page objects; each page has an "items" array.
  - "text" items are baked-in static strings (body copy, signature). Left alone.
  - "sheet" items are the merge fields. The cell they fill is
    item["mapList"][0]["excelStart"] (e.g. "B1"). The value lives in BOTH
    item["data"][0][0] AND item["allData"][0][0]. We set both; setting only one
    can leave stale text in the rendered output.

This module is data-source agnostic: hand it a flat dict of values and a
field map (cell -> "{placeholder}" string). The dashboard builds that dict from
a propintel.db row; the diagnostic builds it from a sample. Missing placeholders
render blank rather than raising, so a sparse lead never crashes a send.

CLI:
    python iauto_template_v0_1_0.py --cells Iauto/HV_Letter1_2182026_Final.json
    python iauto_template_v0_1_0.py --selftest
"""

import copy
import json
import string


class _SafeDict(dict):
    """Missing keys render as empty string instead of raising KeyError."""
    def __missing__(self, key):
        return ""


def _fill(template_str, values):
    """Fill a '{placeholder}' string from values; unknown fields -> ''."""
    safe = _SafeDict({k: ("" if v is None else str(v)) for k, v in values.items()})
    try:
        return string.Formatter().vformat(template_str, (), safe)
    except (ValueError, IndexError):
        # Malformed brace in a field string: return it literally rather than crash.
        return template_str


def load_template(path):
    """Load a template JSON file as a Python object (list of pages)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pages(template):
    return template if isinstance(template, list) else [template]


def list_merge_cells(template):
    """Return the merge cells in a template: [{page,item,cell,current}, ...]."""
    out = []
    for pi, page in enumerate(_pages(template)):
        for ii, item in enumerate(page.get("items", [])):
            if item.get("type") != "sheet":
                continue
            ml = item.get("mapList") or []
            cell = ml[0].get("excelStart") if ml else None
            try:
                current = item["data"][0][0]
            except (KeyError, IndexError, TypeError):
                current = None
            out.append({"page": pi, "item": ii, "cell": cell, "current": current})
    return out


def _set_grid(item, key, value):
    """Set item[key][0][0] = value, building the grid if shape is unexpected."""
    grid = item.get(key)
    if isinstance(grid, list) and grid and isinstance(grid[0], list) and grid[0]:
        grid[0][0] = value
    else:
        item[key] = [[value]]


def merge(template, field_map, values):
    """
    Return (merged_template, applied) where merged_template is a deep copy with
    every mapped cell filled, and applied is a list of dicts describing each
    change: {cell, old, new}. Cells in field_map not found in the template are
    reported in `missing`; sheet cells in the template with no field_map entry
    are left at their baked-in value.
    """
    out = copy.deepcopy(template)
    applied = []
    seen_cells = set()
    for page in _pages(out):
        for item in page.get("items", []):
            if item.get("type") != "sheet":
                continue
            ml = item.get("mapList") or []
            cell = ml[0].get("excelStart") if ml else None
            if cell not in field_map:
                continue
            new_val = _fill(field_map[cell], values)
            try:
                old_val = item["data"][0][0]
            except (KeyError, IndexError, TypeError):
                old_val = None
            _set_grid(item, "data", new_val)
            _set_grid(item, "allData", new_val)
            applied.append({"cell": cell, "old": old_val, "new": new_val})
            seen_cells.add(cell)
    missing = [c for c in field_map if c not in seen_cells]
    return out, {"applied": applied, "missing": missing}


def to_bytes(template):
    """Serialize a merged template for the multipart POST (UTF-8 JSON)."""
    return json.dumps(template, ensure_ascii=False).encode("utf-8")


def merge_to_bytes(path, field_map, values):
    """Convenience: load -> merge -> bytes. Returns (bytes, report)."""
    tmpl = load_template(path)
    merged, report = merge(tmpl, field_map, values)
    return to_bytes(merged), report


# ── CLI / self-test ──────────────────────────────────────────────────────────

def _cmd_cells(path):
    tmpl = load_template(path)
    cells = list_merge_cells(tmpl)
    print(f"{path}: {len(cells)} merge cell(s)")
    for c in cells:
        print(f"  page{c['page']} item{c['item']}  {c['cell']:>4}  current={c['current']!r}")


def _selftest():
    """Round-trip the real letter template with sample data, no machine needed."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "Iauto", "HV_Letter1_2182026_Final.json")
    field_map = {
        "B1": "Hi {first_name},",
        "D1": "{property_address}",
        "N1": "Scan for quick, {property_city} market update. ",
    }
    values = {
        "first_name": "Jordan",
        "property_address": "13533 Boulder Ridge Rd",
        "property_city": "Snohomish",
    }
    merged, report = merge(load_template(path), field_map, values)
    print("APPLIED:")
    for a in report["applied"]:
        print(f"  {a['cell']}: {a['old']!r} -> {a['new']!r}")
    if report["missing"]:
        print("MISSING (in field_map, not in template):", report["missing"])
    # Verify both grids were updated for every applied cell.
    ok = True
    for page in _pages(merged):
        for item in page.get("items", []):
            if item.get("type") != "sheet":
                continue
            cell = (item.get("mapList") or [{}])[0].get("excelStart")
            if cell in field_map:
                d = item["data"][0][0]
                a = item["allData"][0][0]
                if d != a:
                    ok = False
                    print(f"  MISMATCH {cell}: data={d!r} allData={a!r}")
    print("\ndata/allData consistent:", ok)
    assert report["applied"], "no cells applied"
    assert ok, "data and allData diverged"
    print("SELFTEST PASS")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "--cells" and len(args) > 1:
        _cmd_cells(args[1])
    elif args and args[0] == "--selftest":
        _selftest()
    else:
        print(__doc__.strip().splitlines()[0])
        print("Usage:")
        print("  python iauto_template_v0_1_0.py --cells <template.json>")
        print("  python iauto_template_v0_1_0.py --selftest")
