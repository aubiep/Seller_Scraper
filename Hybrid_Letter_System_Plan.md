# Hybrid Letter System - Plan

Status: design locked, not yet built. This is the blueprint for the printed +
handwritten seller letter feature inside the PropIntel dashboard.

---

## How it works, physically

One sheet of letterhead, two passes:

1. **Print pass (your printer).** The full typed letter: letterhead, the body
   with the lead's name and address merged in, your typed signature block, the
   footer, and the QR codes. A blank zone is reserved near the sign-off.
2. **Pen pass (iAuto).** The machine writes ONE short handwritten line (chosen
   from your note bank, with the lead's first name) plus your "Aubie" signature,
   into that reserved zone.

Result: ~90% polished type, ~10% real pen, exactly the blend in your example.

Efficient workflow is batch, not one-at-a-time: print the whole stack, then run
the whole stack through the iAuto.

---

## A hybrid template has three linked parts

1. **Printed body** - an HTML letter with `{placeholders}` (`{first_name}`,
   `{property_address}`, etc.). Opens in your browser; you hit Print.
2. **iAuto insert** - a small pen template positioned to land in the reserved
   zone: the chosen note line + your signature. You design this once on the iAuto.
3. **Note bank** - your ~20 rotating handwritten lines (shared across templates).

The printed body's reserved zone and the iAuto insert's position must line up.
That is a one-time calibration (print one, run it, nudge the pen position once).

---

## Locked Soft Master (typed body)

From your "Best Overall Version to Actually Use." Merge fields: `{first_name}`,
`{property_address}`. No hard numbers, by design, to protect the soft tone.

> Hi {first_name},
>
> I noticed you recently took a look at the value of your home at
> {property_address}, and I wanted to send a quick note your way.
>
> I'm not sure if the automated value answered what you were hoping to understand.
>
> For some homeowners, that number is enough. For others, it leaves gaps,
> especially when condition, improvements, layout, land, privacy, or market
> timing come into play.
>
> I also don't want to assume that checking your value means you're planning to
> sell. A lot of people are simply curious, keeping an eye on their equity, or
> beginning to think through future possibilities.
>
> If there is a bigger question behind it, such as what your home might
> realistically sell for, how much equity you may have, or whether certain
> improvements are worth making, I'd be happy to help you get a clearer picture.
>
> Warmly,
> Aubie

**Handwritten zone** (penned by iAuto, default line):
> {first_name}, I'd be happy to be a resource whenever the timing feels right.
> No pressure at all.

---

## Note bank (your 20 lines)

`{first_name}` is filled per lead. One line is used per letter; the rest rotate.

Soft / Ari-style:
1. {first_name}, no pressure at all. I just wanted to personally reach out.
2. Happy to be a resource whenever the timing feels right.
3. If there's ever a bigger question behind it, I'd be glad to help.
4. No need to respond unless it would be helpful.
5. Even if you're only curious, that's completely fine too.
6. Sometimes it just helps to talk it through.
7. I don't want to assume anything, just wanted to make myself available.
8. If the online value felt off, you're not alone. They often miss a lot.

More personal:
9. {first_name}, I know timing is everything with these decisions.
10. Just wanted to make sure you had a real person to reach out to if needed.
11. I'd be glad to help you get a clearer picture whenever useful.
12. If this is something you're only starting to think about, that's perfectly okay.
13. I'm happy to be a sounding board if you ever want to talk it through.
14. No rush at all. These decisions usually unfold over time.

More direct but still warm:
15. If helpful, I can give you a more accurate opinion than the online estimate.
16. I'd be happy to put together a clearer value range for you.
17. If you want to know what your home could realistically sell for, I can help.
18. A quick 15-minute conversation would probably give you a much clearer picture.
19. I can also help you understand which improvements are worth doing and which are not.
20. If selling is even a small possibility, it may be worth getting better information.

---

## Rotation behavior

- **Auto-rotate** across a batch so consecutive letters differ (no two stacked
  letters share the same handwritten line).
- **Override** with a dropdown when you want to pick the line for a specific lead.

---

## Dashboard flow

Single lead:
1. On a lead, click **Generate letter**.
2. A print-ready page opens in a new tab, merges filled, a handwritten line chosen.
3. You print it.
4. Click **Queue handwritten pass** to send the pen insert for that lead to the iAuto.

Batch:
1. Filter a list (reuse the existing bulk-mail filters).
2. **Generate batch** produces one multi-page print document (all letters) plus a
   matching queue of iAuto inserts in the same order, so the stacks stay in sync.

---

## Where things live (data model)

- New `letter_templates.json` (mirrors `iauto_templates.json`): each template has a
  name, the HTML body, a reference to the shared note bank, and the linked iAuto
  insert (its design file + the cell that holds the note line).
- Shared `note_bank` (the 20 lines), reusable across templates.
- Merges reuse `iauto_send.build_lead_values` (the same variables as the iAuto
  letters, including the new equity/tenure/value fields for the Equity Review
  template later).

---

## Template set

1. **Soft Master** - the workhorse. Name + address only. Build first.
2. **Equity Review** - uses `{equity_estimate}`, `{years_owned}`, `{market_value}`.
   Only for enriched leads with assessor data (a subset). Build second.
3. **Warm Reconnect** - for past contacts, no valuation framing. Later.

---

## Build order

1. **Print foundation + Soft Master, single lead.** Print template module, the
   Soft Master HTML, the print-ready page with merges. Deliver: print one real
   letter for one lead.
2. **Note bank + pen pass, single lead end to end.** Rotation, the iAuto insert
   send. Deliver: one full hybrid letter (print + pen) for one lead. One-time
   alignment calibration here.
3. **Batch.** Multi-page print doc + synced iAuto queue.
4. **Equity Review template.** Reuses everything above.

Per-recipient trackable QR codes (idea #2) layer on after the hybrid works.
