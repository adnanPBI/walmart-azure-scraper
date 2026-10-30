# Classic Oxylabs diagnostic plan — v0.5.4 (2026-10-30)

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
90 seconds absolute runtime, 2 MB response. Detailed exact commands, source
proof requirements, budget policy, limits and risks are in the linked plan.
