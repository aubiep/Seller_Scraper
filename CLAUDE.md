# PropIntel: Property Intelligence and Outreach Suite

Claude Code reads this file automatically at the start of every session in this
folder. It is the canonical orienting doc. It supersedes the older, stale
`Project_Downloads/CLAUDE.md` (which still describes a v2.5.3 / bulk-King-County
/ iAuto-deferred world that no longer exists).

Built by and for **Aubie Pouncey**, a real estate broker at Keller Williams PNW
covering King, Snohomish, Island, and Skagit counties.

> If you are a fresh Claude Code instance on a new machine: read the
> **"Running on a new workstation"** section at the bottom first.

---

## What this is

A local, single-user property toolkit that turns seller leads into verified,
enriched records and then drives outreach. The direction is **one unified local
app** (not a pile of scripts): leads land in a SQLite database, get their
ownership verified against county assessor data, and flow out to Homebot (the
Market Digest) and the iAuto handwriting machine (handwritten notes). A local
Flask dashboard ties it together.

Lead sources: Market Leader / HouseValues CRM (primary), plus others. No CRM has
a usable inbound API, so leads are pasted/exported, not pulled.

---

## How to work with Aubie

- **Lead with the answer.** No preamble, no restating the question.
- **Default under 150 words** unless the task needs depth (code, analysis, docs).
- **Yes/no questions get yes or no as the first word.**
- **"What do you recommend":** one honest pick first, brief reasoning, no option menus.
- **Counter-arguments and flagged assumptions only when they would change the decision.**
- **Mid-chat corrections apply to the rest of the session.**
- **Never use em dashes.** Periods, commas, or restructured sentences only.
- **Ask a clarifying question before doing work when scope is genuinely unclear.**
- **Aubie uses voice input**, so messages are stream-of-consciousness. Parse intent.
- **Proactive recommendations.** If there is a better way than what was asked, say so first.
- **Distinguish confirmed fact from assumption.** Flag what is verified vs guessed.
- **Outward-facing or hard-to-reverse actions get confirmed first** (live sends,
  enrolling real people, deleting files).

---

## Current live files (and how to run them)

All in this folder. Naming convention is locked: `{tool}_v{major}_{minor}_{patch}.py`,
underscores between version segments. Never reuse an old filename with new content;
delete superseded versions.

