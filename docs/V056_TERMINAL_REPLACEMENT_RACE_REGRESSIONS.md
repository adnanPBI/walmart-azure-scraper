# v0.5.6 — terminal replacement ownership and fault-injection QA

**Date:** October 30, 2026 (Asia/Dhaka, UTC+06:00), after the original
18:00 code/offline checkpoint. **No authorized paid calls, Walmart collection
or Azure jobs.**

## Client reproduction and source correction

v0.5.5 staged **positive** bytes in a `.terminal.tmp` file. Its daemon
checked the deadline immediately before `os.replace(tmp, receipt)`. The
watchdog could time out and return a negative result while an injected
replacement was paused, then that replacement could resume and leave the
canonical receipt in **positive COMPLETED** state. Markers such as
`receipt_finalized=true` did not prevent this race.

v0.5.6 removes the underlying authority:

1. The core worker persists only an **unqualified** snapshot. The durable
   fixed approval ledger still reserves a potential billable call BEFORE
   network dispatch. Interrupted, uncertain or failed calls are never
   automatically retried and do not restore allowance.
2. The daemon finalizer writes a scrubbed `PENDING` receipt through the
   original `*.terminal.tmp` rename seam. **No positive payload is present
   on that in-flight rename.** A late swap after timeout can only write an
   unqualified receipt.
3. The supervising `run_probe` caller joins that staging thread within
   the deadline. It is **the only actor** allowed to synchronously commit a
   positive canonical receipt (`*.supervisor.tmp` -> receipt), and only
   when staging completed before the deadline.
4. A delayed or failing supervised commit is checked before returning;
   a detected overrun is synchronously scrubbed to an unqualified receipt.
   No daemon can promote success after the caller has returned deadline.
5. Saved success must match the return, with
   `receipt_finalized=true`, `finalization_state=COMPLETE`, source-shape
   count 1 **only in synthetic control**, `genuine_products_verified=0`
   and `buyer_acceptance=false`.

### Regression tests

`python -m pytest -q tests/test_release_v055.py tests/test_release_v056.py`

- `test_terminal_rename_inflight_cannot_publish_late_success[before_replace]`:
  stop inside `os.replace(.terminal.tmp, receipt)` **before** swap,
  allow one-second watchdog to return, then resume actual swap. Canonical
  receipt stays pending/failed; no verified count or completed marker.
- `test_terminal_rename_inflight_cannot_publish_late_success[after_real_replace]`:
  perform the actual rename first, then stop before `os.replace` returns.
  Watchdog times out, and receipt stays pending both before and after resume.
- `test_only_calling_thread_can_commit_positive_receipt`:
  intercept actual writes, assert the daemon's `.terminal.tmp` bytes are
  unqualified and the `.supervisor.tmp` successful commit occurs only
  on the calling thread. Saved and returned positive synthetic control match.
- Existing v0.5.5 paused intermediate save, expired-watchdog no-receipt-read,
  canceled pre-publisher, and negative provider-response tests remain.

These are synthetic or localhost-only tests. No independent source
authentication or retailer price evidence is implied.

### Deadline model and filesystem limitation

The client-visible watchdog still bounds the concurrent core and fail-closed
staging phases. The final positive filesystem rename runs synchronously in
the supervising caller to prevent **any post-timeout daemon success
publication**. As with all synchronous filesystem calls, an indefinitely
blocked OS-level rename cannot simultaneously guarantee a hard caller
return deadline without process-level isolation. We prefer **no late
positive verdict** to fabricating such a guarantee. An in-progress or
missing terminal receipt is always unqualified and its allowance spent.

### One-product Classic diagnostic

Client-nominated Great Value Whole Vitamin D Milk, Gallon:
`product_id=10450114`,
`https://www.walmart.com/ip/10450114`.
Its Waukegan #3891 PICKUP availability and price are **not independently
observed or verified**.

Proposed, *unexecuted*, Classic payload:
```json
{"source":"walmart_product","product_id":"10450114",
 "store_id":"3891","fulfillment_type":"pickup","parse":false,"render":""}
```

Max **one** billable request, **zero** retries, **90** seconds and
**2,000,000** response bytes. No automatic rendering, other item,
additional categories, schedule, credentials or Azure access is authorized.
Store/PICKUP price/PPM/offer provenance must come from returned raw HTML
and strict `qualify_envelope` proof, not from configured parameters.

## Remaining acceptance

Client-approved paid Classic response, actual #3891 PICKUP price and PPM,
Classic production runner integration, 500 genuine distinct products, every
applicable category/subcategory/pagination branch, observed live recovery
and Azure production runs remain outstanding. Historical unavailable and
later-missing eligible records remain retained, distinct from fresh counts.
22-field JSON, empty strings, blank gupc/unit_price and full separate
promotion terms are unchanged.

The source/CI checkpoint is after October 30, 2026 18:00 Asia/Dhaka
(UTC+06:00), not a retroactive claim of completing live work. The
previously discussed 5–7 working days start only **after** connectivity
AND category coverage are qualified; no guaranteed live completion date.
