# Walmart #72 — November 3, 2026 Azure access and source checkpoint

**Scope:** read-only account/secret checks and offline regression qualification.
**Prior accepted releases remain accepted:** v0.5.7 deadline correction and
the Azure readiness baseline at `1c9c3819d64af7aae7d8eff442abb743e3d5a753`.
This addendum does not claim production Classic, a paid probe or Azure acceptance.

## Actual read-only RND findings (November 3, Asia/Dhaka UTC+06:00)

- Portable official Azure CLI exists at
  `%USERPROFILE%\MarianosAzureQualification\tools\azure-cli\bin\az.cmd`.
- Both the dedicated Azure CLI configuration and the normal user configuration
  returned **no authenticated account**. An actual account check via the new
  `scripts/azure_readonly_access.py` returned `auth_status=LOGIN_REQUIRED`.
- `oxylabs-username`: **NOT_ATTEMPTED** (no authenticated guest identity).
- `oxylabs-password`: **NOT_ATTEMPTED** (same prerequisite).
- No evidence of RBAC denial has been observed. The client reports that
  individual Get Secret permissions are configured; listing is unnecessary.
- NO secret content was printed, persisted, or sent through ChatGPT; no
  Oxylabs request, Walmart crawl, Azure deployment or schedule was run.
- Seven new **mock-only** access-verification regressions passed locally on
  Windows Python 3.12, including guest/tenant mismatch, independent secret
  failures, timeout, redacted errors, and fixed no-list/no-paid semantics.
- The complete local Walmart offline suite was rerun on RND Windows Python
  3.12: **199 passed, 3 skipped, 0 failures** (202 total cases). The skips
  are platform/browser-dependent tests; live service tests were not attempted.
- GitHub Actions and local offline CI are separate from the two actual
  secret reads. Report the exact post-commit CI run only after observing it.

## Once the operator authenticates: private read-only procedure

1. Open **a private interactive PowerShell terminal on the authorized RND
   machine**. Do not redirect login output to files, paste device/MFA codes
   into chat, or expose session tokens.
2. Use the portable CLI and the same dedicated config for login and checks.
3. Run these commands **in that private terminal**:

```powershell
$az = Join-Path $env:USERPROFILE 'MarianosAzureQualification\tools\azure-cli\bin\az.cmd'
$env:AZURE_CONFIG_DIR = Join-Path $env:USERPROFILE 'MarianosAzureQualification\evidence\azure-config'
& $az login --tenant b6d4bd45-c947-4f69-9949-7e688a70561e --use-device-code --allow-no-subscriptions
python scripts/azure_readonly_access.py --az-exe $az
```

The final command must run from the Walmart repository directory. The
operator privately completes Microsoft sign-in as `adnanrnd@outlook.com`.
It verifies the tenant and active user, and then issues exactly TWO
`az keyvault secret show` operations to `shif1021-kv-hfpzua5n`, by exact
known name. `--output none` suppresses the secret response entirely.
The script emits only `GET_SUCCEEDED_VALUE_NOT_DISPLAYED` or
`GET_FAILED_<redacted code>` for each secret. It never calls list/create,
never accesses another secret, never issues a provider request.

**Interpretation:** `LOGIN_REQUIRED` is an authentication prerequisite,
NOT a denial of individual secret RBAC. When auth is ready, capture only
the script's redacted JSON status, never a credential value.

## Distinct stages still unqualified

1. **Access:** both named secret Get operations, actual provider entitlement
   and client-account Classic rates. The current client comment does not
   approve the one paid request.
2. **Single-source compatibility:** one separately approved `walmart_product`
   request for genuine product `10450114`, store `3891`, `pickup`,
   `parse=false`, `render=""`, with zero retries, 2,000,000 bytes and
   **90-second phase** (not hard caller wall-clock) deadline. Store/PICKUP
   prices must be proven from returned source; request parameters alone fail.
3. **Production adapter and integrity:** source-qualified listing/detail
   integration; durable Blob receipt and sanitized logs; shared, restart-
   and concurrency-safe reservation ledger with tested leases/ETags.
   Current unpersisted `/tmp` receipts and unqualified paid-ledger
   semantics remain NO-GO for paid Azure execution.
4. **Coverage:** genuine >=500 distinct products, original categories and
   uncapped subcategories/pagination, exact 22-field schema and PPM/offer
   semantics; retain eligible unavailable/later-missing history separately
   from current observations; observed stop/resume and independent review.
5. **Azure:** a separate priced/approved manual deployment and real job,
   persistence/readback, execution logs and cleanup. No scheduling approved.

## Updated dated checkpoints (all Asia/Dhaka UTC+06:00)

| Checkpoint | Expected evidence | Explicit gate |
|---|---|---|
| **Nov 3, 2026 — status issued after 18:00** | RND auth blocker and code/offline test status, no claim of live qualification | This checkpoint is informational; the original 18:00 time has passed |
| **Nov 4, 2026, 18:00** | Two exact Key Vault read outcomes, or explicit unattended-login blocker | Attended sign-in by account owner |
| **Nov 5, 2026, 18:00** | One Classic price/source compatibility report, **or blocker** | Client confirms entitlement/rates AND separately authorizes paid request |
| **Nov 6, 2026, 18:00** | Production adapter candidate and source regression plan | Usable qualified source path; no silent unsupported adapter |
| **Nov 10, 2026, 18:00** | Full category/subcategory/pagination manifest progress, or access blocker | Permitted source and verified mapping |
| **Nov 12–17, 2026 (conditional planning)** | Genuine >=500 dataset, live recovery and separate manual Azure acceptance packet | Both connectivity AND complete required coverage qualified early; Azure authorization separate |

The **5–7 working-day** estimate begins only after **connectivity and
required coverage are qualified**. Dates slide when access/evidence gates
move. These are not guaranteed acceptance or award dates.

The Mariano's project uses direct authorized Playwright/Chromium and has
separate store/source/retailer permission gates; Walmart Key Vault access
is **not** Mariano's authorization.