| File | What it does | Run |
|---|---|---|
| `snoco_scraper_v2_7_3.py` | Lead enrichment. Snohomish (live scrape) + **King County LIVE** (ArcGIS + Dashboard, no bulk files). Writes to propintel.db. **v2.7.3: King County condo/townhome leads no longer land UNENRICHED. The address resolves to the condo COMPLEX MASTER parcel (MINOR 0000, common area, no owner/value); the scraper now detects that, confirms condo via GIS land-use, walks the per-unit parcels (MAJOR-00X0), and matches the lead to their unit by surname (first-name disambiguation; absent/ambiguous match = left unenriched, never a wrong-unit guess). Recovered Dean Lester -> 729910-0090 and Michael Hoar -> 174990-0600.** v2.7.2: address-clean no longer truncates streets starting with a state-code prefix (Wagner/Callow Rd); detect_county handles 'City ST zip' (Duvall/Snoqualmie/Redmond route to King); initial search results street-filtered + city-disambiguated so it skips ambiguous matches instead of grabbing a wrong parcel. | `python snoco_scraper_v2_7_3.py Seller_Leads.txt` |
| `propintel_db_v0_1_0.py` | SQLite system of record (`propintel.db`): contacts, properties, lead_events, outreach. Schema + CLI + queries. **Schema v4 adds properties.last_lookup_at/status/detail (the stored outcome of a re-run assessor lookup).** | imported by the others; has a CLI |
| `propintel_app_v0_3_3.py` | **The dashboard.** Home = **daily command center** (new & unprocessed leads, follow-up due, priority worklist, review queue, status tiles). **Merged /leads** (Contacts+Leads in one repeat-aware page: "Nx" badge, filters, Add-contact form, per-row queue+enroll; /contacts redirects here). Priority worklist (/priority). Lead detail (/property/<id>) with photos + every submission. **v0.3.3: per-lead "Re-run assessor lookup" button (POST /lead/<cid>/<pid>/reenrich) + a "Last assessor lookup" panel showing what the assessor returned on a failure (owner found that didn't match / candidate condo units / no parcel).** iAuto letter queue (change template per queued row; inline Enroll-in-Homebot). **Bulk mail** (/letters/bulk: city/county/zip/neighborhood/lead-type/verdict/date + radius, arrange by score/distance, top-N, queue many). Homebot hub. **Edit-contact form** (/contact/<id>/edit) to fix name casing / add email-phone. | `python propintel_app_v0_3_3.py` then open http://127.0.0.1:5000 |
| `reenrich_v0_1_0.py` | **One-lead re-enrichment.** Re-runs the county assessor lookup for a single existing lead and upgrades its property **in place** on a match (real parcel + owner + value, verdict flipped, original lead date preserved - no duplicate rows); on a failure records what the assessor returned to `properties.last_lookup_*`. Backs the dashboard Re-run button. | imported by the dashboard |
| `geocode_v0_1_0.py` | **Geocoding.** Address -> lat/long for the bulk radius filter. Source order Google (rooftop, needs billing) -> US Census (free) -> Nominatim/OSM (free). Writes lat/long to propintel.db properties. | `python geocode_v0_1_0.py --backfill` / `--test "<address>"` |
| `lead_priority_v0_1_0.py` | Listing-likelihood scoring (0-100 + why) behind the /priority page. Tunable WEIGHTS at top. | imported by the dashboard; CLI prints top 12 |
| `ownership_match_v0_1_0.py` | Spouse/nickname/trust/heir ownership matching with confidence + reasons. | imported by the scraper |
| `kc_lookup_v1_2.py` | Standalone single-address King County lookup (legacy, bulk-file based). | `python kc_lookup_v1_2.py` |
| `homebot_api_v0_1_0.py` / `homebot_push_v0_1_0.py` / `homebot_diagnostic_v0_1_0.py` | Homebot Market Digest: API client, lead->enrollment push, auth/create diagnostic. | `python homebot_push_v0_1_0.py` (dry run) / `--live` |
| `iauto_api_v0_1_0.py` / `iauto_template_v0_1_0.py` / `iauto_send_v0_1_0.py` / `iauto_diagnostic_v0_1_0.py` | iAuto handwriting machine: API client, template merge engine, DB->send path, plumbing diagnostic. | `python iauto_diagnostic_v0_1_0.py` (with machine on) |
| `lead_email_parse_v0_2_0.py` / `lead_intake_v0_1_0.py` / `lead_watcher_v0_2_0.py` | **Email lead intake** (no copy-paste, no CRM click). **SELLER-ONLY**: watcher search targets Zurple CMA/home-value requests (buyers scrubbed; Market Leader/HouseValues comes from the .md instead). Zurple sellers are usually address-less, captured as NO ADDRESS / UNVERIFIED contacts (name+email+phone) for follow-up via `intake.ingest_addressless`. `--since YYYY/MM/DD` for a historical pull. Config: `config/imap.json` (app password set 2026-06-11). | `python lead_watcher_v0_2_0.py --dry-run --since 2026/01/23` then live |
| `lead_md_import_v0_1_0.py` | **HouseValues/Market Leader .md importer.** The authoritative source for HV/ML leads (real date + email + phone in one CSV row, which the notification emails split/omit). Cleans names/phones, enriches + ingests via the intake path with the real date. | `python lead_md_import_v0_1_0.py --dry-run` then live; file in `imports/` |
| `propintel_backup_v0_1_0.py` | **DB backup & safety.** Consistent SQLite snapshots to `backups/`, integrity check, OneDrive conflict-copy detection, restore. Auto-runs on dashboard launch and before every lead ingest. | `python propintel_backup_v0_1_0.py` / `--check` / `--list` / `--restore <file>` |

Superseded scraper backups (`v2_5_3`, `v2_6_0`, `v2_7_0`) are kept on disk but
not used. Safe to archive.

---

## Environment

- **OS:** Windows 11. Shell: PowerShell (and Bash available).
- **Python:** 3.14 (works on 3.12+). Install deps: `python -m pip install -r requirements.txt`
  (requests, beautifulsoup4, openpyxl, flask, pyyaml). `kc_lookup` is stdlib-only.
- **Project folder:** `C:\Users\aubie\OneDrive\Desktop\Claude Tools\Seller_Lead_Scraper\`
  (under OneDrive, so it syncs across machines on the same account).
- **config/** holds the secrets and settings (local only, never commit):
  - `machine.json` - iAuto base_url (`http://192.168.254.90:90`) + machine id
  - `credentials.json` - iAuto login (uin/passwd)
  - `homebot.json` - Homebot Open API token + JSON:API settings
  - `iauto_templates.json` - named outreach buttons -> letter/envelope field maps
- `config.txt` - Google Maps Street View Static API key (for the scraper photos).
- iAuto templates live in `Iauto/` (`HV_Letter1_2182026_Final.json`, `Envelope_Final_today_2232026.json`).
- **Output:** scraper writes `propintel.db` (system of record) and an Excel export.
  Photos save to `property_photos/`.

---

## Integration state (as of 2026-06-05)

**Homebot - LIVE and verified.** Token in `config/homebot.json` authenticates.
Enrolls a verified seller lead as a Homebot Client + Home (which puts them on the
Market Digest). Verified findings: `data.type` literals `clients`/`homes` correct;
accepted client fields are first-name/last-name/email/mobile/locale; `lead-source`
is rejected on create; Homebot derives home value/beds/baths from the address (its
own AVM), so we send only address-street + address-zip. Dedupe by email works.
- **Eligible = 15** (Seller + CONFIRMED/LIKELY + email). 11 already in Homebot.
- **Jason Hauck ENROLLED.** 3 new pending: Ron Potter, Ed Tenney, David Wilson.
- Run remaining: `python homebot_push_v0_1_0.py --live` (dedupe auto-skips the rest),
  or use the dashboard Homebot page "Enroll new leads" button.

**iAuto - LIVE and verified on hardware (2026-06-05).** The full path (queue a
letter in the dashboard -> merge template -> POST to machine) is built, wired, and
PROVEN end to end on the physical machine. Evidence: `outreach` row id 2 (contact
39, property 41, template `seller_lead_initial`) status `sent`, detail "letter
accepted by machine", sent_at `2026-06-05 22:43:00`. Login, the multipart POST,
and the shipped `application/json` file content-type all work as-is, no code
changes needed. Graceful offline failure (FAILED row + plain reason) also
confirmed. The dashboard Send buttons are production-ready. (The diagnostic
`iauto_diagnostic_v0_1_0.py` remains as a re-runnable plumbing check if the LAN
or machine config ever changes.)

---

## Key behavioral knowledge (non-obvious, important when editing)

- **ASP.NET WebForms POSTs need fresh `__VIEWSTATE`.** The Snohomish site is
  ASP.NET; every POST needs viewstate from a fresh GET. Stale viewstate gives
  cryptic errors that never say "viewstate." Scraper refreshes session every 10 properties.
- **King County is LIVE, no bulk files.** Address -> PIN via the KC ArcGIS
  AddressPoints feature layer (deterministic SQL match on `ADDR_FULL`), then live
  detail via `blue.kingcounty.com/Assessor/eRealProperty/Dashboard.aspx?ParcelNbr=`.
  The old eReal form-scrape is dead (KC redesigned it). The old bulk ZIPs + 700MB
  pickle cache are retired. (`kc_lookup_v1_2.py` is the one tool still on bulk files.)
- **Owner names are `LASTNAME FIRSTNAME`** in both counties. Trusts/corps parse imperfectly.
- **Owner-occupancy gate:** KC city/zip are recovered from the billing address only
  when billing street matches property street. Absentee owners leave them blank (correct).
- **Wildcard retry** on Snohomish must match the input street (silent wrong-property matches are a known past bug).
- **Properties without structures** have no beds/baths/sqft/photo. Blank there is expected.
- **iAuto templates:** merge fields are `sheet` items; the cell is `mapList[0].excelStart`.
  Set BOTH `data[0][0]` and `allData[0][0]` (value lives in both; setting one leaves stale text).
- **Lead verdict flags (ownership_match).** Beyond the assessor-match verdicts
  (CONFIRMED / LIKELY / PARTIAL / REVIEW / MISMATCH), three flags mark leads that
  carry a real contact but no verified property: **NO ADDRESS** (Zurple CMA lead,
  no address at all), **UNVERIFIED** (Zurple listed an address that's likely a
  browsed listing, not their home, noted not attached), **UNENRICHED** (a real
  CRM address the scraper couldn't auto-resolve; verify the owner manually). All
  three are seller leads to work; add/confirm the address via the Edit form to
  enrich. Placeholder properties use a synthetic parcel (`NOADDR-*`/`UNENRICHED-*`)
  so they dedup instead of colliding on the blank-parcel UNIQUE constraint.
- **Auto-geocode at ingest.** `pdb.upsert_property()` is the single property-write
  chokepoint (scraper, email intake, and the web Add-contact form all go through it),
  so it best-effort geocodes any new row with a street but no coordinates via
  `_maybe_geocode()` (lazy-imports `geocode_v0_1_0`; never raises; skips rows that
  already have a lat). Toggle with `pdb.GEOCODE_ON_UPSERT`. This is why a bulk scraper
  run now does one geocode per new property; flip the flag off for a giant import and
  backfill afterward.

---

## Test addresses (canonical)

- **Snohomish:** `13533 Boulder Ridge Rd` (Pouncey property, parcel 00863100000900)
- **King County:** `7214 204th Dr NE` (Redmond)
- **Split-county routing:** `19825 30th Drive Southeast, Bothell, WA 98012` -> Snohomish
- **KC zip recovery:** `32732 SE 44th St, Fall City` -> City `Fall City`, Zip `98024`

Address-clean checks: `22123 Dubuque Rd Snohomish, WA 98290` -> `22123 Dubuque Rd`;
`10728 Birch Drive Northwest Marysville` -> `10728 Birch Dr NW`.

---

## Open items / next steps

1. **3 Homebot enrollments** (Potter, Tenney, Wilson) after Aubie reviews Hauck's digest.
2. **Enable Google geocoding billing** to upgrade radius accuracy. Geocoding is built
   and live on the free Census/Nominatim sources (41/42 properties geocoded). Google
   is wired as the rooftop-accurate primary but currently falls through because the
   Cloud project has billing off and the Geocoding API not enabled. Aubie's action:
   in Google Cloud, (a) enable billing, (b) enable the Geocoding API, (c) set a quota
   cap (e.g. 1000/day). Then `python geocode_v0_1_0.py --backfill --force` re-geocodes
   everything at rooftop accuracy (~$0 at this volume; $200/mo free credit). The one
   ungeocoded row (`10728 Birch Dr NW, Marysville` - a free-source gap) will resolve.
Done recently (2026-06-11): iAuto live send proven on hardware (2026-06-05, see
Integration state); `31225 Mountain Loop Hwy` truncated-address row fixed; dashboard
v0.2.6 added bulk mail + friendly template labels + Sent-timestamp; dashboard v0.2.7 +
`geocode_v0_1_0.py` + schema v3 (lat/long) add the radius filter; new leads now
auto-geocode at ingest (see Key behavioral knowledge).

When making changes: syntax-check (`python -c "import py_compile; py_compile.compile('f.py', doraise=True)"`),
keep a CHANGELOG entry, test against the canonical addresses, and remind Aubie to
close `propintel_export.xlsx` in Excel before a scraper run (open file blocks the rebuild).

---

## Running on a new workstation

You are likely reading this because the project moved to a different machine.

**If the new machine uses the SAME OneDrive account (easiest):**
1. Wait for OneDrive to finish syncing this folder (it carries the code,
   `propintel.db`, `config/`, `config.txt`, and `Iauto/` templates). Path will be
   the same: `C:\Users\<you>\OneDrive\Desktop\Claude Tools\Seller_Lead_Scraper\`.
2. Install Python 3.12+ and run `python -m pip install -r requirements.txt`.
3. Open Claude Code in this folder. It auto-reads this CLAUDE.md.
4. Sanity check: `python propintel_app_v0_3_3.py` and open http://127.0.0.1:5000.

**If the new machine does NOT share the OneDrive account:**
Copy the entire `Seller_Lead_Scraper` folder over (USB, zip, or a shared drive),
making sure `config/`, `config.txt`, `propintel.db`, and `Iauto/` come along
(those hold secrets and data). Then do steps 2-4 above.

**Things that do NOT travel automatically:**
- The Claude Code *memory* (in `~/.claude/`, not OneDrive). This file replaces it.
- The Python install + dependencies (step 2).
- LAN access to the iAuto machine. iAuto sends only work on the same network as
  `192.168.254.90`. Homebot and the scraper work from any internet connection.
- If the Google Maps API key is ever regenerated, update `config.txt`.

