# Live interruption and restart acceptance protocol (NOT YET EXECUTED)

This procedure may be executed only after authorized live category access, complete reviewed subcategory inputs, and proven #3891 PICKUP price context exist. **Do not run when Walmart returns `/blocked`.** Offline fixture restart tests do not satisfy this test.

1. Identify an existing `output/latest/3891.json` and record its SHA-256 and `run_id`. If none exists, record `not present`. Do not publish synthetic data merely to create a baseline.
2. Start `python -m walmart_azure run --store 3891 --categories config/reviewed_full_categories.csv --stores config/stores.yaml --storage local --output output --run-id live-resume-001` using an approved complete manifest. Preserve JSONL process logs (stdout/stderr).
3. Wait until at least one complete page checkpoint is durably written under `output/runs/3891/live-resume-001/pages/.../page-0001.json`, noting its SHA-256, category, page number, config fingerprint and current page totals. **Do not interrupt before a page checkpoint exists.**
4. Stop the single process using Ctrl+C (graceful interrupt), and confirm there is no new `latest/3891.json` pointer and any existing last-good hash is unchanged. Capture the interruption time and process exit status.
5. Restart **the same run_id**, **same reviewed category CSV**, **same store and config**. Confirm `resume_checkpoint` log references the saved page and that its hash stays unchanged, while later pages are fetched and checkpointed normally.
6. Only if the entire live run passes complete category/store/price/validation gates, compare the new `products.json`, `report.json`, `product_source_evidence.json`, and `evidence.json` with raw source proof and verify any new `latest/3891.json` pointer.
7. Repeat one new run-id with identical config. Confirm no duplicate product IDs, reasonable yield and per-category counts, stable pickup context, and last-good safeguards. Introduce a controlled invalid category or invalid store scenario in separate staging output and ensure the original good pointer is retained.
8. Record independent reviewer name, timestamp, UTC timezone, execution machine, storage location, output and checkpoint hashes, raw (sanitized) price-bearing response proofs, and result PASS/FAIL for each step. A failure in any step means **no live recovery acceptance**.

**Current status:** Procedure specified, not executed. Walmart #3891 category access is blocked in the RND diagnostic. No genuine catalog or last-good data is present in the package.
