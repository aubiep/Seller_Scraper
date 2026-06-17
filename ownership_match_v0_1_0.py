"""
Ownership Reasoning  v0.1.0
===========================
Investigative matching between a seller lead and the assessor's owner of record.

The old check compared last names and called it CONFIRMED / PARTIAL / MISMATCH.
Real lead work needs more judgment: the lead may be the owner's spouse, may have
married into or out of the name, may be an adult child or heir of a deceased
owner, may go by a nickname (Bob/Robert), or the home may be held by the family
trust or an LLC. This module reasons about those cases and returns a status,
a 0-100 confidence, a relationship hypothesis, and a human-readable reason.

It is deterministic and dependency-free. Genuinely ambiguous cases are returned
as REVIEW with the reasoning spelled out, which is the natural hook for a later
LLM adjudication pass (see analyze_ownership's docstring).

Status vocabulary:
    CONFIRMED - high confidence the lead is the owner (self or nickname match)
    LIKELY    - strong circumstantial match (spouse, hyphenated/maiden name,
                surname inside the holding trust/LLC)
    REVIEW    - plausible but unconfirmed; a human should glance
    MISMATCH  - name does not line up; property may have sold or lead isn't owner
    NO_LEAD   - no lead name to compare

Public API:
    analyze_ownership(lead_first, lead_last, owners) -> dict
    where owners is a list of {"first":..., "last":...} (owner 1, owner 2).
"""

import re

# ── Nickname / given-name variants ──────────────────────────────────────────
# Each set is a family of interchangeable first names. Membership is symmetric.
_NICKNAME_GROUPS = [
    {"robert", "rob", "bob", "bobby", "robbie", "bert"},
    {"william", "will", "bill", "billy", "willie", "liam"},
    {"richard", "rick", "ricky", "dick", "rich", "richie"},
    {"john", "jon", "johnny", "jack", "jackie"},
    {"james", "jim", "jimmy", "jamie", "jimbo"},
    {"michael", "mike", "mikey", "mickey", "mick"},
    {"charles", "charlie", "chuck", "chip", "chas"},
    {"joseph", "joe", "joey"},
    {"thomas", "tom", "tommy"},
    {"daniel", "dan", "danny"},
    {"david", "dave", "davy"},
    {"edward", "ed", "eddie", "ted", "ned", "ned"},
    {"anthony", "tony"},
    {"christopher", "chris", "topher"},
    {"matthew", "matt", "matty"},
    {"nicholas", "nick", "nicky"},
    {"andrew", "andy", "drew"},
    {"steven", "stephen", "steve", "stevie"},
    {"kenneth", "ken", "kenny"},
    {"donald", "don", "donnie"},
    {"ronald", "ron", "ronnie", "ronny"},
    {"gerald", "gerry", "jerry"},
    {"lawrence", "larry", "lars"},
    {"frederick", "fred", "freddie", "freddy"},
    {"raymond", "ray"},
    {"eugene", "gene"},
    {"samuel", "sam", "sammy"},
    {"benjamin", "ben", "benji", "benny"},
    {"alexander", "alex", "al", "xander"},
    {"timothy", "tim", "timmy"},
    {"jeffrey", "jeff", "geoff"},
    {"gregory", "greg"},
    {"douglas", "doug"},
    {"patrick", "pat", "paddy"},
    {"peter", "pete"},
    {"walter", "walt", "wally"},
    {"henry", "hank", "harry"},
    {"albert", "al", "bert", "albie"},
    {"vincent", "vince", "vinny"},
    {"elizabeth", "liz", "beth", "betty", "eliza", "libby", "lizzie", "betsy"},
    {"margaret", "maggie", "meg", "peggy", "marge", "margie"},
    {"katherine", "catherine", "kate", "katie", "kathy", "cathy", "kat", "kit"},
    {"patricia", "pat", "patty", "trish", "tricia"},
    {"jennifer", "jen", "jenny", "jenna"},
    {"susan", "sue", "susie", "suzy"},
    {"deborah", "debra", "deb", "debbie"},
    {"barbara", "barb", "babs"},
    {"cynthia", "cindy", "cyndi"},
    {"rebecca", "becky", "becca"},
    {"pamela", "pam"},
    {"sandra", "sandy"},
    {"virginia", "ginny", "ginger"},
    {"victoria", "vicky", "vic", "tori"},
    {"christine", "christina", "chris", "chrissy", "tina"},
    {"jacqueline", "jackie", "jacqui"},
    {"theresa", "teresa", "terry", "tess", "tracy"},
    {"dorothy", "dot", "dottie"},
    {"nancy", "nan"},
    {"diane", "diana", "di"},
    {"kimberly", "kim"},
    {"angela", "angie"},
    {"danielle", "dani", "danni"},
    {"stephanie", "steph"},
    {"michelle", "shelly", "mich"},
    {"melissa", "missy", "mel"},
    {"amanda", "mandy"},
]
_VARIANT = {}
for _g in _NICKNAME_GROUPS:
    for _n in _g:
        _VARIANT.setdefault(_n, set()).update(_g)

