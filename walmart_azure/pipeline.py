"""Idempotent resumable crawler; failed/incomplete runs never replace last-good data."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import asyncio
import hashlib
import json
import logging
import os
import time
from .browser import WalmartBrowser, StoreMismatch, BrowserFailure, next_page_url
from .config import Config, Store, Category
from .extract import (BlockedResponse, ParseError, sponsored, product_id, product_url, seller_is_walmart,
                      pickup_availability, local_pickup_offer, make_record, approximate_weight, match_location, regular_sale)
from .report import build_report
from .schema import validate_record

logger = logging.getLogger('walmart')


def key_prefix(store: Store, run_id: str) -> str:
    if not run_id or not all(c.isalnum() or c in '-_.' for c in run_id):
        raise ValueError('Run ID must be a safe alphanumeric token')
    return f'runs/{store.id}/{run_id}'


def page_key(store: Store, run_id: str, category: Category, number: int) -> str:
    return f'{key_prefix(store, run_id)}/pages/{category.key}/page-{number:04d}.json'


async def fetch_category_page(browser: WalmartBrowser, config: Config, store: Store,
                              category: Category, number: int, url: str,
                              run_id: str, memory: dict[str, dict]) -> dict:
    """Complete the whole page then checkpoint it. Interrupted pages are re-fetched."""
    last_error = None
    for attempt in range(config.limits.page_retries + 1):
        try:
            _, meta, candidates = await browser.listing(url)
            if not candidates:
                raise ParseError(f'EMPTY category page {category.key} page={number}')
            max_page = meta['max_page']
            if config.limits.max_pages_per_category and max_page > config.limits.max_pages_per_category:
                raise ParseError(f'Safety cap {config.limits.max_pages_per_category} smaller than reported maxPage {max_page}; do not publish')
            if number > max_page:
                raise ParseError(f'Unexpected page {number} after maxPage {max_page}')
            found = []
            reasons = Counter()
            candidate_ids = set()
            excluded_candidate_ids: dict[str, str] = {}
            unresolved_candidate_ids: dict[str, str] = {}
            unidentified_candidates = 0
            detail_attempted = detail_failed = 0
            observed_at = datetime.now(timezone.utc).date().isoformat()
            for item in candidates:
                pid = product_id(item)
                if not pid:
                    reasons['no_product_id'] += 1
                    unidentified_candidates += 1
                    continue
                if sponsored(item):
                    reasons['sponsored'] += 1
                    continue
                candidate_ids.add(pid)
                # Already verified product may appear under multiple categories.
                if pid in memory:
                    copy = dict(memory[pid])
                    copy['category'] = category.name
                    copy['sub_category'] = category.subcategory
                    found.append({'id': pid, 'record': copy, 'reused_verified_detail': True,
                                  'availability_state': 'AVAILABLE' if copy.get('regular_price') else 'UNAVAILABLE',
                                  'price_bearing': bool(copy.get('regular_price'))})
                    continue
                detail_url = product_url(item)
                if not detail_url:
                    reasons['unsafe_or_missing_product_url'] += 1
                    unresolved_candidate_ids[pid] = 'unsafe_or_missing_product_url'
                    continue
                # Opt-in listing-only mode is valid *only when the listing itself*
                # carries seller + store-specific price provenance + explicit pickup.
                use_listing = (config.limits.detail_mode == 'missing_local_and_price'
                    and seller_is_walmart(item) and local_pickup_offer(item)
                    and match_location(item, store)[0] and bool(regular_sale(item)[0]))
                if use_listing:
                    rec = make_record(item, store, category, observed_at)
                    if approximate_weight(rec['weight']) or approximate_weight(str(item.get('name') or '')):
                        reasons['approximate_weight'] += 1
                        excluded_candidate_ids[pid] = 'explicit_approximate_weight'
                    elif not validate_record(rec):
                        memory[pid] = rec
                        found.append({'id':pid,'record':rec,'listing_verified':True,
                            'availability_state':'AVAILABLE', 'price_bearing':True,
                            'detail_url':detail_url,'detail_proof':meta['proof'],
                            'source_fields':{k:item[k] for k in ('name','priceInfo','sellerName','location','fulfillmentOptions','upc','promotions','imageInfo') if k in item}})
                    else:
                        reasons['invalid_listing_record'] += 1
                        unresolved_candidate_ids[pid] = 'invalid_listing_record'
                    continue
                detail_attempted += 1
                try:
                    product, proof = await browser.detail(detail_url, pid)
                    if not seller_is_walmart(product):
                        reasons['third_party_or_unknown_seller'] += 1
                        if product.get('sellerName') or (product.get('sellerInfo') or {}).get('name'):
                            excluded_candidate_ids[pid] = 'explicit_third_party_seller'
                        else:
                            unresolved_candidate_ids[pid] = 'unverified_seller'
                        continue
                    availability = pickup_availability(product)
                    if availability == 'UNKNOWN':
                        reasons['no_explicit_local_pickup_or_shipping_only'] += 1
                        options = product.get('fulfillmentOptions') or []
                        explicit_shipping_only = bool(options) and all(
                            isinstance(option, dict) and
                            'SHIPPING' in str(option.get('type') or option.get('fulfillmentType') or '').upper()
                            for option in options)
                        if explicit_shipping_only:
                            excluded_candidate_ids[pid] = 'explicit_shipping_only'
                        else:
                            unresolved_candidate_ids[pid] = 'no_verified_pickup_or_unavailability'
                        continue
                    # Known unavailable products are retained with a sidecar flag;
                    # a missing store-local price is never fabricated or counted as priced.
                    # Prefer detail payload, but preserve explicitly surfaced promotions/size
                    # on the listing if product detail does not expose those fields.
                    for k in ('promotions', 'promotionInfo', 'badges', 'coupon', 'coupons', 'size', 'sizeDisplay'):
                        if not product.get(k) and item.get(k):
                            product[k] = item[k]
                    record = make_record(product, store, category, observed_at)
                    if approximate_weight(record['weight']) or approximate_weight(str(product.get('name') or '')) or approximate_weight(str(product.get('size') or '')):
                        reasons['approximate_weight'] += 1
                        excluded_candidate_ids[pid] = 'explicit_approximate_weight'
                        continue
                    issues = validate_record(record, strict=availability == 'AVAILABLE')
                    if issues:
                        reasons['invalid_record:' + ','.join(issues[:2])] += 1
                        unresolved_candidate_ids[pid] = 'invalid_required_detail:' + ','.join(issues[:2])
                        continue
                    memory[pid] = record
                    # Audit-only source fields are directly observed in PDP hydration;
                    # downstream normalized fields can be checked against them.
                    source_fields = {k: product.get(k) for k in (
                        'usItemId','name','upc','brand','sellerName','sellerType',
                        'location','fulfillmentOptions','priceInfo','promotions',
                        'promotionInfo','badges','coupon','coupons','imageInfo','size') if k in product}
                    found.append({'id': pid, 'record': record, 'availability_state': availability,
                                  'detail_proof': proof.as_dict(), 'detail_url': product_url(item),
                                  'price_bearing': bool(record['regular_price']),
                                  'source_fields': source_fields})
                except (BlockedResponse, StoreMismatch):
                    # One corrupted store or challenge invalidates *whole* run.
                    raise
                except (ParseError, BrowserFailure, TimeoutError, ValueError) as exc:
                    detail_failed += 1
                    logger.warning('detail_error %s', json.dumps({'item_id': pid, 'error': str(exc)}))
                    reasons['detail_error'] += 1
                    unresolved_candidate_ids[pid] = 'detail_error:' + type(exc).__name__
            chunk = {
                'config_fingerprint': config.fingerprint, 'category': category.name,
                'sub_category': category.subcategory, 'category_key': category.key,
                'page': number, 'url': url,
                'next_url': next_page_url(category.browse_url, number + 1) if number < max_page else '',
                'page_hash': meta['proof']['hash'], 'proof': meta['proof'],
                'max_page': max_page, 'reported_count': meta['reported_count'],
                'http_status': meta.get('http_status',200),
                'candidate_ids': sorted(candidate_ids), 'records': found,
                'explicitly_excluded_ids': excluded_candidate_ids,
                'unresolved_candidate_ids': unresolved_candidate_ids,
                'unidentified_candidates': unidentified_candidates,
                'terminal_pagination_evidence': bool(number == max_page and max_page >= 1),
                'skipped': dict(reasons), 'detail_attempted': detail_attempted,
                'detail_failed': detail_failed,
            }
            logger.info('page_done %s', json.dumps({
                'store':store.id, 'category_key':category.key, 'page':number,
                'candidates':len(candidate_ids), 'valid':len(found),
                'skipped':dict(reasons), 'next':chunk['next_url'], 'pickup':meta['proof']['fulfillment']}))
            return chunk
        except (BlockedResponse, StoreMismatch):
            raise
        except Exception as exc:
            last_error = exc
            if attempt == config.limits.page_retries:
                break
            delay = min(40, 2 ** attempt * 3)
            logger.warning('page_retry %s', json.dumps({'category':category.key,'page':number,
                                                         'attempt':attempt+1,'sleep':delay,'error':str(exc)}))
            await asyncio.sleep(delay)
    raise BrowserFailure(f'Category {category.key} page {number} failed after retries: {last_error}')


async def run_store(store: Store, config: Config, storage, run_id: str, headless: bool = True,
                    browser_type=WalmartBrowser) -> dict:
    start = time.monotonic()
    prefix = key_prefix(store, run_id)
    all_chunks = []
    memory: dict[str, dict] = {}
    with storage.store_lock(store.id):
        prior = storage.load(f'latest/{store.id}.json')
        previous_catalog, previous_sources = None, None
        if prior and prior.get('status') == 'PASS':
            if prior.get('store_id') != store.id or not prior.get('run_id'):
                raise ParseError('Last-good pointer store identity inconsistent; stop before collection')
            old_prefix = key_prefix(store, prior['run_id'])
            previous_catalog = storage.load(prior.get('products_key') or f'{old_prefix}/products.json')
            previous_sources = storage.load(f'{old_prefix}/product_source_evidence.json')
            previous_evidence = storage.load(prior.get('evidence_key') or f'{old_prefix}/evidence.json')
            if not isinstance(previous_catalog, list) or not isinstance(previous_sources, dict) or not isinstance(previous_evidence, dict):
                raise ParseError('Previous good catalog/evidence missing: cannot safely carry product assortment')
            if previous_sources.get('store_id') != store.id or previous_evidence.get('store') != store.id:
                raise ParseError('Previous good source evidence belongs to another store')
            expected_runtime = 'playwright_live' if browser_type is WalmartBrowser else 'custom_or_test'
            if previous_sources.get('source_kind') != expected_runtime:
                raise ParseError('Cannot merge live and synthetic/runtime-incompatible product provenance')
        completed = storage.load(f'{prefix}/report.json')
        if completed and completed.get('status') == 'PASS':
            # Recovery from crash between durable report/evidence write and final pointer publish.
            evidence = storage.load(f'{prefix}/evidence.json')
            existing = storage.load(f'{prefix}/products.json')
            source_sidecar = storage.load(f'{prefix}/product_source_evidence.json')
            if (not evidence or evidence.get('config_fingerprint') != config.fingerprint or
                    not isinstance(existing, list) or not isinstance(source_sidecar, dict) or
                    len(source_sidecar.get('records', [])) != len(existing)):
                raise ParseError('Previously passed run missing catalog, source evidence or matching config; refuse republish')
            if not (prior and prior.get('run_id') == run_id):
                # Only repair an interrupted publish if the previous good pointer
                # still matches the one observed by the original PASS report.
                if (prior.get('run_id') if prior else None) != completed.get('previous_good_run_id'):
                    raise ParseError('A newer good run is already published; do not roll back to stale run ID')
                storage.publish(store.id, {'status':'PASS','run_id':run_id,'store_id':store.id,
                                           'total_unique':completed['total_unique'],
                                           'category_counts':completed['category_counts'],
                                           'products_key':f'{prefix}/products.json',
                                           'report_key':f'{prefix}/report.json',
                                           'evidence_key':f'{prefix}/evidence.json',
                                           'published_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')})
                logger.info('recovered_passed_publication store=%s run=%s', store.id, run_id)
            return completed
        try:
            async with browser_type(store, config.limits, headless=headless) as browser:
                init = await browser.select_store()
                logger.info('store_selected %s', json.dumps(init.as_dict()))
                for cat in config.categories:
                    page = 1
                    url = cat.browse_url
                    first_max = None
                    seen_page_hashes: set[str] = set()
                    while url:
                        if config.limits.max_pages_per_category and page > config.limits.max_pages_per_category:
                            raise ParseError(f'Safety cap reached without completion in {cat.key}')
                        key = page_key(store, run_id, cat, page)
                        chunk = storage.load(key)
                        if chunk is None:
                            chunk = await fetch_category_page(browser, config, store, cat, page, url, run_id, memory)
                            storage.write(key, chunk)
                        else:
                            if chunk.get('config_fingerprint') != config.fingerprint or chunk['url'] != url or chunk['page'] != page:
                                raise ParseError('Checkpoint config/url mismatch; use a new run ID to avoid mixing data')
                            logger.info('resume_checkpoint store=%s cat=%s page=%s', store.id, cat.key, page)
                        if first_max is None:
                            first_max = chunk['max_page']
                        if chunk['max_page'] < first_max:
                            raise ParseError(f'Silent pagination shrink {first_max} -> {chunk["max_page"]}')
                        if chunk.get('page_hash') in seen_page_hashes:
                            raise ParseError(f'Repeated page source hash in {cat.key}; possible pagination loop')
                        seen_page_hashes.add(chunk.get('page_hash'))
                        all_chunks.append(chunk)
                        for element in chunk['records']:
                            memory.setdefault(element['id'], element['record'])
                        url = chunk['next_url']
                        page += 1
            products, report = build_report(store, config, all_chunks, prior,
                                            time.monotonic() - start, run_id,
                                            previous_catalog=previous_catalog,
                                            previous_sources=previous_sources)
            # Immutable artifacts are always saved for audit, regardless of PASS/FAIL.
            storage.write(f'{prefix}/products.json', products, overwrite=True)
            # Write report LAST, after evidence and product sidecar, so a PASS
            # report is a durable completion marker for crash-safe republish.
            evidence = {
                'run_id': run_id, 'store':store.id, 'config_fingerprint':config.fingerprint,
                'category_input_urls': [c.browse_url for c in config.categories],
                'page_sha256': report['source_page_hashes'],
                'product_json_sha256': hashlib.sha256(json.dumps(products, ensure_ascii=False, indent=2).encode()).hexdigest(),
                'proof_count': len(report['store_proofs']),
                'source': 'Live browser page hydration; detail pages for local offer and price confirmation',
                # A custom/mock browser must never automatically declare a live source.
                # Real collection still requires independent human verification.
                'runtime_adapter': 'playwright_live' if browser_type is WalmartBrowser else 'custom_or_test',
                'synthetic': browser_type is not WalmartBrowser,
                'acceptance_verified': False,
            }
            storage.write(f'{prefix}/evidence.json', evidence, overwrite=True)
            # Kept separate from exact 22-field client export: availability, source
            # price model, location and fulfillment; never reconstruct PPM or prices.
            previous_provenance = {
                r.get('product_id'): r for r in (previous_sources or {}).get('records', [])
                if isinstance(r, dict) and r.get('product_id')
            }
            product_sources = {}
            for chunk in all_chunks:
                for item in chunk.get('records', []):
                    prior_source = previous_provenance.get(item['id'], {})
                    product_sources.setdefault(item['id'], {
                        'product_id': item['id'], 'url': item['record'].get('url'),
                        'observation_state': 'OBSERVED_THIS_RUN',
                        'first_observed_date': prior_source.get('first_observed_date') or item['record'].get('crawl_date'),
                        'last_observed_date': item['record'].get('crawl_date'),
                        'current_price_verified': bool(item.get('price_bearing', False)),
                        'availability': item.get('availability_state', 'UNKNOWN'),
                        'price_bearing': item.get('price_bearing', bool(item['record'].get('regular_price'))),
                        'direct_ppm': item['record'].get('ppm', ''),
                        'displayed_regular_price': item['record'].get('regular_price', ''),
                        'displayed_sale_price': item['record'].get('sale_price', ''),
                        'detail_url': item.get('detail_url', ''),
                        'page': chunk.get('url', ''),
                        'page_sha256': chunk.get('page_hash', ''),
                        'detail_proof': item.get('detail_proof', {}),
                        'source_fields': item.get('source_fields', {}),
                        'evidence_type': 'reused_existing_provenance' if item.get('reused_verified_detail') else
                                         ('listing_source' if item.get('listing_verified') else 'product_detail'),
                    })
            for carried in report.get('carried_forward', []):
                pid = carried['product_id']
                prior_source = previous_provenance.get(pid)
                if not prior_source:
                    raise ParseError('No verified prior product provenance for carry-forward ' + pid)
                new_source = dict(prior_source)
                new_source.update({
                    'observation_state': 'CARRIED_FORWARD_MISSING',
                    'availability': 'UNAVAILABLE',
                    'last_known_availability': prior_source.get('last_known_availability') or prior_source.get('availability'),
                    'current_price_verified': False,
                    'price_bearing': False,
                    'first_observed_date': prior_source.get('first_observed_date') or carried['first_observed_date'],
                    'last_observed_date': prior_source.get('last_observed_date') or carried['last_observed_date'],
                    'last_observed_run_id': prior_source.get('last_observed_run_id') or prior.get('run_id'),
                    'carried_into_run_id': run_id,
                    'evidence_type': 'historical_verified_provenance_not_current_source',
                    'historical_prices_not_current': True,
                    'current_pickup_observed': False,
                })
                product_sources[pid] = new_source
            storage.write(f'{prefix}/product_source_evidence.json', {
                'store_id': store.id, 'run_id': run_id, 'source_kind': evidence['runtime_adapter'],
                'records': list(product_sources.values()),
                'note': 'Carried-forward prices are HISTORICAL and do not count as current verified price-bearing records. Synthetic fixtures are never retailer evidence.'
            }, overwrite=True)
            storage.write(f'{prefix}/report.json', report, overwrite=True)
            if report['status'] == 'PASS':
                # The only mutable object is an atomic pointer to the verified run.
                storage.publish(store.id, {'status':'PASS', 'run_id':run_id, 'store_id':store.id,
                                           'total_unique':len(products),
                                           'fresh_unique':report['fresh_unique'],
                                           'carried_forward_count':report['carried_forward_count'],
                                           'category_counts':report['category_counts'],
                                           'products_key':f'{prefix}/products.json',
                                           'report_key':f'{prefix}/report.json',
                                           'evidence_key':f'{prefix}/evidence.json',
                                           'published_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')})
            else:
                logger.error('PUBLISH_REJECTED %s', json.dumps({'store':store.id, 'run_id':run_id,
                                                                'reasons':report['reasons']}))
            return report
        except Exception as exc:
            # Diagnostic object can be overwritten on resume. Checkpointed pages remain immutable.
            storage.write(f'{prefix}/failure.json', {
                'status': 'FAIL', 'run_id': run_id, 'store': store.id,
                'failure_type': type(exc).__name__, 'message': str(exc),
                'completed_pages':len(all_chunks),
                'timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds')}, overwrite=True)
            logger.error('run_aborted %s', json.dumps({'store':store.id, 'run':run_id,
                                                       'error_type':type(exc).__name__, 'error':str(exc)}))
            raise
