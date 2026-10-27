# RND workstation — v0.5.0 client review (2026-10-27)

The prior RND HTTPS GET to Walmart homepage returned HTTP 200, but the Food category redirected to Walmart's `/blocked`/challenge page. This does **not** verify pickup prices or any genuine catalog records. The new Classic Oxylabs provider route must be tested **only after client consent**.

## Safe installation/checks (no Oxylabs requests)

From an extracted `walmart_azure_scraper` directory in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m walmart_azure --version
python -m walmart_azure preflight
python -m pytest -q
python -m walmart_azure oxylabs-probe --store 3891 --max-requests 1 --max-retries 0 --max-seconds 90 --output output\diagnostics\classic-dry-run.json
```

The final command generates a JSON description of exactly one **unexecuted** Classic Web Scraper API request. No Classic account, proxy, browser state or credential is needed. No requests or payments are initiated.

For a separate no-network test against the bundled explicitly **synthetic** provider envelope:

```powershell
python -m walmart_azure oxylabs-review --store 3891 --response examples\oxylabs_classic_SYNTHETIC_DO_NOT_SUBMIT_AS_GENUINE.json --output output\diagnostics\synthetic-review.json
```

## Before any live or cloud action

1. Obtain explicit permission and quota/cost approval for **one Classic Web Scraper API job**. Do not use/resell residential proxy credentials. The client has **not** authorized a billable call.
2. Obtain credentials securely in the operator environment, never in source, ZIP, log or private contest message.
3. Run exactly one 90-second, no-retry job only after approval. Inspect its complete sanitized response and confirm client-approved store #3891, pickup availability, *price-bearing* retailer source, direct PPM and any offer terms.
4. Stop if blocked or store-specific pickup provenance is missing. A provider HTTP 200 is insufficient.
5. Do **not** run the older 100-page/1,500-request browser discovery as a first diagnostic. Do not activate any Azure schedule.

See `docs/OXYLABS_CLASSIC_PLAN.md` for the exact POST body, cost caveats, bounded execution command and all stop conditions. The historical RND browser instructions have been archived under `docs/history/` only for traceability.
