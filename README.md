# Walmart Azure Scraper v0.5.4 — authoritative GitHub source (2026-10-30)

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
  **v0.5.4** changes the proposed request to the documented localized
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

```powershell
python -m walmart_azure oxylabs-probe --store 3891 `
  --product-id 1234567890 `
  --url https://www.walmart.com/ip/item/1234567890 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --max-body-bytes 2000000 `
  --output output\diagnostics\classic-product-dryrun.json
```

**1234567890 and its URL are synthetic placeholders**. The CLI requires a
genuine source-observed /ip/ URL+matching numeric ID before a real request.
This command is DRY RUN: no network or cost, no credentials.

The proposed Classic API payload is exactly:

```json
{"source":"walmart_product","product_id":"1234567890",
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

Read [complete v0.5.4 Classic request/response qualification and cost plan](docs/CLASSIC_3891_PICKUP_QUALIFICATION_20261030.md)
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

**Milestone:** October 30, 2026 at 18:00 Asia/Dhaka: code/CI and conditional
one-product compatibility review only, NOT full delivery. A live assessment
requires the buyer's explicit approval, credentials managed privately and a
genuine observed item ID. Remaining live/production work was estimated at
5–7 working days **after** connectivity and category coverage qualification.
