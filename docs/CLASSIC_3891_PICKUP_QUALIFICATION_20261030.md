# v0.5.6 Classic Oxylabs / Walmart #3891 PICKUP qualification

**2026-10-30.** Source/offline QA only; **zero authorized or executed paid calls**,
zero genuine products, no Azure execution. This replaces the older 2026-10-29
unlocalized Walmart-URL plan.

## Documented single-product request (Classic Realtime Web Scraper API)

`POST https://realtime.oxylabs.io/v1/queries` with provider Basic Auth
(secret environment variables, never committed):

```json
{
  "source": "walmart_product",
  "product_id": "<GENUINE SOURCE-OBSERVED PRODUCT ID>",
  "store_id": "3891",
  "fulfillment_type": "pickup",
  "parse": false,
  "render": ""
}
```

Great Value Whole Vitamin D Milk, Gallon; original Walmart URL `https://www.walmart.com/ip/10450114` (product ID `10450114`, client nominated 2026-10-30; retailer status not independently authenticated). This is the buyer-nominated product for diagnostic review, not an independently verified live Waukegan #3891 PICKUP product or price.

The product ID must be observed in a genuine Walmart primary product URL
`https://www.walmart.com/ip/<slug>/<id>`; supply both ID and URL to the CLI
for provenance. The URL is **not** a payload key for this dedicated source.
The client supplied the Oxylabs documented localization and render forms:
- https://developers.oxylabs.io/products/web-scraper-api/targets/e-commerce/walmart/product
- https://developers.oxylabs.io/products/web-scraper-api/features/js-rendering-and-browser-control

The requested store_id/fulfillment_type may be ignored or fall back to a
default store. They are NOT proof that prices are for Waukegan #3891.
`render:""` explicitly requests no JS rendering. If this yields no usable
first-party HTML/price-context proof, stop and seek a separately approved
rendering method and cost rather than silently enabling rendering.

## Offline zero-network preview (Windows PowerShell)

```powershell
git clone https://github.com/adnanPBI/walmart-azure-scraper.git
cd walmart-azure-scraper
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item config\stores.example.yaml config\stores.yaml
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m walmart_azure oxylabs-probe `
  --store 3891 `
  --product-id 10450114 `
  --url https://www.walmart.com/ip/10450114 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --max-body-bytes 2000000 `
  --output output\diagnostics\classic-product-dryrun.json
