# Walmart Scraper v0.5.2 — Client commands (2026-10-29)

The authoritative release is the GitHub commit reported with the matching successful GitHub Actions run; **not** the previously shared v0.5.0 ZIP or its older Instruction02 text. Clone or check out the full commit SHA supplied in the private Freelancer message.

## Windows PowerShell

```powershell
git clone https://github.com/adnanPBI/walmart-azure-scraper.git
cd walmart-azure-scraper
# Optional: git checkout <full-authoritative-commit-sha>
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m walmart_azure --version
python -m walmart_azure preflight
python -m pytest -q
```

Optional isolated browser fixture: `python -m playwright install chromium` then `python -m pytest tests/test_browser_e2e_offline.py -v`.

## Classic Oxylabs primary-product DRY RUN; zero paid network requests

```powershell
python -m walmart_azure oxylabs-probe --store 3891 --product-id 1234567890 `
  --url https://www.walmart.com/ip/item/1234567890 `
  --max-requests 1 --max-retries 0 --max-seconds 90 `
  --output output\diagnostics\classic-review.json
```

The shown item ID and matching URL are **synthetic command placeholders**, not a retailer record. Replace with a real source-observed product ID only after client selection. The dry run writes proposed `{"source":"walmart","url":"https://www.walmart.com/ip/item/1234567890","parse":false}` and a no-cost receipt. The Classic Walmart URL raw-HTML source is documented; parsed-only walmart_product cannot prove source-page pickup context; a tested way to select **Waukegan #3891 PICKUP** through this request is **not** established. We do not claim genuine price, PPM or offer evidence without a returned original page showing a single consistent store/product/PICKUP/price context.

## Never execute billable mode without approval

The **separate** paid execution flags (not approved at present) require a pre-existing fixed WALMART_OXYLABS_LEDGER_ROOT and separately enrolled buyer-approved grant (oxylabs-enroll-approval), plus private Oxylabs credentials, a buyer authorization reference passed as `--authorization-id`, unique receipt path, explicit `--execute-billable --billing-approved`, and approved cap. Durable ledger, independent stream deadline, source URL proof, seller and store/price binding all fail closed. For bounded design and unreconciled provider features read `docs/OXYLABS_CLASSIC_PLAN.md`.

## Status

Offline tests and CI are distinct from paid Oxylabs execution, 500 live distinct products, live interruption recovery, full category/subcategory coverage and Azure verification. None of those live acceptance gates is completed. The first conditional live review milestone is October 30, 2026 at 18:00 Asia/Dhaka (07:00 Central) *only if the buyer authorizes and provides a source-observed product and access method in time*. Larger acceptance work remains conditional.
