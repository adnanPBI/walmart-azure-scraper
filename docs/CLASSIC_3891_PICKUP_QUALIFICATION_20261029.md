# Classic Oxylabs → Walmart #3891 PICKUP: qualification protocol

**Date:** 2026-10-29. **Status: OFFLINE SOURCE-GATE IMPLEMENTED; LIVE SOURCE NOT QUALIFIED.**

## 1. What is documented — and what is not

The *Classic Oxylabs Web Scraper API*, not a residential proxy subscription, accepts Basic-auth POST to `https://realtime.oxylabs.io/v1/queries`. The dedicated `walmart` URL target can return raw HTML with `parse: false`; `walmart_product` is the parsed product-ID target. `render: html`, `geo_location`, `context` and browser instructions exist as broader Web Scraper API capabilities, but **their compatibility with a particular Walmart target and exact #3891 pickup-store selection has NOT been established**. Geo-location/ZIP and a requested `--store 3891` are NOT store-selection proof.

**No store-selector parameter has been guessed, embedded, or enabled.** Do not insert Walmart cookies or vendor keys into source code, public CI logs, chat or client ZIPs. Do not use unreviewed browser automation to circumvent retailer access restrictions.

### One small Classic product request, for independent review only

Proposed HTTP request (only after the client explicitly approves credentials, billing and selected store method):

```http
POST https://realtime.oxylabs.io/v1/queries
Authorization: Basic <FROM APPROVED SECRET STORE>
Content-Type: application/json

{"source":"walmart","url":"https://www.walmart.com/ip/<source-observed-slug>/<source-observed-id>","parse":false}
```

The URL/ID must be directly observed. The POST does not itself select store #3891. Do **not** claim the resulting prices are pickup-local merely because the CLI contains `--store 3891`.

## 2. Provider-specific evidence that must appear in the actual response

Required in the **returned** source, rather than a configured label:

1. Response envelope `results[0].url` is an actual Walmart HTTPS `/ip/.../<id>` URL and `results[0].status_code == 200`; original raw retailer HTML and a provider job ID must be present.
2. Retailer `__NEXT_DATA__` identifies the **selected page store** as **only #3891** and explicitly selects **PICKUP**, not DELIVERY or SHIPPING. No contradictory page or product store IDs.
3. Primary product object has the same product ID, Walmart as first-party seller, and an explicit store-3891 **PICKUP option** with availability.
4. `priceInfo` / displayed price is *itself* scoped to **store #3891 and PICKUP**. Any direct PPM and each digital/volume offer independently carries or inherits explicit local pickup store/fulfillment context. Conflicting/unknown/ambiguous monetary scopes reject the evidence.
5. The original/sanitized HTML, returned URL, source/job IDs, source paths and exact displayed fields are saved as a private evidence sidecar. A human compares the live retailer view and pricing independently.

A syntactically valid HTML fixture, parsed-only JSON, output label, or third-party quote is **not genuine Walmart local-price proof**. The raw response could be synthetic or stale and needs job provenance from the authorized account before acceptance.

## 3. Zero-request review commands (Windows PowerShell)

```powershell
# Run from the cloned repository root. Requires Python 3.11/3.12 and git.
Copy-Item config\stores.example.yaml config\stores.yaml -ErrorAction SilentlyContinue
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m walmart_azure oxylabs-capabilities
.\.venv\Scripts\python.exe -m pytest tests/test_classic_qualification.py -q

# Review the explicitly SYNTHETIC source fixture: 0 API requests / 0 cost.
.\.venv\Scripts\python.exe -m walmart_azure oxylabs-qualify `
  --response examples\oxylabs_classic_SYNTHETIC_WAUKEGAN_3891_STRICT_REVIEW.json `
  --url https://www.walmart.com/ip/SYNTHETIC-DO-NOT-SUBMIT/1234567890 `
  --product-id 1234567890 --category Food --sub-category 'Soft Drinks' `
  --expected-job-id SYNTHETIC_JOB_NOT_AUTHENTIC `
  --output-dir output\diagnostics\synthetic-qualify
