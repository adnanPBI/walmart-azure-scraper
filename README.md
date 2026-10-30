# Walmart Azure Scraper v0.5.6 — authoritative GitHub source (2026-10-30)

**Status:** Implementation and OFFLINE regression qualification only. No authorized or
executed paid Classic Oxylabs requests, no genuine 500-product run, no verified
Waukegan #3891 PICKUP price, no observed live recovery, no Azure deployment or
twice-weekly schedule. The public GitHub commit and its matching Actions run are
the source of truth, not the older v0.5.0 ZIP.

## What is implemented

- Exact 22 string-valued JSON fields; blanks are empty strings; `gupc` and
  `unit_price` remain blank; PPM is **directly scraped, never derived**.
- Original 11-category Walmart CSV, exclusion preservation, navigation review,
  positive pagination termination, strict candidate/detail reconciliation.
- Retention across later crawls of all previously observed eligible unavailable
  and later-missing products, with historical vs fresh provenance; fresh-only
  canaries; atomic last-good publication.
- Complete volume/digital terms and clipping precedence; family/bulk/multipack
  source labels; no silent promotion-terms truncation.
- Classic Oxylabs single-product dry-run and offline source qualification.
  **v0.5.4–v0.5.6** changes the proposed request to the documented localized
  `walmart_product` payload and uses the SAME strict source gate in the paid
  response path. Shipping/default-store prices cannot be labeled #3891 PICKUP.
- A fixed durable approval ledger, 1-attempt pre-dispatch reservation, strict
  time/response caps and a whole-run watchdog including cleanup. No paid call
  is made without buyer approval plus private credentials and an enrolled grant.

## Install and test (Windows PowerShell; Python 3.12)

```powershell
git clone https://github.com/adnanPBI/walmart-azure-scraper.git
cd walmart-azure-scraper
# To reproduce a specific result, git checkout <FULL_COMMIT_SHA>
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item config\stores.example.yaml config\stores.yaml
.\.venv\Scripts\python.exe -m walmart_azure --version
.\.venv\Scripts\python.exe -m walmart_azure inspect-categories
.\.venv\Scripts\python.exe -m walmart_azure preflight
.\.venv\Scripts\python.exe -m pytest -q
```

For the separate local synthetic Chromium fixture:
`python -m playwright install chromium` then
`python -m pytest tests/test_browser_e2e_offline.py -v`.
GitHub Actions tests Linux Python 3.11/3.12 and Windows Python 3.12,
includes the isolated fixture on Ubuntu, builds source/wheels, and uploads
offline test logs. These do NOT constitute observed retailer/paid/Azure tests.

## Classic single-product zero-cost diagnostic

**v0.5.6 finalization fence:** ALL worker and daemon writes to the
canonical receipt are fail-closed, with `PENDING` state, zero shape counts,
`receipt_finalized=false` and no terminal timestamp. In particular, even
a delayed `.terminal.tmp` `os.replace` can only replace the receipt with
another unqualified snapshot. The sole positive writer is the **supervising
caller**, which first joins the staging worker before the deadline and then
commits the completed receipt synchronously. A timed-out caller may leave a
pending/failed file; neither it nor a delayed daemon can turn that file
positive afterward. Pre-dispatch paid reservations are never reclaimed.

Client's exact before/after-`os.replace` injected pauses and the normal
saved==returned positive control are covered by offline v0.5.6 regressions.
The normal OS filesystem commit is synchronous in the supervising caller;
as with any synchronous filesystem call, an indefinitely blocked local OS
write cannot itself be preempted by a Python watchdog. This tradeoff removes
the dangerous post-timeout late-success race instead of hiding it with a
second cancellable daemon publisher. An offline PASS is **not** live evidence.

```powershell
python -m walmart_azure oxylabs-probe --store 3891 `
  --product-id 10450114 `
  --url https://www.walmart.com/ip/10450114 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --max-body-bytes 2000000 `
  --output output\diagnostics\classic-product-dryrun.json
```

**Product ID 10450114 and https://www.walmart.com/ip/10450114 were nominated by the client** as Great Value Whole Vitamin D Milk, Gallon. They are **not synthetic placeholders**. Current #3891 PICKUP availability, price and product response have **not** been independently verified. This command is a zero-network, zero-cost dry run; it does not use credentials.

The proposed Classic API payload is exactly:

```json
{"source":"walmart_product","product_id":"10450114",
 "store_id":"3891","fulfillment_type":"pickup","parse":false,"render":""}
```

Target: `POST https://realtime.oxylabs.io/v1/queries` using Classic Basic
Auth only when separately authorized. `store_id` and
`fulfillment_type` are documented localization parameters but the retailer
may return fallback/default-store results. Source-page proof is mandatory.

**Strict gate:** actual provider job_id, returned Walmart /ip/ URL and product
ID, raw inspectable HTML, returned page-selected #3891 + PICKUP, product-store
and explicit pickup option, first-party seller, price + directly displayed PPM
and complete offers unambiguously bound to that selected store and fulfillment.
The exact same `qualify_envelope` logic runs for saved replies and live
transport. If any evidence is missing, do NOT set verification flags/counts.
A compatible source-shape candidate still has `buyer_acceptance=false` and
genuine records=0 until independent provider/client authentication.

**Deadline:** 90 seconds by default (configured maximum 180), including
response parsing, evidence writing and close. A slow phase returns a
conservative `DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN`; reserved attempts
remain permanently spent. No automatic retry and no schedule.

Read [complete v0.5.6 Classic request/response qualification and cost plan](docs/CLASSIC_3891_PICKUP_QUALIFICATION_20261030.md)
and [client handoff](CLIENT_HANDOFF_README.md).

## Outstanding acceptance gaps

The Classic `walmart_product` payload is **documented and implemented**,
but this account's entitlement and the actual returned raw page/store
context remain untested. The production collector STILL uses Playwright;
the Classic adapter is a bounded independent diagnostic, NOT full collection
integration. Complete category/subcategory coverage, 500 genuine products,
observed live recovery, Azure deployment and twice-weekly scheduling are
NOT qualified. A single priced diagnostic has NOT changed the unavailable-
and-later-missing-item retention requirement.

**Checkpoint:** The October 30, 2026 at 18:00 Asia/Dhaka (UTC+06:00) checkpoint has passed. v0.5.6 focuses on the subsequent verified source/CI correction. One-product Classic compatibility remains conditional on **separate client authorization** and account qualification; it is NOT a live-result guarantee. A live assessment requires separate buyer approval, privately managed
credentials and confirmation of provider/account compatibility. The client has nominated the product ID (10450114), but not store-3891 verified. Remaining live/production work was estimated at
5–7 working days **after** connectivity and category coverage qualification.