```

The product ID and URL above are public retailer observations, not
independent pickup-price proof for #3891. This is a zero-network DRY RUN
(no --execute-billable, no authorization, no retries, no render, no cost).

## Safeguards for an explicitly authorized future one-product call

- One paid job total INCLUDING retries; retries=0.
- Whole process limit 90 seconds, original response limit 2,000,000 bytes.
- The fixed durable `WALMART_OXYLABS_LEDGER_ROOT` must pre-exist;
  approval is separately enrolled and a job is reserved + fsynced
  BEFORE dispatch. Different receipt paths do not reset allowance.
- Credentials `OXY_WSA_USERNAME` and `OXY_WSA_PASSWORD` remain private.
  The client must approve spend, access, and the actual product first. No
  approval has been given.
- A stall in transport, strict parsing, persistence or session cleanup
  returns a **deadline/uncertain** result, NOT a successful qualification.
- Worker saves are always unfinished/unqualified. Only a supervised terminal
  promotion after full cleanup and provisional fsync may mark a receipt as
  `receipt_finalized=true`, `finalization_state=COMPLETE` and `finished_utc`.
  Expired watchdogs never read receipts, and a missing terminal marker
  means PENDING/FAIL, not source-shape qualification.
  If the process is interrupted, treat the reserved attempt as spent;
  do not issue automatic retries.
- No scheduled job, Azure deployment, general category scrape, renderer or
  secondary product is authorized in this diagnostic.

## Unified strict source gate

Both `oxylabs-qualify` (saved response) and `oxylabs-probe` (live transport)
use `classic_qualification.qualify_envelope`. The reviewer requires:

1. Exactly one result with an ACTUAL provider job_id, actual returned
   Walmart HTTPS product URL and source HTTP status 200, matching the source-observed ID.
2. **Raw inspectable HTML** in `results[0].content` with parseable source hydration;
   parsed-only dictionary content is insufficient for selected-page provenance.
3. Actual selected-page location storeId **3891** and fulfillmentType **PICKUP**.
4. Primary product location and explicit PICKUP fulfillment option also scoped
   exclusively to **3891**, with first-party Walmart seller.
5. Every price, directly scraped PPM and separate digital/volume offer object
   must have an explicit compatible #3891 PICKUP scope (including nested objects).
   Reject SHIPPING, DELIVERY, mixed/ambiguous mode or a default-store fallback.
6. Strict 22-field record validation. Missing fields empty strings; gupc and
   unit_price blank; original pack label, directly displayed PPM and complete
   deal terms retained. Only a review-only candidate record is produced.

The sanitized complete source body, raw/sanitized hashes and reasons are kept
in sidecar evidence. No successful synthetic case is marked authentic.
Even a strictly qualifying real transport is **not independently authenticated**
until the client corroborates the provider job and local Walmart prices. Genuine
product count remains **0**, buyer_acceptance=false.

A positive source-shape result is limited to
`STRICT_SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE`.
Timeout at **any phase** supersedes positive flags and count with
`DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN`.

## Still not delivered

- The client's Classic account entitlement and one actual #3891 PICKUP price.
- Provider raw-HTML structure/availability: if `walmart_product + parse=false`
  does not return original HTML with selected store/product pricing, this route
  fails closed; confirm supported HTML delivery and (if needed) rendering price
  with Oxylabs before changing the request.
- Genuine 500 unique Walmart records, all categories/subcategories and
  positive pagination-end evidence; production Classic collector integration;
  observed live interruption/recovery; Azure execution and twice-weekly scheduling.

**Previous conditional checkpoint:** **2026-10-30 18:00 Asia/Dhaka
(07:00 US Central, CDT)**: v0.5.6 bug fix, injected file-I/O regressions,
and GitHub CI results; paid diagnostic remains separately gated.
One-product live assessment at that checkpoint is **conditional on separate
authorization and genuine observed ID**. The 5–7 working-day remainder is a conditional planning range **after**
Classic connectivity and local price evidence AND full category/subcategory
and pagination coverage qualify. It does not begin with this offline patch.


## v0.5.6 post-checkpoint terminal race correction

The client independently injected pauses at the exact atomic rename whose source
ends in `.terminal.tmp`, both **before** and **after** the real swap while the
caller's one-second deadline expired. A background daemon must not be able to
publish `STRICT_SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE` after that failure.

The background publisher now stages **only** a scrubbed PENDING receipt, even
when its actual `os.replace` is delayed. Its return is joined by the
supervising caller within the remaining deadline. **Only the caller** may
synchronously replace the canonical receipt with terminal positive status,
after the background staging has completed. A timed-out stage can never
publish success later. The fixed pre-dispatch allowance remains consumed.

Regression entrypoint: `python -m pytest -q tests/test_release_v055.py tests/test_release_v056.py`.
CI evidence must be checked against the exact authoritative GitHub commit.
Normal positive synthetic runs retain a matching saved and returned receipt;
no offline case proves a genuine Walmart price. The exact one-request,
zero-retry, 90-second, 2,000,000-byte, `render=""` scope remains unchanged.

**Checkpoint date/time zone:** 2026-10-30 (Asia/Dhaka, UTC+06:00),
following the original 18:00 checkpoint. Live account testing requires an
explicit new approval, not included here. Full live work remains separately
estimated at 5–7 working days **after** connectivity and category coverage
qualification, and that estimate is not a committed delivery date.
