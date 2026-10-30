# Walmart Azure Scraper v0.5.6 — client reproduction (2026-10-30)

The **exact GitHub commit SHA plus matching successful Actions run** supersede
older ZIPs and outdated documents. All evidence is offline until separately
authorized and independently authenticated.

## Windows PowerShell

```powershell
git clone https://github.com/adnanPBI/walmart-azure-scraper.git
cd walmart-azure-scraper
# git checkout <FULL_VERIFIED_COMMIT_HASH>
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item config\stores.example.yaml config\stores.yaml
.\.venv\Scripts\python.exe -m walmart_azure preflight
.\.venv\Scripts\python.exe -m pytest -q
```

Optional browser fixture: `python -m playwright install chromium`,
then `python -m pytest tests/test_browser_e2e_offline.py -v`.

## Zero-cost, one-product Classic request preview

```powershell
.\.venv\Scripts\python.exe -m walmart_azure oxylabs-probe `
  --store 3891 --product-id 10450114 `
  --url https://www.walmart.com/ip/10450114 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --max-body-bytes 2000000 `
  --output output\diagnostics\classic-product-dryrun.json
```

Great Value Whole Vitamin D Milk, Gallon; original Walmart URL `https://www.walmart.com/ip/10450114` (product ID `10450114`, nominated by the client on 2026-10-30; not independently retailer-verified). This is a client-nominated product candidate, NOT independently verified as currently available for Waukegan #3891 PICKUP or priced there. No request is sent.
Exact payload:
`{"source":"walmart_product","product_id":"10450114","store_id":"3891","fulfillment_type":"pickup","parse":false,"render":""}`.

**The exact 3891 PICKUP returned price is NOT yet verified.** The provider
may fall back to default-store results. The response must contain raw HTML
and independent selected page/product/price proof and actual returned job ID
and URL, otherwise strict qualification FAILS.

This focused patch requires saved receipts to carry a finished marker and
`receipt_finalized=true` and a completed caller-owned final commit before interpreting a positive status. A daemon only stages unqualified receipts; a timeout must never be followed by late success;
an interrupted file save remains pending/failed. The expired watchdog makes
zero blocking filesystem reads.

No buyer authorization exists for credentials, paid execution or Azure. A
future billable call must use explicit separate approval, a fixed persistent
pre-enrolled ledger, unique receipt and credentials outside GitHub. Read
[the complete request, evidence, deadline and cost plan](docs/CLASSIC_3891_PICKUP_QUALIFICATION_20261030.md).
The code still needs Classic production collector integration, 500 genuine
distinct products, all category/subcategory coverage, observed live recovery
and Azure production tests. Historical unavailable items must remain retained
even if a diagnostic requires one currently price-bearing item.