```

The result is `qualification_receipt.json`, `sanitized_source.html`, and (only if strict proof checks pass) `candidate_RECORD_NOT_LIVE_VERIFIED.json`. **Nothing is published to the last-good catalog, no charge is incurred and any candidate is explicitly NOT a genuine collected product.** Never submit the synthetic record toward the buyer's 500.

For a future **authorized genuine** provider response, replace the response file, returned product URL, item ID and expected job ID with source-observed details. Save the original provider response privately; use a new output directory for each review. The offline review alone does not authenticate the provider job or the current store price.

## 4. Client/operator decision points; no approval implied

1. Ask Oxylabs support or the client's Classic account operator for the **documented exact store #3891 PICKUP selection** method on the `walmart` raw HTML target, and whether `render:html` is required. Require an example **returned** HTML price response, not just a payload claim.
2. If the provider confirms a supported store-selection mechanism, review one new request payload and quote the exact account cost. Client independently authorizes **one request**, no retry, 90-second wall-clock cap, 2 MB response cap, and one pre-enrolled immutable ledger. No payment authorization exists today.
3. If the provider cannot select exact store #3891 with pickup in Classic, return `NO_GO_CLASSIC_EXACT_STORE`. A distinct, explicitly approved browser-assisted or alternate provider route requires a separate request, data-provenance review and cost approval; do not silently change services.
4. Only after the one-product source passes with human proof should category pagination, unavailable/missing-product retention, complete assortment coverage, 500 distinct fresh items, real restart/recovery, Azure, and twice-weekly schedules enter their separate validation phases.

## 5. Cost/risk bounding

| Item | Unapproved diagnostic design |
| --- | --- |
| Source | Classic `walmart` raw HTML URL, `parse:false`, one source-observed product |
| Credentials | Secrets only in operator-controlled environment; never in repository |
| Paid calls | **0 today**; proposed **1** only after explicit separate approval |
| Retries | 0 |
| Whole-run time | Maximum 90 seconds |
| Response size | Maximum 2 MB |
| Additional JS render/geo/batch | Off, unless independently established and approved |
| Ledger | Existing operator-enrolled durable root; one request reserved *before* dispatch |
| Stop | Wrong/ambiguous page store, fulfillment, price/PPM/offers, missing raw HTML or source URL, 4xx/5xx, challenge, time/body limit, lost accounting, any source mismatch |
| Pricing | Depends on client's actual Classic contract and rendering options. Published public per-result prices are illustrative, not a client account quote. Request exact account pricing before authorization |

## 6. Acceptance boundary

**Completed locally:** a stricter no-cost response verifier, exact 22-field candidate normalization, source-HTML/evidence hash sidecars, error regressions and no-publication path. **Not completed:** supported Classic #3891 PICKUP selection, authenticated retailer result, paid call, 500 genuine distinct records, whole-category coverage, observed live recovery, Azure deployment and schedules. The production runner still lists and fetches via Playwright: a standalone Classic one-product qualifier **does not replace** an integrated full-coverage Classic category+detail adapter.

## 7. Milestone

Previous **October 30, 2026, 18:00 Asia/Dhaka (07:00 US Central daylight time)** was a *conditional one-product compatibility checkpoint*, not a complete scraper. It is not a reliable live delivery commitment until provider store selection and client-paid authorization are confirmed. New conservative checkpoint: **October 30, 2026, 18:00 Asia/Dhaka** for this *code and offline evidence protocol*, with live go/no-go dated from actual permission availability. Full work remains a separate estimated **5–7 working days after connectivity and category-coverage qualification** and may require a new source-access solution.

### Reference documents

- https://github.com/oxylabs/web-scraper-api (Classic realtime and general capabilities)
- https://github.com/oxylabs/agent-skills/blob/main/skills/web-scraper-api/examples.md (`walmart` URL versus parsed product source examples)
- https://oxylabs.io/products/scraper-api/ecommerce/walmarts (Walmart targets and public pricing; not a firm quotation)