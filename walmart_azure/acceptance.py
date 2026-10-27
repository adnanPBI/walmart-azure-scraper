"""Read-only external acceptance audit. This does NOT certify live provenance.

The collector's own PASS bit is not sufficient buyer evidence. The audit checks
schema, distinctness, coverage, reported count, hashes and store/pickup proof.
It explicitly distinguishes static validation from independently observed live runs.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any
from .config import load_categories
from .report import record_identity
from .schema import FIELDS, validate_record


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit_dataset(products: Any, categories: list, report: dict | None = None,
                  evidence: dict | None = None, minimum: int = 500,
                  product_sources: dict | None = None) -> dict:
    issues: list[str] = []
    warnings: list[str] = []
    if not isinstance(products, list):
        return {'status': 'FAIL_STATIC', 'issues': ['products_not_array'], 'total_records': 0}
    invalid = []
    identities: list[str] = []
    per_category: Counter = Counter()
    nonempty: Counter = Counter()
    wrong_zip = 0
    sources = {}
    if product_sources is not None:
        if not isinstance(product_sources, dict) or not isinstance(product_sources.get('records'), list):
            issues.append('malformed_product_source_sidecar')
        else:
            sources = {x['product_id']: x for x in product_sources['records']
                       if isinstance(x, dict) and isinstance(x.get('product_id'), str)}
            if report and (product_sources.get('run_id') != report.get('run_id') or
                           product_sources.get('store_id') != report.get('store_id')):
                issues.append('product_source_run_or_store_mismatch')
    price_bearing = 0
    unavailable_retained = 0
    for i, rec in enumerate(products):
        if not isinstance(rec, dict):
            invalid.append({'index': i, 'issues': ['not_object']})
            continue
        ident = record_identity(rec)
        source = sources.get(ident, {})
        explicitly_unavailable = (
            source.get('availability') == 'UNAVAILABLE' and
            source.get('price_bearing') is False and
            source.get('detail_proof', {}).get('fulfillment') == 'PICKUP' and
            (not report or source.get('detail_proof', {}).get('store_id') == str(report.get('store_id')))
        )
        if explicitly_unavailable:
            unavailable_retained += 1
        # Carried-forward values are historical, never price-bearing evidence
        # for this observed run or the buyer's fresh 500-product requirement.
        is_historical = source.get('observation_state') == 'CARRIED_FORWARD_MISSING'
        is_explicit_oos = source.get('availability') == 'UNAVAILABLE'
        if rec.get('regular_price') and not is_historical and not is_explicit_oos:
            price_bearing += 1
        errs = validate_record(rec, strict=not explicitly_unavailable)
        if errs:
            invalid.append({'index': i, 'issues': errs[:5]})
        key = record_identity(rec)
        if not key:
            invalid.append({'index': i, 'issues': ['no_stable_identity']})
        else:
            identities.append(key)
        per_category[str(rec.get('category', ''))] += 1
        for field in FIELDS:
            if rec.get(field):
                nonempty[field] += 1
        if report is not None and str(rec.get('zipcode')) != str(report.get('zipcode')):
            wrong_zip += 1
    dups = len(identities) - len(set(identities))
    if dups:
        issues.append(f'duplicate_product_ids:{dups}')
    if invalid:
        issues.append(f'invalid_records:{len(invalid)}')
    # The buyer's 500-item proof must be price-bearing and store-specific;
    # out-of-stock records with no quoted price cannot inflate the threshold.
    if price_bearing < minimum:
        issues.append(f'below_minimum_priced:{price_bearing}<{minimum}')
    required = {c.name for c in categories}
    missing = sorted(required - {c for c, count in per_category.items() if count > 0})
    if missing:
        issues.append(f'missing_parent_categories:{missing}')
    if wrong_zip:
        issues.append(f'configured_zipcode_mismatches:{wrong_zip}')
    if any(c.requires_subcategory_discovery for c in categories):
        warnings.append('parent_csv_requires_exhaustive_subcategory_discovery_not_proved_by_dataset')
    # Exclusions in original source apply even if records are labeled with a
    # generic parent category, as long as sub_category contains excluded names.
    excluded = {
        c.name: {x.casefold().strip() for x in c.exclusions}
        for c in categories if c.exclusions
    }
    excluded_found = [i for i, r in enumerate(products) if isinstance(r, dict)
                      and str(r.get('sub_category','')).casefold().strip() in
                      excluded.get(str(r.get('category','')), set())]
    if excluded_found:
        issues.append(f'excluded_subcategories_found:{len(excluded_found)}')
    if product_sources is None:
        warnings.append('product_source_sidecar_missing_price_and_availability_unverified')
    else:
        if len(sources) != len(products):
            issues.append(f'product_source_coverage_gap:{len(sources)}/{len(products)}')
        for rec in products:
            ident = record_identity(rec)
            source = sources.get(ident)
            if source is None:
                continue
            if source.get('url') != rec.get('url'):
                issues.append(f'source_url_disagrees:{ident}')
            if source.get('direct_ppm', '') != rec.get('ppm', ''):
                issues.append(f'source_ppm_disagrees:{ident}')
            if source.get('displayed_regular_price', '') != rec.get('regular_price', ''):
                issues.append(f'source_price_disagrees:{ident}')
            if source.get('observation_state') == 'CARRIED_FORWARD_MISSING':
                if source.get('current_price_verified') or not source.get('historical_prices_not_current'):
                    issues.append(f'historical_record_incorrectly_marked_current:{ident}')
    if report is None:
        warnings.append('run_report_missing')
    else:
        if report.get('status') != 'PASS':
            issues.append('run_report_not_pass')
        if report.get('total_unique') != len(products):
            issues.append('report_total_disagrees_with_dataset')
        if not report.get('source_page_hashes'):
            issues.append('no_source_page_hashes')
        proofs = report.get('store_proofs') or []
        if not proofs:
            issues.append('missing_store_proofs')
        elif any(x.get('store_id') != str(report.get('store_id')) or x.get('fulfillment') != 'PICKUP' for x in proofs):
            issues.append('store_or_pickup_proof_mismatch')
        if not report.get('category_counts'):
            issues.append('missing_category_counts')
    if evidence is None:
        warnings.append('evidence_manifest_missing')
    else:
        expected_hash = hashlib.sha256(json.dumps(products, ensure_ascii=False, indent=2).encode()).hexdigest()
        if expected_hash != evidence.get('product_json_sha256'):
            issues.append('evidence_product_hash_mismatch')
        if report is not None and (evidence.get('run_id') != report.get('run_id') or
                                   evidence.get('store') != report.get('store_id')):
            issues.append('evidence_run_or_store_mismatch')
        if evidence.get('synthetic', True) or evidence.get('runtime_adapter') == 'custom_or_test':
            issues.append('synthetic_or_custom_adapter_not_live_evidence')
        if not evidence.get('acceptance_verified'):
            warnings.append('independent_live_acceptance_not_yet_verified')
    return {
        'status': 'FAIL_STATIC' if issues else 'PASS_STATIC_ONLY',
        'buyer_acceptance': 'NOT_CERTIFIED',
        'total_records': len(products),
        'price_bearing_records': price_bearing,
        'unavailable_retained_without_price': unavailable_retained,
        'distinct_identities': len(set(identities)),
        'duplicate_product_ids': dups,
        'required_parent_categories': len(required),
        'covered_parent_categories': len(required - set(missing)),
        'per_category_records': {k:per_category[k] for k in sorted(per_category)},
        'field_nonempty_counts': {k:nonempty[k] for k in FIELDS},
        'examples_available': {
            'ppm': sum(bool(r.get('ppm')) for r in products if isinstance(r, dict)),
            'volume_deal': sum(bool(r.get('volume_deals_description')) for r in products if isinstance(r, dict)),
            'digital_deal': sum(bool(r.get('digital_deals_description')) for r in products if isinstance(r, dict)),
            'without_deals': sum(not r.get('volume_deals_description') and not r.get('digital_deals_description') for r in products if isinstance(r, dict)),
        },
        'issues': issues,
        'warnings': warnings,
        'invalid_samples': invalid[:12],
        'excluded_samples': excluded_found[:12],
    }


def run_audit(catalog: str, categories: str, report: str = '', evidence: str = '',
              minimum: int = 500, product_sources: str = '') -> dict:
    return audit_dataset(_read_json(catalog), load_categories(categories),
                         _read_json(report) if report else None,
                         _read_json(evidence) if evidence else None, minimum,
                         _read_json(product_sources) if product_sources else None)
