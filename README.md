# Walmart Azure Scraper v0.5.2 — authoritative GitHub release

**Status (2026-10-29): source + OFFLINE tested. No paid Classic Oxylabs request, genuine 500-product crawl, observed live recovery, or Azure execution has been approved or performed.** The default commands do not make paid calls. Public source: `https://github.com/adnanPBI/walmart-azure-scraper`; identify the exact tested commit in GitHub Actions. No separate ZIP is authoritative.

## Installation — Windows PowerShell (Python 3.12)

```powershell
git clone https://github.com/adnanPBI/walmart-azure-scraper.git
cd walmart-azure-scraper
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m walmart_azure --version
python -m walmart_azure inspect-categories
Copy-Item config\stores.example.yaml config\stores.yaml
python -m walmart_azure preflight
python -m pytest -q
```

For the **offline-only browser fixture**: `python -m playwright install chromium` followed by `python -m pytest tests/test_browser_e2e_offline.py -v`.

### Small Classic Web Scraper API diagnostic — zero paid requests

The first useful request is a **single original Walmart product URL returning raw HTML**; both an observed numeric Walmart ID and its matching original URL are mandatory (replace `1234567890` with a real, approved example; it is not an observed item). No Food category or second product job is silently added.

```powershell
python -m walmart_azure oxylabs-probe --store 3891 --product-id 1234567890 `
  --url https://www.walmart.com/ip/item/1234567890 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --output output\diagnostics\classic-zero-cost.json
```

Produces **only** the proposed POST and a local receipt, with **zero network requests, credentials or cost**:

```json
{"source":"walmart","url":"https://www.walmart.com/ip/item/1234567890","parse":false}
```

The endpoint is `POST https://realtime.oxylabs.io/v1/queries` (Classic Basic Auth). The `--store 3891` argument is an **expected evidence scope, not a verified Classic API store/fulfillment selector**. Public examples do not establish an exact Waukegan #3891 PICKUP selection mechanism. The Walmart URL source returns raw HTML (unlike parsed-only walmart_product); a response lacking original, inspectable page-selected store + product + pickup + price linkage is marked **unverified**, even with HTTP 200. Only a returned product URL from the provider is accepted; it is never replaced with the requested URL. `geo_location`/ZIP by itself cannot certify the selected store.

**No paid command should be run without fresh buyer authorization.** A paid call now requires one fixed existing absolute WALMART_OXYLABS_LEDGER_ROOT, and separately enrolled approval using oxylabs-enroll-approval --authorization-id <ID> --max-requests 1 --confirm-client-approval. Neither root nor grant is created by a paid probe; moving output paths cannot reset the cap. Missing or damaged accounting fails closed.  If separately approved, an operator must supply private `OXY_WSA_USERNAME`, `OXY_WSA_PASSWORD`, a unique documented `--authorization-id`, `--execute-billable`, and `--billing-approved`, with one request and no retries by default. The fixed-root approval ledger reserves attempts on disk **before** dispatch (including possible charges or uncertain outcomes); a reused receipt path, concurrent lock, changed cap, or exhausted grant fails closed. An independent watchdog returns by the whole-run deadline on slow streams, marks uncertain attempts and does not silently retry them. Do not delete or reset budget receipts to claim fresh approval. See `docs/OXYLABS_CLASSIC_PLAN.md`.

**No production collector integration yet:** `oxylabs-probe` diagnoses a single Classic response; `run`, `discover-tree`, checkpoints and actual product collection still use the Playwright route. The production Playwright runner also rejects available products whose price, PPM or offers are shipping-scoped even with a pickup option. The Classic provider's store/PICKUP selection semantics, result shape and source-body evidence must be qualified before building an approved store-bound collector. Never treat the dry-run or synthetic responses as current Walmart prices.

## Exactly scoped dataset and safety gates

- **Client context**: Waukegan Walmart #3891, 3900 Fountain Square Pl, Waukegan IL 60085; PICKUP. 
- Client's original 11 parent categories and exclusions are in `config/categories.csv`. Production must traverse **all applicable subcategories**, not only parent URLs. This is pending live evidence and source qualification. The dry-run does not scrape these categories.
- Live `run` uses Playwright and requires store/PICKUP proof, seller, direct retailer-displayed PPM, full separate offers, complete listing/detail reconciliation and positive pagination completion. No arbitrary 250-page cap; no failed category masquerades as empty.
- Each valid record has exactly the client-required **22 keys** in order; missing values are empty strings, `gupc` and `unit_price` remain blank. `ppm` is directly displayed, never calculated. Multipack source labels are retained without multiplying sizes. Approximate-weight products are excluded.
- Eligible historical products missing from a later run remain in `latest` with `CARRIED_FORWARD_MISSING` sidecars and historical prices clearly marked stale. They do **not** count toward fresh price-bearing records or live canary verification. A missing fresh canary stops publication even if carried forward.
- Failed/incomplete runs never replace the last-good pointer. Runner-level source, recovery, and retention tests are synthetic; live interruption/recovery and Azure scheduling are **not executed**.
- No Azure schedules, storage changes, provider credentials, or paid requests are activated by CI.

## Independent evidence

`python -m pytest -q` covers the client review regressions, including 600→599 retention, missing fresh canary, store100/page versus store3891/product mismatch, multi-store money ambiguity, missing returned URL, slow localhost streaming, durable budget reservation, clipped MULTIBUY, extended offers and trailing pack counts. GitHub Actions runs Ubuntu Python 3.11/3.12, Windows Python 3.12 and an isolated offline Chromium fixture. CI is **not live acceptance**.

See `CLIENT_HANDOFF_README.md`, `docs/V052_ISSUE_TO_FIX_AND_TESTS.md`, `docs/OXYLABS_CLASSIC_PLAN.md`, and `docs/RELEASE_STATUS.json`. The `Instruction.txt` file agrees with this README; no older Instruction02 is part of this repository.

## Next decision and target

The earlier **2026-10-30 18:00 Asia/Dhaka (UTC+6), 07:00 US Central** target is realistic **only for one newly approved, source-observed-product diagnostic and go/no-go assessment**, if the buyer supplies an authorization decision, selected product ID, safe credential channel and provider configuration by Oct 29. It is not a 500-product or Azure completion promise. The larger live project remains an indicative **5–7 working days after approved store-specific source access and all-subcategory coverage are proven**. If Classic cannot return local store/PICKUP/price evidence, stop and request the buyer's supported store-bound workflow rather than inventing prices or using an unapproved route.