# ── Entity / non-person owner keywords ──────────────────────────────────────
_ENTITY_WORDS = {
    "TRUST", "TRUSTEE", "TRUSTEES", "TRU", "TR", "LIVING", "REVOCABLE",
    "IRREVOCABLE", "FAMILY", "ESTATE", "ESTATES", "LLC", "LLP", "LP", "INC",
    "CORP", "CORPORATION", "COMPANY", "PROPERTIES", "PROPERTY", "HOLDINGS",
    "PARTNERS", "PARTNERSHIP", "FOUNDATION", "ASSOC", "ASSOCIATION", "BANK",
    "HOMES", "ENTERPRISES", "INVESTMENTS", "INVESTMENT", "GROUP", "FUND",
    "VENTURES", "REALTY", "DEVELOPMENT", "ET", "AL",
}


def _norm(s):
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    if not s:
        return ""
    s = re.sub(r"[^A-Za-z\s-]", " ", s)
    return " ".join(s.lower().split())


def _tokens(s):
    return [t for t in re.split(r"[\s-]+", _norm(s)) if t]


def _surname_core(s):
    """Surname tokens with single-letter initials dropped (so 'B Guzman' -> ['guzman']
    and 'Guzman Guzman' -> ['guzman','guzman'])."""
    return [t for t in _tokens(s) if len(t) > 1]


def surname_match(a, b):
    """True if two surnames refer to the same family, tolerant of middle
    initials packed into the lead name and of compound/double surnames. Matches
    on exact equality, equal core-token lists, or a shared final surname token
    (handles 'B Guzman' vs 'Guzman' and 'Guzman Guzman' vs 'Guzman')."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    ca, cb = _surname_core(a), _surname_core(b)
    if ca and cb and (ca == cb or ca[-1] == cb[-1]):
        return True
    return False


def first_name_match(a, b):
    """Return ('exact'|'nickname'|'prefix'|None) describing how two first names
    relate. Handles Bob/Robert via the nickname table and Ed/Edward via prefix."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return None
    if a == b:
        return "exact"
    if b in _VARIANT.get(a, ()):  # symmetric table
        return "nickname"
    # prefix (Ed/Edward, Cathy/Catherine-ish) - require >=3 chars to avoid noise
    short, lng = sorted((a, b), key=len)
    if len(short) >= 3 and lng.startswith(short):
        return "prefix"
    return None


def _is_entity(owners):
    """If any owner name carries an entity keyword, return the keyword, else ''."""
    for o in owners:
        for tok in _tokens(o.get("first", "")) + _tokens(o.get("last", "")):
            if tok.upper() in _ENTITY_WORDS:
                return tok.upper()
    return ""


def _result(status, confidence, relationship, reason):
    return {"status": status, "confidence": int(confidence),
            "relationship": relationship, "reason": reason}


