# v0.5.2 — Walmart review #72 issue-to-fix and evidence (2026-10-29)

All tests are SYNTHETIC or localhost-only, NOT genuine Walmart, paid Oxylabs, Azure, or live recovery results.

| Finding | Correction | Focused tests |
|---|---|---|
| PriceInfo SHIPPING verified as pickup | Check fulfillment on the actual priceInfo/currentPrice, direct PPM and every offer; pickup option elsewhere is insufficient | test_shipping_price_with_valid_pickup_option_is_not_pickup_price; test_nested_shipping_price_ppm_and_offer_never_qualify |
| Mixed shipping/pickup options with unscoped price | Require explicit pickup scope for money on mixed fulfillment products; reject unscoped PPM | test_mixed_fulfillment_untagged_money_is_ambiguous; test_mixed_fulfillment_separate_unscoped_ppm_is_rejected |
| Browser runner could publish shipping price | Apply the shared money scope guard to listing fast path and available detail records; bad required details reject publish | test_production_runner_rejects_shipping_specific_price_and_preserves_last_good |
| Same ID spent across receipt folders | Approval budget now in fixed WALMART_OXYLABS_LEDGER_ROOT rather than relative to output receipt | test_same_approval_id_cannot_dispatch_twice_across_receipt_directories |
| Missing ledger silently replaced | Explicit one-time operator approval registration required; absent/corrupt ledger fails closed | test_missing_grant_after_enrollment_fails_closed; test_enrollment_not_automatic_and_cannot_reset |
| Overlap spends twice | Exclusive filesystem lock and fsynced reservation before HTTP dispatch; uncertain attempts retained | test_overlap_two_mock_processes_at_most_one_dispatch; existing slow localhost stream test |
| parse=true dict insufficient | Classic raw HTML URL source with parse=false and matching observed URL+item ID; dict still does not certify pickup | test_provider_payload_requires_raw_html_and_exact_original_product_url; test_parsed_json_provider_result_cannot_prove_original_html |

Preserved previous tests: 600-to-599 retention with original dates, fresh-canary separation, unclipped savings not payable prices, clipped multibuy digital offers, full terms, multipacks, positive pagination completion, exact 22 fields with blank gupc/unit_price and direct PPM, no overwrite of last-good.

Test: python -m pip install -e ".[test]"; python -m pytest -q. Optional synthetic Chromium: python -m playwright install chromium; python -m pytest tests/test_browser_e2e_offline.py -v.

Outstanding: documented Classic exact Walmart #3891 PICKUP selection method; genuine provider/local price/PPM/offer evidence; Classic-to-production-runner integration; 500 unique live items; uncapped required categories/subcategories; observed live restart; Azure deployment; twice-weekly schedule. No paid calls are authorized.