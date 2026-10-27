# v0.5.0 local verification — 2026-10-27 (UTC+06:00)

- `python -m pytest -v`: **109 passed, 0 failed** (includes separately executed Chromium fixture).
- `python -m compileall -q walmart_azure`: passed.
- `bash -n azure/deploy.sh azure/inspect_existing.sh scripts/verify.sh`: passed.
- Built Python wheel from v0.5.0 source successfully; package has not been smoke-tested on the buyer's computer.
- Default `oxylabs-probe` dry-run: successful, **0 network requests**, **0 paid Oxylabs jobs**.
- Synthetic Classic response review: successful as **offline source-shape review only**.
- Runner retention simulation: one successful 600-product test run, followed by a 599-observed run that carries forward the missing product, then a repeat missing run. All 600 are **synthetic test products**, not Walmart records.
- Required detail failure and missing pagination terminal evidence prevent publication; last-good dataset remains unchanged.
- No genuine Walmart product JSON, price-bearing store #3891/PICKUP proof, observed live recovery or Azure execution was obtained or verified by this release. **Buyer acceptance: NOT CERTIFIED**.

Full pytest console output: `docs/offline_test_v050_20261027.txt`.
