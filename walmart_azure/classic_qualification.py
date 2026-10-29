"""Zero-network Classic Oxylabs response qualification for Waukegan #3891 PICKUP.

Only an unmodified provider response can be input; its authenticity remains to be
confirmed with the authorized operator. A source-looking synthetic response is
never a verified live collection. Never creates or updates latest/* pointers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
import json
import re

from .config import Store, Category
from .extract import (
    _explicit_node, hydration_roots, parse_next_data, nested,
    pickup_availability, seller_is_walmart, regular_sale, find_ppm,
    make_record, product_id, BlockedResponse, ParseError,
)
from .schema import validate_record
from .oxylabs_classic import _evaluate_source, _sanitize, _store_ids, payloads
from .paid_budget import _synced_json

MAX_ENVELOPE_BYTES = 5_000_000
MONEY_ROOTS = ('priceInfo', 'price', 'pricing', 'unitPrice', 'pricePerUnit',
               'pricePerMeasure', 'ppm', 'promotions', 'promotionInfo',
               'promotion', 'coupon', 'coupons', 'offers', 'offerInfo')
SCOPE_KEYS = ('fulfillmentType', 'fulfillmentMethod', 'fulfillmentMode',
              'fulfillmentChannel', 'fulfillment', 'shippingMethod',
              'deliveryMethod', 'deliveryType', 'method', 'channel', 'type')
ID_REGEX = re.compile(r'/ip/(?:[^/?]+/)?(\d{5,20})(?:[/?#]|$)')


def capabilities() -> dict:
    """Documented Classic capabilities vs an *unconfirmed* exact store selector.

    The general Web Scraper API geo_location feature is NOT an authorization to
    infer a precise Walmart pickup store or price. No browser action is presumed
    to work on the dedicated Walmart target without provider qualification.
    """
    return {
        'provider': 'Oxylabs Classic Web Scraper API',
        'endpoint': 'https://realtime.oxylabs.io/v1/queries',
        'documented_raw_html_request': {'source': 'walmart', 'url': '<observed Walmart /ip/ URL>', 'parse': False},
        'documented_product_json_alternative': {'source': 'walmart_product', 'query': '<source-observed product ID>', 'parse': True},
        'required_for_price_proof': ['returned URL', 'raw retailer HTML', 'selected page store #3891',
                                    'selected page PICKUP', 'product store #3891',
                                    'store-scoped local PICKUP price', 'store-scoped PPM and offers if present',
                                    'first-party seller', 'direct product identity'],
        'classic_exact_store_selector_verified': False,
        'geo_location_is_exact_store_selector': False,
        'browser_instructions_walmart_support_verified': False,
        'production_collector_classic_backend_qualified': False,
        'provider_questions': [
            'Which Classic Walmart URL request parameter or supported browser session action selects Walmart #3891 at 3900 Fountain Square Pl, 60085, PICKUP?',
            'Is exact store selection retained across product/category/pagination requests and reflected in returned priceInfo, PPM and promotions?',
            'Can raw HTML with the selected page/store/fulfillment context be returned without parse=true?',
            'Is JS rendering required for the selected store evidence and what is the billed rate per outcome?',
        ],
        'no_paid_request_authorized': True,
        'no_azure_deployment_authorized': True,
    }


def _modes(value) -> set[str]:
    if isinstance(value, (list, tuple)):
        out = set()
        for item in value: out |= _modes(item)
        return out
    if not isinstance(value, str):
        return set()
    w = value.upper().replace('-', '_').replace(' ', '_')
    if 'SHIPPING' in w or 'DELIVERY' in w or 'SHIP_TO' in w or 'MAIL_ORDER' in w:
        return {'SHIPPING'}
    if 'PICKUP' in w or w in ('IN_STORE', 'INSTORE', 'CURBSIDE'):
        return {'PICKUP'}
    return set()


def _scope_of(node: dict) -> set[str]:
    modes = set()
    for k in SCOPE_KEYS:
        value = node.get(k)
        if isinstance(value, str): modes |= _modes(value)
        elif isinstance(value, dict):
            for nested_key in ('type', 'method', 'fulfillmentType'):
                modes |= _modes(value.get(nested_key))
    return modes


def _explicit_pickup_money(product: dict, store_id: str) -> tuple[list[dict], list[str]]:
    """No price/PPM/promotion is certified by a different PICKUP option.

    Every money-bearing root requires an explicit PICKUP+store scope on that
    root or its enclosing object. Conflicting nested scope never inherits a
    good parent. An absent PPM is allowed but is not manufactured.
    """
    checked = []
    problems = []
    roots = [(k, product[k]) for k in MONEY_ROOTS if product.get(k) is not None]
    if not any(k in product for k in ('priceInfo', 'price', 'pricing')):
        problems.append('No primary product price structure')

    def check(node, path, inherited_mode, inherited_store):
        if isinstance(node, list):
            if not node: return
            for i, child in enumerate(node): check(child, f'{path}[{i}]', inherited_mode, inherited_store)
            return
        if isinstance(node, dict):
            scope = _scope_of(node)
            ids = _store_ids(node)
            if 'SHIPPING' in scope or ('PICKUP' in scope and 'SHIPPING' in scope):
                problems.append(f'{path}: shipping or conflicting monetary fulfillment')
            if ids and ids != {store_id}:
                problems.append(f'{path}: monetary store differs or multiple stores')
            mode = scope or inherited_mode
            bound_store = (next(iter(ids)) if ids and len(ids) == 1 else inherited_store)
            if mode != {'PICKUP'}:
                problems.append(f'{path}: no explicit inherited PICKUP monetary scope')
            if bound_store != store_id:
                problems.append(f'{path}: no explicit inherited # {store_id} monetary store scope')
            checked.append({'path':path, 'fulfillment':sorted(mode),
                            'store_id':bound_store, 'price_or_offer_object_present':True})
            for k, child in node.items():
                if isinstance(child, (dict, list)) and k not in SCOPE_KEYS:
                    check(child, f'{path}.{k}', mode, bound_store)
            return
        # Literal top-level money fields cannot carry their own store/PICKUP tags.
        if inherited_mode != {'PICKUP'} or inherited_store != store_id:
            problems.append(f'{path}: unscoped monetary scalar')
        checked.append({'path':path, 'fulfillment':sorted(inherited_mode),
                        'store_id':inherited_store, 'scalar':True})

    for k, v in roots:
        check(v, k, set(), None)
    return checked, list(dict.fromkeys(problems))


def _selected_page_location(hydration: dict) -> tuple[set[str], set[str], list[str]]:
    ids: set[str] = set()
    modes: set[str] = set()
    paths: list[str] = []
    for root_index, root in enumerate(hydration_roots(hydration)):
        for label, node in (('root',root),('root.data', nested(root,'data'))):
            if not isinstance(node, dict): continue
            for key in ('location','selectedStore','pickupStore','storeInfo','customerLocation'):
                loc = node.get(key)
                if isinstance(loc, dict):
                    ids |= _store_ids(loc)
                    modes |= _scope_of(loc)
                    paths.append(f'hydration_roots[{root_index}].{label}.{key}')
    return ids, modes, paths


def qualify_envelope(envelope: dict, *, store: Store, observed_url: str, product_id_expected: str,
                     category: Category, expected_job_id: str = '') -> tuple[dict, dict | None, str | None]:
    """Evaluate a saved provider envelope. No web, no paid requests, no live claims.

    Returns (receipt, candidate 22-field record or None, sanitized HTML or None).
    """
    failures: list[str] = []
    receipt: dict = {'status':'REJECTED_INSUFFICIENT_SOURCE_EVIDENCE',
        'source_kind':'UNAUTHENTICATED_OFFLINE_PROVIDER_RESPONSE',
        'requested_store_id':store.id, 'requested_zip':store.zipcode,
        'required_fulfillment':'PICKUP', 'requested_url':observed_url,
        'requested_product_id':product_id_expected, 'buyer_acceptance':False,
        'verified_genuine_live_products':0, 'network_requests':0, 'paid_requests':0,
        'azure_execution':False, 'reasons':failures}
    candidate = None
    sanitized = None
    # The payload definition itself must be reviewable and free of manufactured URLs.
    try:
        requests = payloads(observed_url, product_id_expected, False)
        if len(requests) != 1: failures.append('No valid observed source product URL and ID')
        else: receipt['proposed_classic_request'] = requests[0]
    except (ValueError, TypeError) as exc:
        failures.append('Invalid requested product URL/ID: '+str(exc))
    if store.id != '3891' or store.zipcode != '60085':
        failures.append('Only the client-confirmed Waukegan #3891 context is qualified')
    rows = envelope.get('results') if isinstance(envelope, dict) else None
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        failures.append('Require exactly one Classic provider result')
        return receipt, candidate, sanitized
    row = rows[0]
    returned_url = row.get('url')
    receipt['actual_returned_url'] = returned_url if isinstance(returned_url,str) else ''
    receipt['provider_job_id'] = str(row.get('job_id') or '')
    receipt['source_http_status'] = row.get('status_code')
    if not receipt['provider_job_id']:
        failures.append('Missing actual provider job_id')
    if expected_job_id and receipt['provider_job_id'] != expected_job_id:
        failures.append('Provider job_id does not match operator-supplied expected ID')
    if row.get('status_code')!=200:
        failures.append('Provider source HTTP status is not 200')
    if not isinstance(returned_url,str):
        failures.append('Missing actual returned retailer source URL')
    else:
        parsed = urlparse(returned_url)
        if (parsed.scheme!='https' or parsed.hostname not in ('walmart.com','www.walmart.com')
                or parsed.username or parsed.password or not ID_REGEX.search(parsed.path)):
            failures.append('Returned URL must be a real HTTPS Walmart product URL')
        else:
            returned_id=ID_REGEX.search(parsed.path).group(1)
            if returned_id!=product_id_expected:
                failures.append('Returned source URL product ID mismatches requested product ID')
        if parsed.path.casefold().startswith(('/blocked','/challenge','/captcha')):
            failures.append('Retailer returned challenge/blocked URL')
    content = row.get('content')
    if not isinstance(content,str) or not content.lstrip().startswith(('<!DOCTYPE','<!doctype','<html','<HTML')):
        failures.append('Require inspectable original retailer HTML, not parsed JSON or an empty body')
        return receipt, candidate, sanitized
    receipt['original_html_sha256'] = sha256(content.encode('utf-8')).hexdigest()
    receipt['original_html_bytes'] = len(content.encode('utf-8'))
    sanitized = _sanitize(content)
    if not isinstance(sanitized,str):
        failures.append('Failed to sanitize original retailer HTML')
        return receipt, candidate, None
    receipt['sanitized_html_sha256'] = sha256(sanitized.encode('utf-8')).hexdigest()
    try:
        hydration = parse_next_data(content)
    except (BlockedResponse,ParseError,ValueError) as exc:
        failures.append('Retailer response missing usable source hydration: '+str(exc))
        return receipt, candidate, sanitized
    selected_ids, selected_modes, paths = _selected_page_location(hydration)
    receipt['selected_page_source_paths'] = paths
    receipt['selected_page_store_ids'] = sorted(selected_ids)
    receipt['selected_page_fulfillment'] = sorted(selected_modes)
    if selected_ids != {store.id}:
        failures.append('Returned selected page store is not exclusively #3891')
    if selected_modes != {'PICKUP'}:
        failures.append('Returned page does not explicitly select PICKUP only')
    product = _explicit_node(hydration, 'product')
    if not isinstance(product,dict):
        failures.append('Missing primary product object')
        return receipt, candidate, sanitized
    pid=product_id(product)
    receipt['source_product_id']=pid
    if pid!=product_id_expected:
        failures.append('Primary product ID mismatches source-observed ID')
    if _store_ids(product.get('location')) != {store.id}:
        failures.append('Primary product store scope is absent, ambiguous, or mismatched')
    if not seller_is_walmart(product):
        failures.append('Seller is not independently verified as first-party Walmart')
    # The product-level availability option must itself identify this store;
    # page selection and a generic pickup option are not sufficient.
    options = product.get('fulfillmentOptions') or nested(product,'fulfillment','options') or []
    if isinstance(options, dict):
        options = options.get('options') or [options]
    pickup_scopes=[]
    for option in options if isinstance(options,list) else []:
        if isinstance(option,dict) and 'PICKUP' in _scope_of(option):
            pickup_scopes.append(sorted(_store_ids(option)))
    receipt['selected_pickup_option_store_ids']=pickup_scopes
    if not pickup_scopes or any(ids != [store.id] for ids in pickup_scopes):
        failures.append('PICKUP availability option lacks an exclusive explicit #3891 store binding')
    availability=pickup_availability(product)
    receipt['source_pickup_availability']=availability
    if availability != 'AVAILABLE':
        failures.append('Product is not explicitly available for current #3891 PICKUP price')
    old_evidence = _evaluate_source(content, store, returned_url if isinstance(returned_url,str) else observed_url)
    receipt['legacy_source_shape_evidence'] = old_evidence
    if old_evidence.get('verification_status')!='SOURCE_SHAPE_VERIFIED_NEEDS_HUMAN_COMPARISON':
        failures.append('Existing source-shape verifier did not qualify page/store/price')
    money_checked,money_errors=_explicit_pickup_money(product,store.id)
    receipt['money_source_paths']=money_checked
    failures.extend(money_errors)
    price=regular_sale(product)[0]
    receipt['observed_regular_price']=price
    receipt['direct_ppm']=find_ppm(product)
    if not price:
        failures.append('Missing explicitly source-displayed current local pickup price')
    # Never rely on the CLI category label to claim full category/branch coverage.
    receipt['category_label_source']='OPERATOR_PROVIDED_NOT_SOURCE_VERIFIED'
    if not failures:
        observed=datetime.now(timezone.utc).date().isoformat()
        record=make_record(product,store,category,observed)
        issues=validate_record(record,strict=True)
        if issues:
            failures.extend('Invalid 22-field wire record: '+x for x in issues)
        elif record['url'] and ID_REGEX.search(urlparse(record['url']).path) and ID_REGEX.search(urlparse(record['url']).path).group(1)==pid:
            candidate=record
            receipt['status']='STRICT_OFFLINE_SOURCE_SHAPE_CANDIDATE_NOT_LIVE_AUTHENTICATED'
            receipt['candidate_record_sha256']=sha256(json.dumps(record,ensure_ascii=False).encode()).hexdigest()
            receipt['candidate_field_order']=list(record)
        else:
            failures.append('Primary product canonical URL is absent or mismatched')
    return receipt, candidate, sanitized


def qualify_saved_response(*, response_file: str, output_dir: str, store: Store,
                           observed_url: str, product_id_expected: str,
                           category: Category, expected_job_id: str = '') -> dict:
    """Read-only input; writes isolated, review-only evidence. Never last-good data."""
    src = Path(response_file)
    raw = src.read_bytes()
    if len(raw)>MAX_ENVELOPE_BYTES:
        raise ValueError('Classic response exceeds strict 5MB offline review cap')
    try:
        envelope=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ValueError('Saved Classic response is not UTF-8 JSON') from exc
    output=Path(output_dir)
    if output.resolve()==src.resolve() or output.resolve() in src.resolve().parents:
        raise ValueError('Output directory cannot overwrite the source response')
    result,candidate,sanitized=qualify_envelope(envelope,store=store,
        observed_url=observed_url,product_id_expected=product_id_expected,
        category=category,expected_job_id=expected_job_id)
    result['input_envelope_sha256']=sha256(raw).hexdigest()
    result['input_envelope_bytes']=len(raw)
    result['live_origin_authenticated']=False
    result['retailer_browser_session_authorized']=False
    result['complete_category_coverage']=False
    result['collection_runner_integrated']=False
    # Sanitize source before writing a reviewable copy; do not redistribute
    # the original provider envelope which can contain tokens/cookies.
    output.mkdir(parents=True,exist_ok=True)
    if sanitized is not None:
        target=output/'sanitized_source.html'
        if target.exists(): raise FileExistsError('Review evidence already exists; choose a new output directory')
        target.write_text(sanitized,encoding='utf-8')
        result['sanitized_source_path']=str(target)
    if candidate is not None:
        record_file=output/'candidate_RECORD_NOT_LIVE_VERIFIED.json'
        if record_file.exists(): raise FileExistsError('Candidate record already exists; choose new output directory')
        _synced_json(record_file,[candidate],exclusive=True)
        result['candidate_record_path']=str(record_file)
    receipt_file=output/'qualification_receipt.json'
    _synced_json(receipt_file,result,exclusive=True)
    return result
