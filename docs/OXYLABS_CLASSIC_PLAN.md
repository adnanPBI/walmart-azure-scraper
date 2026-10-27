# Classic Oxylabs Web Scraper API — bounded diagnostic request

**Dated: 2026-10-27 Asia/Dhaka (UTC+06:00)**

## What is supported

The adapter `walmart_azure/oxylabs_classic.py` implements **Oxylabs Web Scraper API (Classic)** via HTTPS Basic-auth `POST https://realtime.oxylabs.io/v1/queries` with the retailer-specific URL source `walmart`. A second optional source is `walmart_product`. This is the **scraping API**, not a residential proxy account, and not the newer Web API bearer-token `/scrape` endpoint.

The exact Classic account, available target features, real output shape, store/pickup locality and quotas **have not yet been tested with buyer credentials**. Do not confuse provider API success with store-accurate Walmart product evidence. Only client-confirmed demonstration store: **#3891, 3900 Fountain Square Pl, Waukegan IL 60085, PICKUP**.

Official/reference sources:
- https://developers.oxylabs.io/products/web-scraper-api
- https://github.com/oxylabs/agent-skills/blob/main/skills/web-scraper-api/examples.md
- https://github.com/oxylabs/web-scraper-api
- https://oxylabs.io/products/scraper-api/web/pricing

## Payloads, expected envelope

No-auth dry-run request **does not send** the following payload:

```
POST https://realtime.oxylabs.io/v1/queries
Content-Type: application/json
Authorization: Basic <read from process environment at runtime; never log>

{"source":"walmart","url":"https://www.walmart.com/cp/food/976759"}
```

Only if buyer explicitly authorizes rendering and associated cost: `{"source":"walmart","url":"https://www.walmart.com/cp/food/976759","render":"html"}`. Rendering need is **unknown until the first unrendered approved response**; never auto-upgrade to a more expensive route.

Only if a source-observed numeric product ID is available, and separately authorized: `{"source":"walmart_product","query":"<SOURCE-OBSERVED-PRODUCT-ID>","parse":true}`. That adds a **second** API job.

Expected Classic response (shape, not proof):

```
{
  "results":[{
    "status_code":200,
    "url":"https://www.walmart.com/cp/food/976759",
    "job_id":"<provider-job-id>",
    "content":"<html>...</html>"
  }]
}
```

If `content` is a parsed JSON object, it may not include original visible store/PPM/offer text. The probe therefore does **not** certify those fields from a generic provider parse. The **complete sanitized provider response** is saved with a raw SHA-256 and sanitized SHA-256. Original raw bodies are not bundled in public ZIPs. Merchant price, original displayed PPM, linked coupons and store/PICKUP fields require human source comparison before any buyer acceptance.

## Approval gate, execution limits and stop conditions

- **Initially 0 requests:** `python -m walmart_azure oxylabs-probe --store 3891 --max-requests 1 --max-retries 0 --max-seconds 90 --output output/diagnostics/classic-dry-run.json`
- **If buyer approves paid execution:** 1 Classic job, 0 retries, no JS rendering, whole-run deadline 90 s, max 2 MB returned body, precisely one category URL. No 100-page/1,500-request inventory.
- Hard caps, even if arguments are changed: **at most 2 provider jobs including retries, at most 1 retry/job, 180 s whole-run application deadline, 5 MB/response**. Network calls have connect/read timeouts; OS/network socket deadlines are also subject to system scheduling.
- Abort on provider auth failure (401/403), rate limit 429, retailer `/blocked`/captcha, non-200 source status, absent/unsafe source URL, missing explicit store ID #3891, no verified local pickup or price, missing original source evidence, body cap, malformed provider response, or deadline. Server-side 5xx may be retried **only if** explicitly configured with a funded 2-job cap.
- No automatic switching to generic universal, residential proxies, alternative location, headless-browser cloud usage, or scheduled collection.
- No credential read for the default dry-run. Paid execution requires **both** `--execute-billable` and `--billing-approved` AND separate environment variables `OXY_WSA_USERNAME` / `OXY_WSA_PASSWORD`. These flags are technical safeguards, not a replacement for client authorization.

## Cost estimate (illustrative, not a binding Classic quote)

Oxylabs' public Web Scraper API pricing page currently lists approximately **$1.15 per 1,000 successful "Other" results without JS** and **$1.35 per 1,000 with JS** on the Free Trial/Micro pricing table. At these published unit rates, one no-JS diagnostic result is about **$0.00115** and two about **$0.00230**; a rendered result is about **$0.00135**. **These are unit-rate arithmetic illustrations, NOT the price of a Classic account, subscription, minimum charge or an approved quote.** The buyer must confirm actual Classic account credits/contract, tax, rounding, any rendering multipliers, and spend caps from their Oxylabs account. Requests returning provider 2xx and 4xx may be billable under published terms. The dry-run has no Oxylabs charges.

Azure diagnostic cost is **zero** for this initial local probe because **no Azure service is created or started**. Deployment remains a separate decision and requires a subscription-scoped cost quote and permissions.

## Earliest useful next milestone

- Source, offline tests and dry-run adapter: delivered **October 27, 2026 (UTC+06:00)**.
- If the client explicitly approves a Classic API call and supplies secure execution access by October 28: target **October 30, 2026, 18:00 Asia/Dhaka (UTC+06:00)** for a one-job response receipt and a go/no-go decision on source-proven pickup/price compatibility. This is conditional, not a promise of 500 products.
- A complete 500-product live demonstration, observed recovery and Azure acceptance cannot be dated reliably until the store-specific price-bearing response is qualified and the required all-subcategory coverage is verifiable; budget 5–7 working days after those gates pass, subject to the retailer/provider's actual capabilities.
