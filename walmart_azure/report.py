"""Evidence-backed report and conservative publication gates."""
from __future__ import annotations
from collections import defaultdict, Counter
from datetime import datetime, timezone
import hashlib
import json
import re
from .config import Config, Store
from .extract import product_id
from .schema import FIELDS, validate_record


def record_identity(record: dict) -> str:
    """Item ID is preferred; UPC is only a fallback identity, never a replacement GUPC."""
    found = re.search(r'/ip/(?:[^/?]+/)?(\d{5,20})(?:[/?#]|$)', record.get('url', ''))
    return found.group(1) if found else (record.get('upc') or record.get('url') or '')


def build_report(store: Store, config: Config, chunks: list[dict], previous: dict | None,
                 elapsed_seconds: float, run_id: str, *, previous_catalog: list[dict] | None = None,
                 previous_sources: dict | None = None) -> tuple[list[dict], dict]:
    all_records = []
    by_category_raw = defaultdict(set)
    by_category_proven = defaultdict(set)
    memberships = defaultdict(set)
    by_shard = defaultdict(set)
    skipped = Counter()
    total_detail_attempted = 0
    total_detail_failed = 0
    total_duplicates = 0
    latest_by_id = {}
    states_by_id = {}
    valid_urls = set()
    source_hashes = []
    observed_proofs = []
    shard_stats = {}
    for chunk in chunks:
        category_key = chunk['category_key']
        cat = (chunk['category'], chunk['sub_category'])
        shard_stats.setdefault(category_key, {'category': cat[0], 'sub_category': cat[1],
                                             'page_count': 0, 'reported_count': None, 'candidate_ids': set(),
                                             'accepted_ids': set(), 'last_max_page': 0,
                                             'page_numbers': set(), 'terminal_page_proven': False,
                                             'explicit_excluded_ids': set(), 'unresolved_candidate_ids': set(),
                                             'unidentified_candidates': 0})
        stat = shard_stats[category_key]
        stat['page_count'] += 1
        stat['page_numbers'].add(chunk.get('page', 0))
        stat['terminal_page_proven'] |= bool(chunk.get('terminal_pagination_evidence'))
        stat['explicit_excluded_ids'].update(map(str, chunk.get('explicitly_excluded_ids', {})))
        stat['unresolved_candidate_ids'].update(map(str, chunk.get('unresolved_candidate_ids', {})))
        stat['unidentified_candidates'] += chunk.get('unidentified_candidates', 0)
        stat['last_max_page'] = max(stat['last_max_page'], chunk.get('max_page', 1))
        if chunk.get('reported_count') is not None and (stat['reported_count'] is None or stat['page_count'] == 1):
            stat['reported_count'] = chunk['reported_count']
        stat['candidate_ids'].update(map(str, chunk.get('candidate_ids', [])))
        source_hashes.append({'page': chunk['url'], 'sha256': chunk['page_hash']})
        observed_proofs.append(chunk['proof'])
        skipped.update(chunk.get('skipped', {}))
        total_detail_attempted += chunk.get('detail_attempted', 0)
        total_detail_failed += chunk.get('detail_failed', 0)
        for item in chunk['records']:
            rec = item['record']
            pid = record_identity(rec)
            by_shard[category_key].add(pid)
            by_category_proven[cat].add(pid)
            memberships[cat].add(pid)
            if pid in latest_by_id:
                total_duplicates += 1
                # Keep the first valid record and its original classification / URLs.
            else:
                latest_by_id[pid] = rec
                states_by_id[pid] = item.get('availability_state') or ('AVAILABLE' if rec.get('regular_price') else 'UNKNOWN')
                all_records.append(rec)
    # The latest catalog must retain previously proven assortment even when a
    # product disappears entirely from today's category listing. Provenance is
    # mandatory; a missing/unknown previous sidecar invalidates publication.
    fresh_observed = len(all_records)
    fresh_price_count = sum(bool(r.get('regular_price')) and states_by_id.get(record_identity(r)) == 'AVAILABLE'
                            for r in all_records)
    prior_by_id = {
        r.get('product_id'): r for r in (previous_sources or {}).get('records', [])
        if isinstance(r, dict) and r.get('product_id')
    }
    carried_forward = []
    carry_errors = []
    for old in previous_catalog or []:
        if not isinstance(old, dict):
            carry_errors.append('invalid_prior_record')
            continue
        pid = record_identity(old)
        if not pid:
            carry_errors.append('prior_record_without_identity')
            continue
        if pid in latest_by_id:
            continue
        source = prior_by_id.get(pid, {})
        proof = source.get('detail_proof') if isinstance(source, dict) else {}
        if (not isinstance(proof, dict) or
            proof.get('store_id') != store.id or proof.get('fulfillment') != 'PICKUP' or
            source.get('url') != old.get('url') or
            source.get('availability') not in ('AVAILABLE','UNAVAILABLE')):
            carry_errors.append('unverifiable_previous_source:' + pid)
            continue
        if validate_record(old, strict=False):
            carry_errors.append('invalid_previous_record:' + pid)
            continue
        latest_by_id[pid] = old
        states_by_id[pid] = 'UNAVAILABLE'
        all_records.append(old)  # original crawl_date remains untouched
        by_category_proven[(old.get('category',''), old.get('sub_category',''))].add(pid)
        carried_forward.append({
            'product_id': pid, 'source_run_id': source.get('last_observed_run_id') or (previous or {}).get('run_id'),
            'first_observed_date': source.get('first_observed_date') or old.get('crawl_date'),
            'last_observed_date': source.get('last_observed_date') or old.get('crawl_date'),
            'observation_state': 'CARRIED_FORWARD_MISSING',
            'price_is_historical': True,
        })
    reasons = ['carry_forward_provenance_error:' + x for x in carry_errors]
    # A parent landing page does not prove recursive subcategory coverage.
    # Even 500 parent-page products cannot satisfy the client's ALL-subcategory scope.
    if any(c.requires_subcategory_discovery for c in config.categories):
        pending = [c.name for c in config.categories if c.requires_subcategory_discovery]
        reasons.append('subcategory_discovery_unverified:' + ','.join(pending))
    # Every expected configured shard (not just a category label) must finish.
    for category in config.categories:
        stat = shard_stats.get(category.key)
        if not stat:
            reasons.append(f'missing_category:{category.name}/{category.subcategory}/{category.key}')
            continue
        if len(by_shard[category.key]) < config.limits.min_category_records:
            reasons.append(f'thin_category:{category.key}:{len(by_shard[category.key])}')
        actual = len(stat['candidate_ids'])
        reported = stat['reported_count']
        if reported is not None and actual < reported:
            reasons.append(f'pagination_truncation_or_thin_result:{category.key}:{actual}/{reported}; no threshold allowed')
        if stat['page_numbers'] != set(range(1, stat['last_max_page'] + 1)):
            reasons.append(f'incomplete_page_sequence:{category.key}')
        if not stat['terminal_page_proven']:
            reasons.append(f'pagination_terminal_not_proven:{category.key}')
        if stat['unidentified_candidates']:
            reasons.append(f'unidentified_listing_candidates:{category.key}:{stat["unidentified_candidates"]}')
        unresolved = stat['unresolved_candidate_ids']
        resolved = by_shard[category.key] | stat['explicit_excluded_ids']
        missing = stat['candidate_ids'] - resolved
        if unresolved or missing:
            reasons.append(f'unresolved_candidates:{category.key}:{len(unresolved | missing)}')
    # Historical prices on carried products are not fresh store price evidence.
    priced_count = fresh_price_count
    unavailable_count = sum(state == 'UNAVAILABLE' for state in states_by_id.values())
    unpriced_unavailable_count = sum(states_by_id[record_identity(rec)] == 'UNAVAILABLE' and not rec.get('regular_price') for rec in all_records)
    if priced_count < config.limits.min_total_records:
        reasons.append(f'below_minimum_priced_records:{priced_count}<{config.limits.min_total_records}')
    if total_detail_failed:
        reasons.append(f'required_detail_failed:{total_detail_failed}/{total_detail_attempted}; zero-tolerance')
    if config.limits.require_stable_store_proof:
        for proof in observed_proofs:
            if proof.get('store_id') != store.id or proof.get('fulfillment') != 'PICKUP':
                reasons.append('missing_store_or_pickup_proof')
                break
    if previous and previous.get('status') == 'PASS':
        previous_total = int(previous.get('total_unique', 0))
        if previous_total and fresh_observed < config.limits.min_total_vs_last_good * previous_total:
            reasons.append(f'total_yield_drop:{fresh_observed}/{previous_total}')
        previous_counts = previous.get('category_counts', {})
        for cat in config.categories:
            key = f'{cat.name} | {cat.subcategory}'
            last = previous_counts.get(key)
            # Fresh observations alone determine whether a category disappeared;
            # carry-forward is not allowed to hide a bad crawl.
            current = len(by_shard[cat.key])
            if last and current < int(last) * config.limits.min_category_vs_last_good:
                reasons.append(f'category_yield_drop:{key}:{current}/{last}')
    observed = set(latest_by_id)
    if store.canary_item_ids and not set(store.canary_item_ids).intersection(observed):
        reasons.append(f'canary_missing:{list(store.canary_item_ids)}')
    invalid = []
    for idx, record in enumerate(all_records):
        issues = validate_record(record, strict=states_by_id.get(record_identity(record)) != 'UNAVAILABLE')
        if issues:
            invalid.append({'index': idx, 'issues': issues, 'url': record.get('url')})
    if invalid:
        reasons.append(f'invalid_records:{len(invalid)}')
    completeness = {}
    for name in FIELDS:
        nonempty = sum(bool(x.get(name)) for x in all_records)
        completeness[name] = {'nonempty': nonempty, 'percentage': round(nonempty / len(all_records) * 100, 2) if all_records else 0.0}
    examples = {}
    for title, predicate in (
        ('ppm', lambda x: bool(x['ppm'])),
        ('volume_deal', lambda x: bool(x['volume_deals_description'])),
        ('digital_deal', lambda x: bool(x['digital_deals_description'])),
        ('without_deals', lambda x: not x['digital_deals_description'] and not x['volume_deals_description']),
    ):
        matches = [dict(url=r['url'], product_title=r['product_title'], ppm=r['ppm'],
                        volume=r['volume_deals_description'], digital=r['digital_deals_description'])
                   for r in all_records if predicate(r)]
        examples[title] = matches[:3]
    report = {
        'run_id': run_id, 'store_id': store.id, 'zipcode': store.zipcode,
        'previous_good_run_id': previous.get('run_id') if previous else None,
        'status': 'FAIL' if reasons else 'PASS', 'reasons': reasons,
        'total_unique': len(all_records), 'fresh_unique': fresh_observed,
        'carried_forward_count': len(carried_forward), 'carried_forward': carried_forward,
        'historical_price_values_not_current': sum(bool(latest_by_id[x['product_id']].get('regular_price')) for x in carried_forward),
        'priced_record_count': priced_count,
        'unavailable_count': unavailable_count, 'unpriced_unavailable_count': unpriced_unavailable_count,
        'duplicate_count': total_duplicates,
        'runtime_seconds': round(elapsed_seconds, 2),
        'category_counts': {f'{c} | {s}': len(ids) for (c, s), ids in by_category_proven.items()},
        'fresh_category_counts': {
            f'{c.name} | {c.subcategory}': len(by_shard[c.key]) for c in config.categories},
        'historically_carried_category_counts': {
            f'{c} | {sub}': sum(1 for item in carried_forward
                               if latest_by_id[item['product_id']].get('category') == c
                               and latest_by_id[item['product_id']].get('sub_category') == sub)
            for c, sub in {(latest_by_id[item['product_id']].get('category',''),
                            latest_by_id[item['product_id']].get('sub_category',''))
                           for item in carried_forward}},
        'shard_coverage': {key: {
                                  **{k: v for k,v in st.items() if k not in (
                                      'candidate_ids','accepted_ids','page_numbers',
                                      'explicit_excluded_ids','unresolved_candidate_ids')},
                                  'candidate_ids_unique': len(st['candidate_ids']),
                                  'accepted_ids_unique': len(by_shard[key]),
                                  'explicitly_excluded_count': len(st['explicit_excluded_ids']),
                                  'unresolved_candidate_ids': sorted(st['unresolved_candidate_ids']),
                                  'page_numbers': sorted(st['page_numbers']),
                                  'reconciliation_complete': (
                                      not st['unresolved_candidate_ids'] and
                                      not (st['candidate_ids'] - (by_shard[key] | st['explicit_excluded_ids'])) and
                                      st['unidentified_candidates'] == 0),
                              } for key, st in shard_stats.items()},
        'field_completeness': completeness, 'examples': examples,
        'skipped': dict(skipped), 'detail_attempted': total_detail_attempted,
        'detail_failed': total_detail_failed, 'page_count': len(chunks),
        'source_page_hashes': source_hashes, 'store_proofs': observed_proofs,
        'invalid_record_examples': invalid[:20],
        'run_completed_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    return all_records, report
