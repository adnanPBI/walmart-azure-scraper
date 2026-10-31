# Classic Oxylabs diagnostic plan — v0.5.7 (2026-10-31)

**Current authoritative plan:** [CLASSIC_3891_PICKUP_QUALIFICATION_20261030.md](CLASSIC_3891_PICKUP_QUALIFICATION_20261030.md).

This replaces the old unlocalized `source=walmart` URL payload.
The supported localized product request is
`source=walmart_product`, `product_id=<observed>`,
`store_id=3891`, `fulfillment_type=pickup`,
`parse=false`, `render=""`.
It is a localization **request, not proof**; fallback store responses must
fail the strict returned-HTML source gate.

No paid credentials, spending, rendering, Azure deployment or schedule is
approved. First diagnostic is one observed product, one request, zero retries,
90 seconds for network/worker and fail-closed staging phases (NOT a hard total command wall-clock limit if synchronous final disk I/O blocks), 2 MB response. Detailed exact commands, source
proof requirements, budget policy, limits and risks are in the linked plan.

Terminal-race protection updated in v0.5.6: background staging is fail-closed; caller-only positive publication, with exact pre/post atomic-replace regressions. No paid diagnostic authorized.

**v0.5.7:** The caller-only `.supervisor.tmp` terminal commit is synchronous; an OS filesystem stall may extend caller runtime beyond `--max-seconds`. The receipt will fail closed after overrun and reserved spending will not be restored. See [phase timing contract](V057_PHASE_DEADLINE_AND_SUPERVISOR_IO.md).