def analyze_ownership(lead_first, lead_last, owners):
    """Reason about whether a lead is the owner of record.

    lead_first/lead_last: the lead's name.
    owners: list of {"first","last"} for owner 1 and owner 2 (blanks allowed).

    Returns {status, confidence, relationship, reason}. The richest hypothesis
    across both owners (and the entity check) wins. A future LLM pass can take
    any REVIEW result plus the raw names and adjudicate; the deterministic layer
    deliberately errs toward REVIEW rather than guessing CONFIRMED.
    """
    lf, ll = _norm(lead_first), _norm(lead_last)
    if not lf and not ll:
        return _result("NO_LEAD", 0, "none", "No lead name to compare.")

    owners = [o for o in owners if _norm(o.get("first")) or _norm(o.get("last"))]
    owner_label = ", ".join(
        " ".join(x for x in (o.get("first", ""), o.get("last", "")) if x).strip()
        for o in owners) or "(no owner on record)"

    candidates = []  # (score, status, relationship, reason)

    for o in owners:
        of, ol = _norm(o.get("first")), _norm(o.get("last"))
        fnm = first_name_match(lf, of)

        if ll and ol and surname_match(ll, ol):
            # Same surname (tolerant of middle initials and compound surnames).
            if fnm in ("exact", "nickname", "prefix"):
                how = {"exact": "exact name match",
                       "nickname": f"nickname match ({lead_first} = {o.get('first')})",
                       "prefix": f"name match ({lead_first} / {o.get('first')})"}[fnm]
                candidates.append((96, "CONFIRMED", "self",
                                   f"Lead is the owner of record - {how}."))
            elif not of:
                candidates.append((68, "REVIEW", "unknown",
                                   f"Surname '{lead_last}' matches; owner's first "
                                   f"name not on record - confirm it's the same person."))
            else:
                candidates.append((74, "LIKELY", "spouse_or_relative",
                                   f"Same surname '{lead_last}', different first name "
                                   f"({lead_first} vs {o.get('first')}) - likely a "
                                   f"spouse, sibling, parent, or adult child of the owner."))
        elif ll and ol:
            # Different surname.
            if fnm in ("exact", "nickname"):
                candidates.append((50, "REVIEW", "name_change_or_coincidence",
                                   f"Same first name, different surname "
                                   f"({lead_last} vs {o.get('last')}) - possible "
                                   f"marriage/name change, or a coincidence. Verify."))
            # lead surname embedded in a (likely hyphenated) owner surname
            if ll in _tokens(o.get("last", "")) and ll != ol:
                candidates.append((64, "LIKELY", "marriage_or_relative",
                                   f"Lead surname '{lead_last}' appears within owner "
                                   f"surname '{o.get('last')}' - likely a hyphenated "
                                   f"married name or a family relationship."))
            if ol in _tokens(lead_last) and ll != ol:
                candidates.append((58, "REVIEW", "marriage_or_relative",
                                   f"Owner surname '{o.get('last')}' appears within the "
                                   f"lead's surname '{lead_last}' - possible married name."))

    # Entity / trust / LLC holding title.
    ent = _is_entity(owners)
    if ent:
        owner_tokens = set()
        for o in owners:
            owner_tokens |= set(_tokens(o.get("first", ""))) | set(_tokens(o.get("last", "")))
        if ll and ll in owner_tokens:
            candidates.append((66, "LIKELY", "entity",
                               f"Property is held by an entity ({ent}); the lead's "
                               f"surname '{lead_last}' appears in the entity name "
                               f"'{owner_label}' - very likely the lead's own "
                               f"trust/LLC."))
        else:
            candidates.append((30, "REVIEW", "entity",
                               f"Property is held by an entity ({ent}: '{owner_label}'); "
                               f"the lead's name does not obviously appear in it - "
                               f"confirm the connection manually."))

    if not candidates:
        return _result("MISMATCH", 18, "unrelated",
                       f"Lead '{(lead_first + ' ' + lead_last).strip()}' does not match "
                       f"the owner of record ({owner_label}). The property may have "
                       f"sold, or the lead is not the owner.")

    candidates.sort(key=lambda c: c[0], reverse=True)
    score, status, rel, reason = candidates[0]
    return _result(status, score, rel, reason)


# ── Back-compat helper: collapse the rich status to the legacy 4-value set ───
def legacy_status(result):
    """Map the rich status to the old CONFIRMED/PARTIAL/MISMATCH/NO LEAD DATA
    vocabulary, for anything still expecting it."""
    return {
        "CONFIRMED": "CONFIRMED", "LIKELY": "PARTIAL", "REVIEW": "PARTIAL",
        "MISMATCH": "MISMATCH", "NO_LEAD": "NO LEAD DATA",
    }.get(result["status"], "PARTIAL")


def needs_review(result):
    """True when a human should look. Everything but a clean CONFIRMED."""
    return result["status"] != "CONFIRMED"


# ── Self-test / demo ────────────────────────────────────────────────────────
if __name__ == "__main__":
    CASES = [
        # (lead_first, lead_last, owners, note)
        ("Aubie", "Pouncey", [{"first": "Aubie", "last": "Pouncey"},
                              {"first": "Karen", "last": "Pouncey"}], "self"),
        ("Ron", "Potter", [{"first": "Ronald", "last": "Potter"},
                           {"first": "Davina", "last": "Potter"}], "nickname"),
        ("Danielle", "Hottendorf", [{"first": "Brett", "last": "Hottendorf"}], "spouse"),
        ("Charles", "Krahl", [{"first": "Revocable Tru", "last": "Rohling-Krahl"}], "trust w/ surname"),
        ("Larry", "Newton", [{"first": "Gary", "last": "Leischner"},
                             {"first": "Barbara", "last": "Leischner"}], "sold/unrelated"),
        ("Jennifer", "Smith", [{"first": "Jennifer", "last": "Jones"}], "married name?"),
        ("Mike", "Anderson", [{"first": "Michael", "last": "Anderson"}], "nickname"),
        ("Sarah", "Lee", [{"first": "ABC", "last": "Properties LLC"}], "LLC, no surname"),
    ]
    for lf, ll, owners, note in CASES:
        r = analyze_ownership(lf, ll, owners)
        print(f"{lf+' '+ll:22s} [{note:18s}] -> {r['status']:9s} "
              f"({r['confidence']:>3}) {r['relationship']}")
        print(f"      {r['reason']}")
    print("\nself-test complete")
