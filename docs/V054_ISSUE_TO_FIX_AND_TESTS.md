# v0.5.4 client finding -> fix matrix (2026-10-30)

| Client finding | Code change | Focused offline regression |
| --- | --- | --- |
| Live run_probe uses permissive legacy source checker | Paid transport now calls the same `qualify_envelope` strict gate as saved response; actual provider job ID+URL, page selected store/PICKUP, primary product and bound price/PPM/offer required | `test_live_probe_uses_exact_same_strict_saved_response_gate` and parameterized negative fixtures |
| Shipping page and missing selected pickup mode produced positive live flags | All verification flags and source-shape count derive from strict candidate status ONLY | `test_live_probe_rejects_strict_saved_gate_failures` variants |
| Response processing/cleanup fell beyond whole-run deadline | Whole-run watchdog bounds paid execution, post-transport deadline guards, bounded session.close and fail-closed supersession after final receipt write | `test_whole_run_deadline_includes_slow_session_close`, `test_whole_run_deadline_bounds_slow_response_processing` |
| URL target not localized, source=wrong target | Documented `walmart_product(product_id,store_id=3891,fulfillment_type=pickup,parse=false,render="")` request; source-observed URL retained as provenance input, NOT sent as payload URL | `test_new_documented_localized_raw_product_payload_is_exact`, existing CLI dry-run CI |
| Inconsistent v0.5.3 docs | Updated README, handoff, Instruction, capabilities, release status and current full Classic protocol | CI preflight, tests and dry-run |

All tests are synthetic or localhost-only; a passing code test never
constitutes a genuine product. The fixed durable approval ledger and no-retry
policy are unchanged. No credentials, paid jobs, Azure execution or schedule.

Still outstanding: one actual client-authorized Oxylabs Walmart #3891 PICKUP
raw-HTML response, independent price/PPM/offers verification, Classic production
runner integration, 500 genuine products across all required category branches,
observed live recovery, and Azure deployment.

Milestone **2026-10-30 18:00 Asia/Dhaka** is for code/offline CI + a
**conditional** one-product live go/no-go only. The conditional live portion
requires the client's separate approval and genuine product ID; the 5–7
working-day estimate for remaining live/production work starts only after
connectivity and coverage qualification.
