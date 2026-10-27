# Client handoff — v0.5.0 — 27 October 2026

**Purpose:** Review fixes to independent v0.4.0 audit and the smallest Classic Oxylabs route. This ZIP is **not** a 500-genuine-product or Azure-accepted delivery.

**Selected store** #3891, Waukegan Supercenter, 3900 Fountain Square Pl, IL 60085, **PICKUP**. Source-specific fulfillment/price remains unproven. No paid requests or credentials approved/used.

## Exact PowerShell commands (Windows, Python 3.12)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m walmart_azure --version
python -m walmart_azure inspect-categories
python -m walmart_azure preflight
python -m pytest -q
python -m walmart_azure oxylabs-probe --store 3891 --max-requests 1 --max-retries 0 --max-seconds 90 --output output\diagnostics\oxylabs-classic-dryrun.json
```

This last command is **dry-run with 0 network requests**. It produces the exact Classic Oxylabs POST payload and review receipt. The only supported default input is the selected Food URL: `{"source":"walmart","url":"https://www.walmart.com/cp/food/976759"}`. No official Walmart API, residential proxy plan or browser session is required to review this payload.

The buyer must explicitly approve a paid Classic API request and supply credentials through a secure operator process before `--execute-billable --billing-approved` may be used. The seller has **not executed** this action. Optional `render=html` is billable/explicit and not automatically used. **Do not scale to category discovery before receiving a genuine source response that proves store ID #3891, pickup and a price.**

See `docs/OXYLABS_CLASSIC_PLAN.md` for caps, sample responses, account cost caveats and stop conditions, `docs/V050_ISSUE_TO_FIX_AND_TESTS.md` for the client issues, and `docs/offline_test_v050_20261027.txt` for test execution. Source hash listing is `SHA256SUMS.txt`; ZIP checksum is provided beside the ZIP.

## Progress / blockers

- Implemented: current-catalog missing-product carry-forward, original historical dates and stale prices, direct-PPM handling, full offer-object terms and nonpayable savings, full source pack labels, strict terminal-pagination/candidate/detail gates, review-only Classic adapter.
- Offline: scripted runner 600→599 and explicit out-of-stock scenarios, interruption fixtures and isolated adapter transport mock; these are **synthetic**.
- Real: earlier RND HTTP connectivity to Walmart homepage passed; Food redirected to `/blocked`/challenge in observed browser/curl route. **No real price-bearing #3891 product was obtained**.
- Pending: Classic route source shape with buyer account, complete live subcategories, 500 genuine products, live observed recovery, Azure execution, production twice-weekly schedule.

**Conditional milestone:** If client authorizes the small Classic query and supplies secure access by October 28, target October 30, 2026, 18:00 Bangladesh Standard Time (UTC+6) for a one-job receipt and go/no-go on store/PICKUP price capability. This is not a guaranteed final delivery date. A 500-product + Azure timeframe requires genuine price provenance and full category scope first.
