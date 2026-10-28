# Classic Oxylabs Web Scraper API — one-product diagnostic v0.5.1

**Date 2026-10-28 (Asia/Dhaka). Zero paid requests authorized or executed.**

## Supported API route and limitation

`POST https://realtime.oxylabs.io/v1/queries` using Classic API HTTP Basic Auth and a **single** documented `walmart_product` source with `query=<source-observed numeric product ID>` and `parse=true`.

```json
{"source":"walmart_product","query":"<REAL_SOURCE_OBSERVED_ITEM_ID>","parse":true}
```

The client-confirmed scope is Waukegan Walmart #3891, 3900 Fountain Square Pl, IL 60085, **PICKUP**. Public Classic examples establish a product-ID query, but **do not establish a store-ID/PICKUP selector** for this target. Neither CLI `--store`, ZIP/geolocation nor a request label independently proves locality. Do not invent provider parameters or use a different service's store selection API. Explicit result-body provenance is required; the returned URL must be an actual Walmart product URL containing the expected ID. Parsed product JSON without inspectable page context is **not** acceptable for store/PICKUP price verification.

The returned source must establish one selected page store, one product store, explicit PICKUP availability, Walmart first-party seller, and direct priceInfo/PPM/offer objects bound to that context. Any mismatch, multiple unresolved store IDs, unknown source URL, listing-only object or inconsistent per-store offer/price scope sets verification false. A positive shape result still requires independent human comparison; 500 live records and Azure qualification are separate.

## No-cost command (works without credentials)

```powershell
python -m walmart_azure oxylabs-probe --store 3891 --product-id 1234567890 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --output output\diagnostics\classic-dry-run.json
```

`1234567890` is a synthetic placeholder; replace it with a real observed product ID before any authorization request. Without a product ID the probe returns `NEEDS_PRODUCT_ID_NO_NETWORK_NO_COST`, not a category request. No retries/rendering/extra jobs occur implicitly.

## Paid execution plan — NOT APPROVED

If the client separately approves **one job**, grants valid credentials privately, confirms the product ID and acceptable Classic store-localization method, the operator can supply a unique agreed authorization ID, environment variables `OXY_WSA_USERNAME` and `OXY_WSA_PASSWORD` and explicit flags:

```powershell
python -m walmart_azure oxylabs-probe --store 3891 --product-id <SOURCE_ID> `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --authorization-id <BUYER_APPROVAL_REFERENCE> `
  --execute-billable --billing-approved `
  --output output\private\classic-approved-unique-receipt.json
```

No credentials, approval reference or paid execution was supplied. The source does not enable any scheduled jobs or spend by default. The product source may return JSON without original price/PPM/offer evidence; then **STOP** and ask the client to confirm their supported Classic parameters or authorized store-bound workflow. The production runner still uses Playwright; the Classic adapter is a small standalone probe, not a completed catalog collector.

## Budgets and durable controls

- Default maximum: **1 provider call, 0 retry, 90 seconds whole-run, 2 MB response**. Hard bounds: at most 2 calls including retries, 1 retry, 180 seconds and 5 MB/response; no cost increase without a separate approved budget.
- A per-authorization ledger file and an exclusive receipt are durably `fsync`-written before each dispatch, reserving *possible charges* even if the process crashes. Requests with the same authorization ID cannot exceed the cap even with another receipt file. Stale locks fail closed until manually investigated; no background retry.
- The independent daemon-transport watchdog returns on the whole-run deadline even if the remote server trickles chunks indefinitely. The uncertain attempted call remains charged against the cap. A timed-out socket might continue awaiting OS transport cleanup; a second call is not issued.
- Complete sanitized response JSON and raw/sanitized SHA-256 digests are retained privately. No unsanitized provider envelope, passwords, cookies or API credentials should be shared publicly. A provider response lacking an actual returned URL fails closed.
- Abort on 401/403, 429, 5xx budget exhaustion, redirect/challenge, unknown store, seller mismatch, missing product body/price/PICKUP, incomplete offer terms, response cap or deadline. No CAPTCHA evasion, residential proxy assumption or automatic rendering upgrade.

**Estimated price:** The client's Classic subscription rates, success billing, quota and any minimum charge are unknown. Obtain an account-specific quote and approval; do not substitute generic Web Scraper API marketing unit prices for a binding Classic rate. Dry-run is zero provider cost.

## Conditional milestone

**2026-10-30 18:00 Asia/Dhaka (07:00 US Central)** is a conditional **single-product diagnostic go/no-go** target only if access/product-selection details are authorized by October 29. It is *not* a promise of 500 products or Azure acceptance. Full required category coverage, live recovery and Azure collection remain an indicative 5–7 working days **after** source-localization and complete scope are qualified; this is not a fixed completion date.

Official Oxylabs reference examples: https://github.com/oxylabs/agent-skills/blob/main/skills/web-scraper-api/examples.md and https://github.com/oxylabs/web-scraper-api .
