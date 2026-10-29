# Classic Oxylabs v0.5.2 — bounded raw-HTML diagnostic plan

Date: 2026-10-29. NO paid requests, credentials or Azure access approved.

Official Oxylabs target descriptions distinguish Walmart Product (walmart_product: parsed JSON) from Walmart URL (walmart: raw HTML). The previous parse=true request could return dict content without original page-selected store context. For the verifier's source HTML requirement, the proposed ONE job is:

POST https://realtime.oxylabs.io/v1/queries via Classic Basic Auth (only after separate approval).

Payload: {"source":"walmart","url":"https://www.walmart.com/ip/OBSERVED_NAME/OBSERVED_ID","parse":false}

Response shape (illustrative only): {"results":[{"url":"https://www.walmart.com/ip/OBSERVED_NAME/OBSERVED_ID","status_code":200,"job_id":"EXAMPLE","content":"<html> original retailer source including __NEXT_DATA__ </html>"}]}

Both item ID and exact product URL must be source-observed; no fabricated product source URL; no category listing, automatic rendering, retries, or extra job. The returned URL must match Walmart product ID. Dict content is not sufficient. Full sanitized HTML, original/sanitized SHA-256 and rejection causes are retained.

The parser requires ONE original page store #3891, ONE product store #3891, verified Walmart first-party seller, explicit pickup availability, and the SPECIFIC price, direct PPM and each offer from that pickup context. It rejects SHIPPING on priceInfo/currentPrice/unitPrice/offers, ambiguous mixed fulfillment, conflicting store scopes, missing returned URL, and challenge/blocked pages. Generic pickup option cannot bless shipping money.

IMPORTANT LIMITATION: neither --store 3891 nor the documented Classic raw-HTML URL request establishes an exact STORE/PICKUP selector. No verified Classic Waukegan #3891 pickup selection parameter is available in the current implementation. Do not infer it from a ZIP or another service. Ask the client/provider for a supported Classic session/context/browser-instruction method and a genuine response before authorizing any paid qualification.

ZERO-COST preview (synthetic only):
python -m walmart_azure oxylabs-probe --store 3891 --product-id 1234567890 --url https://www.walmart.com/ip/item/1234567890 --max-requests 1 --max-retries 0 --max-seconds 90 --output output/diagnostics/classic-preview.json

Fixed spending allowance (FUTURE ONLY AFTER SEPARATE CLIENT APPROVAL):
1. Provision ONE existing absolute persistent access-controlled WALMART_OXYLABS_LEDGER_ROOT outside receipt directories/ephemeral runners, shared by all invocations.
2. Explicit operator enrollment: python -m walmart_azure oxylabs-enroll-approval --authorization-id <BUYER_APPROVAL_ID> --max-requests 1 --confirm-client-approval
3. Separately authorized private credentials plus --execute-billable --billing-approved and matching observed item ID/URL. No automatic grant creation, no reused receipt allowance, no resets on crashes, and no unapproved rendering.
4. Budget: maximum ONE job, ZERO retries, 90 seconds, 2 MB response for first diagnostic; local approval ledger reserves possible charges BEFORE dispatch and marks uncertain attempts spent. Missing/corrupt grant fails closed. Whole-run watchdog covers slow response streaming.

The O_EXCL lock/fsync approach needs a shared atomic filesystem, not independent ephemeral GitHub or Azure containers. Multi-instance Azure paid execution requires separately qualified distributed budget enforcement. Real Classic account rate and any JavaScript rendering cost are unknown: obtain an account quote before paid approval.

Classic is currently a standalone one-product probe. The full Playwright runner has shared fulfillment-money rejection for available products but Classic is NOT connected to category/subcategory enumeration, page checkpoints, retained assortment, recovery or Azure schedules. These integrations remain outstanding.

2026-10-30 18:00 Asia/Dhaka / 07:00 US Central is a CONDITIONAL one-product go/no-go only; the required approved source/URL/store selection method is not available yet. Full buyer acceptance remains an estimated 5–7 working days AFTER connectivity and coverage qualification, not a guaranteed completion date.

References: https://oxylabs.io/products/scraper-api/ecommerce/walmarts ; https://github.com/oxylabs/web-scraper-api .