# v0.5.7 — explicit phase deadline and synchronous supervisor I/O

**Date:** October 31, 2026 (Asia/Dhaka, UTC+06:00).
**Testing scope:** Synthetic/local-only. No authorized paid Oxylabs calls,
real Walmart collection, Azure deployments, or automatic scheduling.

## Why a contract correction is necessary

Client review of v0.5.6 confirmed the two `.terminal.tmp` races were
fixed, but identified the remaining time-limit caveat:

> Delaying the **caller-owned** `.supervisor.tmp` `os.replace` by about
> 1.30 seconds with `max_seconds=1` led to caller return around 1.45 seconds.
> Returned and saved receipts were both failures, but elapsed time exceeded
> the advertised limit.

This behavior follows from the v0.5.6 ownership rule: background threads
may save only **unqualified PENDING** data; the caller synchronously performs
the sole positive commit. An arbitrary blocking OS-level rename cannot be
forcibly interrupted safely within the same process.

The client explicitly offered either (a) a process-isolated finalization
architecture or (b) an honest time-limit contract distinguishing the bounded
network/worker phase from potentially blocking final file operations.

**v0.5.7 implements option (b)**. We preserve the no-late-positive-race
guarantee and explicitly **do not promise an unconditional wall-clock command
return limit**. No new process, automatic charge, or retry is introduced.

## Exact time-limit semantics

| Phase | `--max-seconds` scope |
| --- | --- |
| Network dispatch / bounded stream reads | Absolute provider/worker phase deadline, with conservative uncertain-call handling |
| Source qualification, evidence and receipt writes, cleanup | Deadline checked by bounded worker supervisor; stalled background work can be abandoned safely |
| Fail-closed `.terminal.tmp` staging | Watched by the caller; any late background swap still contains only PENDING/unqualified bytes |
| **Synchronous `.supervisor.tmp` positive commit** | **No hard caller wall-clock guarantee** if OS/filesystem write or rename blocks |
| Overrun detected after synchronous commit | Saved result synchronously superseded with unqualified PENDING failure before returning failure; grant remains spent |
| Crash / unrecoverable filesystem error during repair | Never claim independent success; review durable approval ledger and receipt manually before any additional request |

The default one-product diagnostic retains **1 provider request, 0 retries,
90-second phase deadline, 2,000,000 maximum response bytes, `render=""` and
no follow-up jobs**. Do not call 90 seconds an unconditional command-time cap.

Receipt fields for audit:
- `deadline_seconds`: configured phase deadline (90 default).
- `deadline_scope: "PROVIDER_WORKER_AND_FAIL_CLOSED_STAGING"`.
- `caller_return_hard_limited: false`.
- `final_receipt_io: "SYNCHRONOUS_SUPERVISOR_MAY_BLOCK_BEYOND_DEADLINE"`.
- `terminal_commit_overran_deadline`: whether the supervised terminal
  filesystem commit itself exceeded the phase deadline.
- On a detected overrun, `terminal_commit_elapsed_seconds` and an
  unqualified `DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN` result.

If a synchronous filesystem operation blocks indefinitely, the caller can
also block indefinitely: no Python watchdog can guarantee termination in
that scenario without process-level isolation. No claim otherwise.

## Client-specified fault injection

```powershell
python -m pytest -q tests/test_release_v055.py tests/test_release_v056.py tests/test_release_v057.py
```

The new regression
`test_supervisor_rename_stall_is_reported_not_claimed_hard_bounded`
runs **both** fault-injection variants for `os.replace` with
`.supervisor.tmp` as its source:

1. `before_real_replace`: pause for ~1.30 seconds before actual rename.
2. `after_real_replace`: perform the actual rename first, then pause ~1.30
   seconds before returning to the caller.

Both scenarios use `max_seconds=1` and synthetic mock provider responses.
They assert a *deliberate* caller overrun, **failure returned and saved**,
zero positive source-shape counts, no completed marker, and one retained
approval-ledger attempt. Rechecking the saved receipt shows no late success.
The tests do not assert a false one-second upper bound.

Additional regressions assert the zero-cost dry-run receipt discloses the
limit and the successful synthetic control retains saved==returned
completion with `buyer_acceptance=false`, genuine product count zero.

The v0.5.5/v0.5.6 tests for blocked intermediate saves, after-deadline
reads, the `.terminal.tmp` pre/post swap and caller-only positive
publication remain in place. GitHub CI runs the entire offline suite on
Linux Python 3.11/3.12 and Windows Python 3.12; only the Ubuntu jobs
execute the isolated Chromium fixture.

## Source/locality and spend safeguards unchanged

The client-nominated product is **Great Value Whole Vitamin D Milk, Gallon**
at `https://www.walmart.com/ip/10450114`, ID `10450114`. The item's
current availability, price, direct PPM and offers for Walmart Waukegan
#3891 PICKUP are not independently established.

Proposed (UNEXECUTED) Classic payload:
```json
{"source":"walmart_product","product_id":"10450114",
 "store_id":"3891","fulfillment_type":"pickup","parse":false,"render":""}
```

Configured `store_id`/`fulfillment_type` request a location but are not
proof of a locally bound price: returned raw HTML must pass the strict
source gate and be independently authenticated. The fixed durable
`WALMART_OXYLABS_LEDGER_ROOT` and pre-dispatch reservation are unchanged.
An uncertain attempt is never automatically refunded or retried.

## Acceptance status and next step

This release is **code + offline/localhost tests only**. The client has not
approved credentials, billable Oxylabs requests, rendering, Azure execution
or scheduling. Full Classic production collector integration, 500 genuine
distinct products, every applicable category/subcategory with positive
pagination-end evidence, observed live interruption/recovery and Azure
production runs remain outstanding.

**Code checkpoint:** October 31, 2026, Asia/Dhaka (UTC+06:00), subject to
the exact verified commit/Actions run. One-product compatibility assessment
is separately conditional on account/authorization and an independently
qualifiable retailer response. A previously discussed 5–7 working-day
planning range begins only after source connectivity AND full required
coverage qualification; it is not a guaranteed completion date.
