# Buyer independent-review reconciliation — v0.5.1 (2026-10-28)

All tests below are **synthetic/offline** except one **localhost-only** slow-stream fixture; none makes a Walmart, Azure or paid Oxylabs request.

| Client finding | Source correction | Regression proof |
|---|---|---|
| ZIP differs from commit, old Instruction02, pytest-asyncio missing | GitHub commit is sole authority, README/Instruction updated, `pyproject.toml` test extra includes `pytest-asyncio`; CI has three platform jobs | GitHub Actions for exact commit; `python -m pip install -e ".[test]"` and `python -m pytest -q` |
| Page store 100 vs product 3891 returned false positives | Page-selected IDs extracted independently of product; exactly one page and product store 3891, explicit matched pickup and price scope required; parsed API without source HTML never verified | `test_cross_store_page_100_product_3891_rejected`, `test_multistore_product_is_not_price_bound_to_requested_store`, conflicting scopes |
| Source URL silently substituted | Actual `results[0].url` required; returned product URL must contain requested product ID; never replace with submitted URL | `test_missing_returned_url_is_not_synthesized` |
| Whole-run deadline weak against slow trickling and paid counts can disappear | Independent watchdog around POST+stream; fsynced approval-wide ledger and exclusive receipt reserve each charge before dispatch, uncertain attempts retained, fail-closed restart and concurrency | localhost streamed-response test, reservation/reuse test |
| Category default, no primary product, store selector absent | Default no-network without product; one primary `walmart_product` job when ID supplied; explicitly disclaims unproven Classic store/PICKUP selector and production-runner integration | `test_primary_product_only_and_default_without_id_no_network`; README and provider plan |
| Historical carry-forward satisfies live canary | Canary IDs taken from fresh observations only; retained history still carried, invalid current run cannot publish | `test_carried_canary_is_not_fresh_canary` |
| Clipped MULTIBUY mistaken as volume; terms truncated | `requiresClipping`/activation outrank MULTIBUY type; full linked terms preserved, excess depth/size raises `ParseError` rather than cutting silently | `test_clipping_multibuy_is_digital_with_complete_terms_and_price`, `test_long_offer_terms_are_not_silently_truncated` |
| "Soda 12 fl oz, 12 Pack" loses count | Added source-order trailing pack-count pattern without inferred totals | `test_trailing_pack_count_preserved_and_ppm_direct_only` |

**Unresolved, NOT passed:** actual buyer Classic response, Waukegan #3891 PICKUP price verification, 500 fresh genuine distinct products, complete category and subcategory coverage, real interruption/recovery, production Classic integration, Azure deployment/scheduling. CI is offline evidence only.
