"""Bounded read-only diagnostic with explicit source provenance; never publishes a dataset.

Only ordinary Walmart.com browser navigation, no hidden API replay or challenge bypass.
A production-claiming PASS cannot be derived from this short probe.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Type
from .browser import WalmartBrowser
from .config import Config, Store
from .extract import (product_id, product_url, seller_is_walmart, pickup_availability,
                      match_location, make_record, regular_sale, sponsored)
from .schema import validate_record


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate_probe_budget(max_requests: int, max_seconds: int, max_categories: int, max_details: int,
                          max_http_requests: int = 250) -> None:
    if not (1 <= max_requests <= 12):
        raise ValueError('Probe navigation budget must be between 1 and 12')
    if not (30 <= max_seconds <= 600):
        raise ValueError('Probe time budget must be 30-600 seconds')
    if not (1 <= max_categories <= 2):
        raise ValueError('Probe category budget must be 1 or 2')
    if not (1 <= max_details <= 4):
        raise ValueError('Probe product detail budget must be 1-4')
    if not (25 <= max_http_requests <= 500):
        raise ValueError('Probe browser HTTP request budget must be 25-500')


async def _collect(report: dict, store: Store, config: Config, headless: bool,
                   max_categories: int, max_details: int, max_requests: int,
                   max_http_requests: int, browser_type: Type[WalmartBrowser]) -> None:
    instance = browser_type(store, config.limits, headless=headless)
    instance.navigation_budget = max_requests
    instance.http_request_budget = max_http_requests
    async with instance as browser:
        # All navigation attempts and browser HTTP requests are bounded.
        report['browser'] = 'playwright_live' if browser_type is WalmartBrowser else 'custom_or_test'
        try:
            proof = await browser.select_store()
            report['store_selected'] = proof.as_dict()
            report['store_verified'] = proof.store_id == store.id and proof.fulfillment == 'PICKUP'
            if not report['store_verified']:
                raise RuntimeError('Selected store or pickup not proven; stop')
            total_details = 0
            seen_product_ids: set[str] = set()
            for category in config.categories[:max_categories]:
                if total_details >= max_details or browser.requests >= max_requests:
                    break
                _, listing_meta, candidates = await browser.listing(category.browse_url)
                report['categories_visited'].append({
                    'category': category.name, 'url': category.url,
                    'page_sha256': listing_meta['proof']['hash'],
                    'page_proof': listing_meta['proof'],
                    'http_status': listing_meta.get('http_status'),
                    'candidate_count': len(candidates),
                    'advertised_max_page': listing_meta['max_page'],
                    'note': 'Only first-page diagnostic; not exhaustive coverage'})
                for candidate in candidates:
                    if total_details >= max_details or browser.requests >= max_requests:
                        break
                    pid, url = product_id(candidate), product_url(candidate)
                    if not pid or not url or pid in seen_product_ids or sponsored(candidate):
                        continue
                    seen_product_ids.add(pid)
                    total_details += 1
                    # Any browser challenge/location mismatch aborts the *entire* probe.
                    product, detail_proof = await browser.detail(url, pid)
                    location_ok, provenance = match_location(product, store)
                    availability = pickup_availability(product)
                    is_seller = seller_is_walmart(product)
                    regular, sale = regular_sale(product)
                    record = make_record(product, store, category, datetime.now(timezone.utc).date().isoformat())
                    issues = validate_record(record, strict=availability != 'UNAVAILABLE')
                    price_verified = bool(regular) and location_ok and is_seller and not issues and \
                        detail_proof.store_id == store.id and detail_proof.fulfillment == 'PICKUP' and \
                        availability in ('AVAILABLE', 'UNAVAILABLE')
                    report['product_samples'].append({
                        'product_id': pid, 'url': url, 'sample_record': record,
                        'record_issues': issues,
                        'source_price_info': product.get('priceInfo', {}),
                        'source_fulfillment_options': product.get('fulfillmentOptions', []),
                        'source_seller': product.get('sellerName', ''),
                        'source_location': product.get('location', {}),
                        'detail_proof': detail_proof.as_dict(),
                        'location_reason': provenance, 'availability': availability,
                        'price_verified': price_verified,
                        'unavailable': availability == 'UNAVAILABLE',
                    })
            report['price_bearing_verified'] = sum(x['price_verified'] for x in report['product_samples'])
            report['status'] = 'PROBE_VERIFIED_NOT_ACCEPTANCE' if report['price_bearing_verified'] else 'FAIL_NO_VERIFIED_LOCAL_PRICE'
        finally:
            report['navigation_attempts'] = browser.requests
            report['browser_http_requests_seen'] = getattr(browser, 'http_requests_seen', 0)
            report['browser_http_request_budget_hit'] = getattr(browser, 'http_budget_hit', False)


async def diagnostic_probe(store: Store, config: Config, output: str,
                           max_requests: int = 8, max_seconds: int = 300,
                           max_categories: int = 2, max_details: int = 3,
                           headed: bool = False, browser_type: Type[WalmartBrowser] = WalmartBrowser,
                           max_http_requests: int = 250) -> dict:
    validate_probe_budget(max_requests, max_seconds, max_categories, max_details, max_http_requests)
    now = utc_now()
    report = {
        'status': 'NOT_STARTED', 'retailer': 'Walmart',
        'source_adapter': 'playwright_live' if browser_type is WalmartBrowser else 'custom_or_test',
        'genuine_collection_claim': False, 'buyer_acceptance': 'NOT_CERTIFIED',
        'started_utc': now,
        'selected_store_expected': {'store_id': store.id, 'zipcode': store.zipcode,
                                    'address': store.location, 'fulfillment': 'PICKUP'},
        'max_navigation_attempts': max_requests, 'max_seconds': max_seconds,
        'max_browser_http_requests': max_http_requests,
        'browser_http_requests_seen': 0, 'browser_http_request_budget_hit': False,
        'max_categories': max_categories, 'max_product_details': max_details,
        'navigation_attempts': 0,
        'store_verified': False, 'store_selected': None,
        'price_bearing_verified': 0, 'categories_visited': [], 'product_samples': [],
        'errors': [], 'scope': 'bounded proof only; no catalog publication, no scheduled execution'
    }
    started = time.monotonic()
    try:
        await asyncio.wait_for(_collect(report, store, config, not headed, max_categories,
                                        max_details, max_requests, max_http_requests, browser_type), timeout=max_seconds)
    except asyncio.TimeoutError:
        report['status'] = 'STOP_TIMEOUT'
        report['errors'].append({'type': 'TimeoutError', 'detail': f'Exceeded {max_seconds}s stop limit'})
    except Exception as exc:
        report['status'] = 'FAIL_DIAGNOSTIC'
        # Errors often contain signed URLs/session material. Keep class & short summary only.
        detail = str(exc).replace('\r', ' ').replace('\n', ' ')[:350]
        report['errors'].append({'type': type(exc).__name__, 'detail': detail})
    finally:
        report['finished_utc'] = utc_now()
        report['runtime_seconds'] = round(time.monotonic()-started, 2)
        report['genuine_verified_product_count'] = (report['price_bearing_verified']
                                                     if browser_type is WalmartBrowser else 0)
        report['buyer_acceptance'] = 'NOT_CERTIFIED'
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        report['report_file'] = str(path)
    return report
