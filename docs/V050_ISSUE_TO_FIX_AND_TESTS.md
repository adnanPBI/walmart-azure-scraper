# v0.5.0 issue-to-fix matrix — buyer feedback of 2026-10-24/25

**Result: source-level correction candidate, NOT buyer acceptance.** The original independent reviewer ran 89 of the supplied offline tests; the latest modified suite is independently reproducible by the buyer with `python -m pytest -q`.

| Client finding | Implemented source fix | Executed offline regression | Still needed for acceptance |
|---|---|---|---|
| Missing products disappear between latest runs | `pipeline.run_store` loads previous latest catalog+product source sidecar. `report.build_report` carries forward previously eligible unobserved products with unchanged 22-field record. Source sidecar exposes original first/last observation date, last-known availability, stale price, `CARRIED_FORWARD_MISSING`. Neither stale prices nor carried rows count toward fresh 500. | Runner 600 -> 599 -> 599, also explicit OOS -> missing, loss-of-sidecar fail-closed. | Genuine repeated live store runs. |
| Digital "Save $2 each" erroneously treated as payable $2 | `extract._payable_price` refuses savings/cashback/discount descriptors. No calculated missing deal prices. | `Save $2 each`, `Save up to $2 each` → blank digital price; displayed `$3.99 each with Digital Coupon` → 3.99. | Random verified live offer comparisons. |
| Multibuy linked terms lost | `extract._promo_entries` keeps each promotion object's quantity, eligibility, household limit, validity and clipping conditions as joined source text without mixing other offers; distinct `|`-separated offers remain separate. | `2 for $5` with limit/validity/mix-and-match, separate digital coupon with clipping. | Provider's real object shape and complete words. |
| Missing pagination metadata defaults to 1 | `parse_listing` now demands positive max page, explicit no-next-page or known total covered by the current page. `report.build_report` checks all page numbers, terminal proof, full reported candidate count. | One-page no total+no pagination fails; known explicit terminal succeeds; 301 claimed vs 300 observed fails. | Real uncapped category/subcategory coverage. |
| 45% candidate threshold / 2% detail error allowance | Strict candidate set reconciliation against accepted and explicitly proven exclusions. Unresolved IDs, unknown seller/fulfillment and ANY failed required detail block PASS. Soft tolerance settings are legacy compatibility only, not publication gates. | 600 valid then single broken detail rejects pointer; one unobserved candidate rejects pointer. | Live branch reconciliation and price shard coverage. |
| Multipack loses pack count | `get_weight` first captures complete displayed count+unit phrase from title, preferring it over short inner size; does not invent a computed total. | `12 pack of 12 fl oz cans`, `6 x 16.9 fl oz bottles`. | Live source pack-size examples. |
| Classic Oxylabs route absent | New `oxylabs_classic.py`, CLI `oxylabs-probe` and `oxylabs-review`. Classic Basic-auth realtime POST, `source=walmart`, optional `walmart_product`. Two explicit opt-in flags for billable calls; caps and receipts. | Default zero-request dry-run, expected payload, 401/503, sanitized full body, API size/time/retry limit checks. | Buyer approval/credentials, 1 genuine provider response, Waukegan #3891 + PICKUP + price confirmation. |
| Evidence and Azure scope ambiguous | Receipt binds source payload, expected Waukegan store, provider job ID, original raw hash, full sanitized body, field proof. Azure remains manual-only, unapproved; no credential storage or schedule changes. | Source compilation and offline probes. | Client observed live recovery, Azure controlled manual job and later twice-weekly scheduling approval. |

## Pass/fail interpretation

A successful offline test proves only the behavior of the supplied code against synthetic data. It does **not** verify Walmart storefront correctness, Classic account compatibility, actual price/PPM terms, consent to paid requests, full production category scope, or Azure execution. Synthetic 600-item runs are **NOT** 500 genuine Walmart records. The user-provided client requirements continue to govern all live acceptance.

## Outstanding independent work

1. Real Classic response sample (no credentials shared in ZIP); verify provider returns HTML with source store ID 3891 and explicit pickup price/offer information.
2. Human source-vs-record price, PPM, and promotion comparisons, including direct deal terms and any blocked items.
3. Complete, human-reviewed navigation inventory for every required category and subcategory, exclusions propagated.
4. Full genuine 500 distinct product sample plus candidate/detail evidence, zero missing branches and price proof.
5. Observed cut/restart with durable checkpoints, repeat run with actual disappearances/out-of-stock, last-good pointer audit.
6. Separate Azure job deployment, managed identity/storage, no-overlap scheduling, logs and cost qualification after approval.

Status at issue of this ZIP: **Genuine verified products 0; paid Oxylabs calls 0; actual Azure jobs 0; live observed recovery 0**.
