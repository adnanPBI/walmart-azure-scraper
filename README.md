# Walmart Azure Scraper — v0.5.0 (2026-10-27)

**Status: SOURCE / OFFLINE QUALIFIED; NOT LIVE OR AZURE ACCEPTED.**

This review candidate implements the 22-field Walmart JSON wire contract, versioned local/Blob checkpoints, fail-closed store and PICKUP verification, no-delete assortment carry-forward, separate volume and digital offer parsing, direct (not calculated) PPM, category/price coverage safeguards, and a **new Classic Oxylabs Web Scraper API (realtime endpoint) diagnostic**.

**Do not describe synthetic fixture output as a genuine 500-product Walmart dataset.** Verified live Walmart products: **0**. Client has not approved paid Oxylabs execution or Azure deployment. No scheduled jobs were activated by this release. The provider request transport is implemented and tested using injected offline responses, but Waukegan #3891's store/PICKUP context must still be independently demonstrated in a *real* price-bearing retailer response. Complete subcategory enumeration and a live observed recovery test remain pending.

## Prerequisites

- Python 3.11+ (Windows PowerShell examples use Python 3.12)
- Classic Oxylabs API credentials **only if client explicitly authorizes paid diagnostic**. Do not use a residential proxy subscription; the adapter calls `https://realtime.oxylabs.io/v1/queries`.
- Playwright 1.56.0 + Chromium only for legacy browser route; **not needed** to run the Classic API probe.
- Requests >=2.31,<3, BeautifulSoup4 >=4.12,<5, PyYAML >=6,<7, Azure Storage Blob >=12.20,<13, Azure Identity >=1.17,<2.
- Fully exact transitive-dependency locking is still pending. See `pyproject.toml`.

## Windows setup, offline preflight and tests

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m walmart_azure --version
python -m walmart_azure inspect-categories
python -m walmart_azure preflight
python -m pytest -q
```

For legacy browser regression with local Chromium, run `python -m playwright install chromium`. The Classic probe sends HTTP requests through `requests`, **not** Playwright and does not require Chromium.

## Smallest Classic Oxylabs review — NO request, NO credentials

```powershell
python -m walmart_azure oxylabs-probe --store 3891 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --output output\diagnostics\classic-dry-run.json
```

- Dry-run is the default. It prints the exact POST endpoint, request JSON and request budget.
- The payload is `{"source":"walmart","url":"https://www.walmart.com/cp/food/976759"}`.
- The API may return a homepage, a challenge, generic market prices, or a category response that does **not** establish Store 3891. None is assumed sufficient.
- An optional product ID adds `{"source":"walmart_product","query":"<SOURCE-OBSERVED-ID>","parse":true}` as a second request; set `--max-requests 2` and get explicit approval for the second paid job.
- Optional JS-rendered HTML requires `--render-html` and explicit prior cost review; **no automatic rendering retry**.

### Paid probe — sample ONLY; do not execute without client approval

1. Buyer authorizes no more than one Classic API job (or explicitly two if product ID is provided), no retries and 90 seconds.
2. Privately configure `OXY_WSA_USERNAME` and `OXY_WSA_PASSWORD` as process environment variables. Never paste credentials into a repository, console transcript, or Freelancer chat.
3. Only then use:

```powershell
python -m walmart_azure oxylabs-probe --store 3891 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --execute-billable --billing-approved `
  --output output\private\classic-20261027-approved.json
```

**Execution guardrails:** hard upper bounds 2 total jobs including retries, 1 retry per job, 180 seconds, 5 MB/response. Defaults are stricter (1 job, 0 retries, 90 seconds, 2 MB). Auth denied, 429, blocked/challenge, absent retailer source URL, store/PICKUP price unverified, body/deadline caps and malformed responses stop the probe. No fallback to another proxy or target. A complete sanitized API response body is preserved privately next to the receipt with its raw and sanitized SHA-256 digests. Human price comparison remains mandatory. **Do not publicly share unsanitized provider responses.**

For provider response inspection with no API calls:

```powershell
python -m walmart_azure oxylabs-review `
  --response output\private\client-provided-classic-response.json `
  --output output\diagnostics\offline-source-review.json
```

## Production runner (browser route, not yet live accepted)

A live source and complete reviewed subcategory CSV are prerequisites. The supplied 11 parent-category URLs require recursive inventory followed by completeness review. The runner fails closed rather than publishing parent-only data as complete.

```powershell
python -m playwright install chromium
python -m walmart_azure discover-tree --store 3891 --max-pages 2 `
  --max-depth 2 --max-seconds 90 --max-http-requests 250 `
  --output output\diagnostics\small-tree.json
```

That discovery is **review-only** and may be blocked; do not claim exhaustive coverage or a priced product dataset. A genuine production run with a *reviewed expanded* CSV can be started only under authorized access and appropriate budget/operating controls.

## Latest-catalog retention and completion gates

- Previously observed, eligible, store-proven products missing from the next crawl are carried forward into **latest** and are flagged `CARRIED_FORWARD_MISSING`. Their original `crawl_date`, original `first_observed_date` and `last_observed_date`, old source proof, and historical prices remain identifiable.
- Carried-forward stale prices **never count** toward 500 current price-bearing products. Their status is `UNAVAILABLE` in the separate evidence sidecar; the 22-field JSON remains unchanged.
- Explicit locally unavailable/OOS products are retained as records where source provides known UPC/URL/title, with separate evidence; blank prices are not fabricated.
- Full listing-to-detail candidate reconciliation, positive terminal pagination evidence, no unresolved product details and no omitted pages are required for PASS. The old 45% and 2% tolerance settings no longer authorize partial publication.
- Store/PICKUP proof must remain consistent; atomic `latest/<store>.json` pointer updates only on full PASS. Crash-resume checks the source sidecar before republishing.
- Source category graph completeness still requires real retailer/source verification; no parent-only acceptance by default.

## What was tested vs. what remains

See `docs/V050_ISSUE_TO_FIX_AND_TESTS.md` for a regression matrix, `docs/OXYLABS_CLASSIC_PLAN.md` for payloads, cost, stop conditions, and the offline test log in `docs/offline_test_v050_20261027.txt`.

**Test classes are synthetic, not observed retailer data.** Live Walmart collection, the 500 genuine product proof, actual price/PPM/deal comparison, live recovery, paid Classic API requests and Azure execution are **NOT RUN / NOT APPROVED**.

## Security and handoff

Source is unencrypted, with no embedded Oxylabs credentials, reverse proxy settings, remotely disabling code or telemetry. Never place live bearer tokens, session state or unredacted response bodies in public source control. The self-contained ZIP contains a SHA-256 manifest. `azure/deploy.sh` is **manual-only and requires affirmative resource/cost approval**; no job was created or modified during this release.

## GitHub Actions offline verification

The `v0.5.0 offline quality gates` workflow runs on push, pull requests, and explicit `workflow_dispatch` on Python 3.11/3.12 (Ubuntu) and Python 3.12 (Windows). It runs compilation, config preflight, runner-level regressions, a **real Chromium process against intercepted synthetic fixtures only**, a zero-request Classic API dry run, and package builds. CI artifacts include JUnit output, logs, and the build distributions. CI has read-only repository permission and supplies no credentials; **it never performs paid Oxylabs requests, Walmart live collection, Azure deployment, or scheduled production scraping**. A green CI badge therefore means offline qualification only.

Repository link: https://github.com/adnanPBI/walmart-azure-scraper
Actions: https://github.com/adnanPBI/walmart-azure-scraper/actions
