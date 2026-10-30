"""Billed-only-on-explicit-approval probe for Oxylabs Web Scraper API (Classic).

HTTP POST https://realtime.oxylabs.io/v1/queries with Basic-auth API USER/PASS.
This adapter does NOT claim store-specific pickup correctness unless the returned
Walmart source independently proves store 3891, pickup, seller and price.
No paid requests run in dry-run mode (the default).
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
from threading import Event, Thread
from typing import Callable
from urllib.parse import urlparse
import json
import os
import re
import time
import uuid

import requests
from bs4 import BeautifulSoup
from .paid_budget import PaidBudget, BudgetError, _synced_json
from .deadline_transport import bounded_post, RequestDeadlineExceeded, ResponseBodyLimit
from .browser import selected_location_from_data
from .extract import (parse_next_data, parse_detail, parse_listing, hydration_roots, nested, seller_is_walmart,
                      pickup_availability, match_location, regular_sale, find_ppm, parse_deals,
                      BlockedResponse, ParseError)
from .config import Store

ENDPOINT = 'https://realtime.oxylabs.io/v1/queries'
STORE_ID = '3891'
DEFAULT_URL = ''  # A category page is not a primary product diagnostic
SENSITIVE_KEY = re.compile(r'(?:password|secret|token|authorization|cookie|session|credential|csrf|nonce|api[_-]?key)',re.I)
SENSITIVE_TEXT = re.compile(r'(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[\w.\-+/=]+|(?i:(?:access_token|refresh_token|api_key|password|secret|sessionid)\s*[=:]\s*["\']?)[\w.\-+/=]+')


class OxylabsProbeError(RuntimeError):
    pass


def payloads(url: str = DEFAULT_URL, product_id: str = '', render: bool = False) -> list[dict]:
    """Use the documented localized Walmart product source with raw HTML.

    The original /ip/ URL is source provenance, not an API request field.
    The returned page may fall back to the default store and MUST prove pickup.
    """
    if render:
        raise ValueError('Rendering is not qualified/approved for this Classic source')
    if not url:
        return []
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('www.walmart.com', 'walmart.com')
            or parsed.username or parsed.password or not parsed.path.startswith('/ip/')):
        raise ValueError('Observed HTTPS Walmart product detail (/ip/) URL required')
    if not re.fullmatch(r'\d{5,20}', product_id or ''):
        raise ValueError('Observed numeric product ID required with the original URL')
    match = re.search(r'/(\d{5,20})(?:/|$)', parsed.path)
    if not match or match.group(1) != product_id:
        raise ValueError('Observed source URL does not match requested product ID')
    return [{'source': 'walmart_product', 'product_id': product_id,
             'store_id': STORE_ID, 'fulfillment_type': 'pickup',
             'parse': False, 'render': ''}]


def _sanitize(value):
    if isinstance(value, dict):
        return {key:('[REDACTED]' if SENSITIVE_KEY.search(key) else _sanitize(val))
                for key,val in value.items()}
    if isinstance(value,list):
        return [_sanitize(v) for v in value]
    if isinstance(value,str):
        if not ('<' in value and '>' in value and ('<html' in value.casefold() or '<script' in value.casefold())):
            return SENSITIVE_TEXT.sub('[REDACTED]',value)
        soup = BeautifulSoup(value,'html.parser')
        # Remove executable script data but retain retailer's source-provided
        # product hydration and JSON-LD, after sensitive-key redaction.
        for tag in list(soup.select('script')):
            if tag.get('id') == '__NEXT_DATA__' or tag.get('type') == 'application/ld+json':
                if tag.string:
                    try: tag.string=json.dumps(_sanitize(json.loads(tag.string)),ensure_ascii=False)
                    except (ValueError,TypeError): tag.decompose()
            else:
                tag.decompose()
        for tag in list(soup.select('input[type="hidden"], meta[name*="csrf" i]')):
            tag.decompose()
        for tag in soup.find_all(True):
            for attr in list(tag.attrs):
                if SENSITIVE_KEY.search(attr):
                    tag[attr]='[REDACTED]'
        return SENSITIVE_TEXT.sub('[REDACTED]',str(soup))
    return value


def _store_ids(value: object) -> set[str]:
    """Only explicit store ID fields; city, ZIP and requested labels are not proof."""
    if not isinstance(value, dict):
        return set()
    result = set()
    for key in ('storeId', 'pickupStoreId', 'selectedStoreId', 'storeIds'):
        raw = value.get(key)
        if isinstance(raw, list):
            result.update(str(x) for x in raw if x is not None and str(x).strip())
        elif raw is not None and str(raw).strip():
            result.add(str(raw))
    return result


def _money_binding(product: dict, store_id: str) -> tuple[bool, str]:
    """Each price, direct PPM and offer must be pickup-scoped, not shipping.

    With mixed pickup/shipping options, untagged monetary structures are
    ambiguous, even when an unrelated pickup option exists.
    """
    def modes(value) -> set[str]:
        if isinstance(value, dict):
            out = set()
            for key, part in value.items():
                if key in ('type','method','fulfillment','fulfillmentType',
                           'fulfillmentMethod','fulfillmentMode','fulfillmentChannel',
                           'shippingMethod','deliveryType','deliveryMethod','channel'):
                    out.update(modes(part))
            return out
        if isinstance(value, list):
            out = set()
            for part in value:
                out.update(modes(part))
            return out
        if value is None:
            return set()
        word = str(value).upper().replace('-', '_').replace(' ', '_')
        if 'PICKUP' in word or word in ('IN_STORE','INSTORE','CURBSIDE'):
            return {'PICKUP'}
        if any(x in word for x in ('SHIPPING','SHIP_TO','SHIPMENT','DELIVERY','MAIL_ORDER')):
            return {'NON_PICKUP'}
        return set()

    product_mode = modes({k: product.get(k) for k in
                          ('fulfillmentType','fulfillmentMethod','fulfillmentMode')})
    if 'NON_PICKUP' in product_mode:
        return False, 'Selected product fulfillment is SHIPPING/DELIVERY'
    options = product.get('fulfillmentOptions') or nested(product,'fulfillment','options') or []
    if isinstance(options,dict):
        options = options.get('options') or [options]
    if not isinstance(options,list) or not options:
        return False, 'Missing explicit pickup fulfillment option'
    option_modes = set()
    for option in options:
        if not isinstance(option,dict):
            return False, 'Malformed fulfillment option'
        option_mode = modes({k:option.get(k) for k in ('type','method','fulfillmentType')})
        if not option_mode:
            return False, 'Unknown fulfillment option method'
        option_modes.update(option_mode)
        ids = _store_ids(option)
        if ids and ids != {store_id}:
            return False, 'Conflicting store scope in fulfillment option'
    if 'PICKUP' not in option_modes:
        return False, 'No explicit product PICKUP option'
    mixed = 'NON_PICKUP' in option_modes

    def check(node, path: str, inherited: set[str]) -> tuple[bool,str]:
        if isinstance(node,list):
            for index, value in enumerate(node):
                ok, reason = check(value,f'{path}[{index}]',inherited)
                if not ok: return ok, reason
            return True,''
        if not isinstance(node,dict):
            return True,''
        ids = _store_ids(node)
        if ids and ids != {store_id}:
            return False, f'{path}: monetary store scope conflicts'
        scope = modes({k:node.get(k) for k in (
            'fulfillment','fulfillmentType','fulfillmentMethod','fulfillmentMode',
            'fulfillmentChannel','shippingMethod','deliveryType','deliveryMethod',
            'method','channel')})
        scope.update(modes({'type':node.get('type')}))
        if 'NON_PICKUP' in scope:
            return False, f'{path}: SHIPPING/DELIVERY-specific monetary object'
        effective = scope or inherited
        if mixed and 'PICKUP' not in effective:
            return False, f'{path}: ambiguous pickup versus shipping money scope'
        for key,value in node.items():
            if isinstance(value,(dict,list)) and key not in (
                'fulfillment','fulfillmentType','fulfillmentMethod','fulfillmentMode',
                'fulfillmentChannel','shippingMethod','deliveryType','deliveryMethod'):
                ok,reason=check(value,f'{path}.{key}',effective)
                if not ok:return ok,reason
        return True,''

    roots=('priceInfo','price','pricing','unitPrice','pricePerUnit','pricePerMeasure',
           'ppm','promotions','promotionInfo','promotion','coupon','coupons','offers','offerInfo')
    if not any(product.get(k) is not None for k in ('priceInfo','price','pricing')):
        return False, 'No direct source price information'
    for name in roots:
        value=product.get(name)
        if value is None: continue
        if mixed and not isinstance(value,(dict,list)):
            return False, f'{name}: unscoped monetary value on mixed pickup/shipping product'
        ok, reason = check(value,name,set())
        if not ok:return ok,reason
    return True,''


def _evaluate_source(content, expected_store: Store, target_url: str) -> dict:
    """Prove selection, product, PICKUP and money all describe ONE store.

    Unknown or contradictory scopes are an explicit failure, even if another
    nested node incidentally contains expected_store.id. A requested store
    label does not establish Walmart's returned context.
    """
    result = {'store_expected': expected_store.id, 'pickup_required': 'PICKUP',
              'store_verified': False, 'pickup_verified': False,
              'first_party_verified': False, 'price_verified': False,
              'price_context_binding_verified': False, 'ppm_direct': '',
              'offer_description': {}, 'verification_status': 'UNVERIFIED',
              'buyer_acceptance': False, 'original_retailer_html_available': False}
    page_ids = set()
    product = None
    if isinstance(content, dict):
        # Parsed API JSON is not independent evidence of the selected retailer page.
        # Never re-interpret a product's location as selected PAGE location.
        product = content.get('product') if isinstance(content.get('product'), dict) else content
    elif isinstance(content, str):
        result['original_retailer_html_available'] = True
        try:
            data = parse_next_data(content)
        except (BlockedResponse, ParseError) as exc:
            result['source_parse_error'] = type(exc).__name__ + ': ' + str(exc)
            return result
        from .extract import _explicit_node
        product = _explicit_node(data, 'product')
        # Do NOT use selected_location_from_data here: its first match may be a
        # product location 3891 even if the selected *page* says store 100.
        for root in hydration_roots(data):
            for place in (root, nested(root, 'data')):
                if isinstance(place, dict):
                    for key in ('location','selectedStore','pickupStore','storeInfo','customerLocation'):
                        page_ids.update(_store_ids(place.get(key)))
        try:
            listing = parse_listing(content)
            result['listing_candidate_count'] = len(listing.products)
        except (BlockedResponse, ParseError):
            pass  # A listing is not a qualifying primary product response.
    else:
        result['source_parse_error'] = 'Unrecognized content type'
        return result
    result['page_store_ids'] = sorted(page_ids)
    if not isinstance(product, dict) or not (product.get('usItemId') or product.get('itemId')):
        result['source_parse_error'] = 'Missing primary product object and ID'
        return result
    result['product_id'] = str(product.get('usItemId') or product.get('itemId'))
    if not result['original_retailer_html_available']:
        result['source_parse_error'] = 'Parsed API product lacks independently inspectable selected retailer page'
        return result
    product_ids = _store_ids(product.get('location'))
    result['product_store_ids'] = sorted(product_ids)
    if page_ids != {expected_store.id}:
        result['source_parse_error'] = 'Page selected store absent, multiple or mismatched'
        return result
    if product_ids != {expected_store.id}:
        result['source_parse_error'] = 'Product store absent, multiple or mismatched'
        return result
    money_ok, money_reason = _money_binding(product, expected_store.id)
    if not money_ok:
        result['source_parse_error'] = money_reason
        return result
    # A shipping-selected page cannot certify pickup prices.
    for root in hydration_roots(data) if isinstance(content, str) else []:
        for node in (root, nested(root,'data')):
            loc = node.get('location') if isinstance(node,dict) else None
            if isinstance(loc,dict):
                selection = str(loc.get('fulfillmentType') or loc.get('fulfillmentMode') or '').upper()
                if 'SHIPPING' in selection or 'DELIVERY' in selection:
                    result['source_parse_error']='Page selected SHIPPING/DELIVERY, not PICKUP'
                    return result
    availability = pickup_availability(product)
    if availability not in ('AVAILABLE','UNAVAILABLE'):
        result['source_parse_error'] = 'No explicit local pickup availability'
        return result
    # Verify an explicit pickup selection, not mere global item availability.
    result['store_verified'] = True
    result['pickup_verified'] = True
    result['first_party_verified'] = seller_is_walmart(product)
    result['observed_price'] = regular_sale(product)[0]
    result['ppm_direct'] = find_ppm(product)
    try:
        result['offer_description'] = parse_deals(product)
    except ParseError as exc:
        result['source_parse_error'] = str(exc)
        return result
    result['price_context_binding_verified'] = bool(result['first_party_verified'] and result['observed_price'])
    result['price_verified'] = result['price_context_binding_verified']
    result['price_context'] = {'selected_page_store': expected_store.id,
                               'product_store': expected_store.id,
                               'fulfillment': 'PICKUP',
                               'price_origin': 'primary product priceInfo inside selected page',
                               'ppm_origin': 'same primary product',
                               'offers_origin': 'same primary product'}
    if result['original_retailer_html_available'] and all(result[k] for k in (
            'store_verified','pickup_verified','first_party_verified','price_verified')):
        result['verification_status'] = 'SOURCE_SHAPE_VERIFIED_NEEDS_HUMAN_COMPARISON'
    return result


def _invalidate_timed_out_proof(receipt: dict) -> None:
    """Deadline overruns always remove positive source-verification signals."""
    receipt['status']='DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN'
    receipt['deadline_exceeded']=True
    receipt['source_shape_verified_records']=0
    receipt['genuine_products_verified']=0
    receipt['buyer_acceptance']=False
    for response in receipt.get('results', []):
        response.pop('candidate_record_sha256',None)
        proof=response.get('source_evidence')
        if isinstance(proof,dict):
            proof['status']='DEADLINE_UNQUALIFIED'
            proof.pop('candidate_record_sha256',None)
            for key in ('store_verified','pickup_verified','first_party_verified',
                        'price_verified','price_context_binding_verified'):
                proof[key]=False



def _incomplete_snapshot(receipt: dict) -> dict:
    """Intermediate receipt remains unqualified even if a candidate was found."""
    snapshot=deepcopy(receipt)
    status=snapshot.get('status','')
    if status not in ('DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN',
                      'TRANSPORT_OR_LIMIT_STOP_RESERVED_OUTCOME_UNCERTAIN'):
        snapshot['status']='FINALIZATION_PENDING_RESERVED_OUTCOME_UNCERTAIN'
    snapshot['finalization_state']='PENDING'
    snapshot['receipt_finalized']=False
    snapshot.pop('finished_utc',None)
    snapshot['source_shape_verified_records']=0
    snapshot['genuine_products_verified']=0
    snapshot['buyer_acceptance']=False
    for reply in snapshot.get('results',[]):
        reply.pop('candidate_record_sha256',None)
        proof=reply.get('source_evidence')
        if isinstance(proof,dict):
            proof['status']='FINALIZATION_PENDING_UNQUALIFIED'
            proof.pop('candidate_record_sha256',None)
            for name in ('store_verified','pickup_verified','first_party_verified',
                         'price_verified','price_context_binding_verified'):
                proof[name]=False
    return snapshot


def _save_incomplete_receipt(budget: PaidBudget, receipt: dict) -> None:
    budget.save_receipt(_incomplete_snapshot(receipt))


def _publish_terminal_receipt(out: Path, receipt: dict, deadline_at: float,
                              cancelled: Event) -> bool:
    """Stage/fsync complete terminal bytes before a supervised atomic rename.

    No potentially blocking I/O follows the promotion. A crash before it
    leaves the existing non-positive receipt and consumed ledger reservation.
    """
    tmp=out.with_name(out.name+'.'+uuid.uuid4().hex+'.terminal.tmp')
    promoted=False
    try:
        with tmp.open('x',encoding='utf-8') as stream:
            json.dump(receipt,stream,indent=2,ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name=='posix':
            fd=os.open(str(out.parent),os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        if cancelled.is_set() or time.monotonic()>=deadline_at:
            return False
        os.replace(tmp,out)
        promoted=True
        return True
    finally:
        if not promoted:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass


def _run_probe_core(*, store: Store, url: str = DEFAULT_URL, product_id: str = '',
              render: bool = False, output: str, execute_billable: bool = False,
              billing_approved: bool = False, authorization_id: str = '',
              max_requests: int = 1, max_retries: int = 0, max_seconds: int = 90,
              max_body_bytes: int = 2_000_000,
              session_factory: Callable[[],object] = requests.Session,
                    _absolute_deadline: float | None = None,
                    _shared_progress: dict | None = None,
                    _cancelled: Event | None = None) -> dict:
    if store.id != STORE_ID or store.zipcode != '60085' or '3900 Fountain Square' not in store.address:
        raise ValueError('Diagnostic is bound to client-confirmed Waukegan #3891, ZIP 60085')
    if not (1 <= max_requests <= 2 and 0 <= max_retries <= 1 and 1 <= max_seconds <= 180 and
            32_768 <= max_body_bytes <= 5_000_000):
        raise ValueError('Exceeds fixed review caps: 2 paid jobs, 1 retry, 180 seconds, 5 MB per body')
    jobs = payloads(url, product_id, render)
    if jobs and len(jobs) * (max_retries + 1) > max_requests:
        raise ValueError('Requests including retries exceed approved request cap')
    start = time.monotonic()
    deadline_at = _absolute_deadline if _absolute_deadline is not None else start + max_seconds
    def check_deadline(stage):
        if (_cancelled is not None and _cancelled.is_set()) or time.monotonic() >= deadline_at:
            raise RequestDeadlineExceeded('Whole-run deadline expired during '+stage)
    out = Path(output)
    receipt = {'release':'0.5.5', 'provider':'Oxylabs Web Scraper API (Classic)',
               'endpoint': ENDPOINT, 'selected_store':store.id, 'selected_zip':store.zipcode,
               'pickup_required':'PICKUP', 'store_selection_in_api_payload':'REQUESTS_3891_PICKUP_REQUIRES_RETURNED_PROOF',
               'source_contract':'walmart_product id+store_id+fulfillment_type; parse=false; render empty',
               'request_cap_total_including_retries':max_requests,
               'retry_cap_per_job':max_retries, 'deadline_seconds':max_seconds,
               'body_cap_bytes':max_body_bytes, 'render_requested':render,
               'paid_execution':bool(execute_billable), 'requests_sent':0,
               'jobs_planned':jobs, 'results':[], 'attempts':[],
               'genuine_products_verified':0, 'source_shape_verified_records':0,
               'azure_execution':False, 'buyer_acceptance':False,
               'started_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if not execute_billable:
        receipt['status'] = ('DRY_RUN_NO_NETWORK_NO_COST' if jobs
                             else 'NEEDS_OBSERVED_PRODUCT_URL_NO_NETWORK_NO_COST')
        receipt['note'] = ('No credential access or paid request. Product ID and original URL must come from an observed Walmart source. '
                           'Classic walmart_product requests store_id=3891 PICKUP; provider may fall back to default store. The returned page must independently prove local prices.')
        out.parent.mkdir(parents=True,exist_ok=True)
        _synced_json(out, receipt)  # never a billing reservation
        return receipt
    if not billing_approved:
        raise OxylabsProbeError('Paid execution requires both --execute-billable and --billing-approved')
    if not jobs:
        raise OxylabsProbeError('Provide --product-id AND --url for an observed primary product before paid execution')
    username = os.getenv('OXY_WSA_USERNAME','')
    password = os.getenv('OXY_WSA_PASSWORD','')
    if not username or not password:
        raise OxylabsProbeError('Missing Classic API credentials; do not place them in source')
    try:
        budget = PaidBudget(out, authorization_id, max_requests)
        if _shared_progress is not None:
            _shared_progress['authorization_ledger']=str(budget.ledger_file)
        receipt['receipt_finalized']=False
        receipt['finalization_state']='PENDING'
        budget.open_receipt(receipt)  # exclusive; no concurrent receipt reuse
    except BudgetError as exc:
        raise OxylabsProbeError(str(exc)) from exc
    session = None
    deadline_exceeded = False
    try:
        session = session_factory()
        check_deadline('provider session creation')
        for job_index, job in enumerate(jobs, 1):
            for attempt in range(1, max_retries + 2):
                if time.monotonic() >= deadline_at:
                    receipt['status'] = 'DEADLINE_STOP'
                    break
                try:
                    check_deadline('durable pre-dispatch reservation')
                    budget.reserve(receipt, job, attempt)  # fsync ledger AND receipt before dispatch
                    if _shared_progress is not None:
                        _shared_progress['requests_sent']=receipt['requests_sent']
                except BudgetError as exc:
                    receipt['results'].append({'job_index':job_index,'attempt':attempt,'error':str(exc)})
                    receipt['status']='BUDGET_RESERVATION_REFUSED_STOP'
                    break
                try:
                    check_deadline('provider network dispatch')
                    status, raw = bounded_post(session, ENDPOINT, (username,password), job,
                                               max_body_bytes, deadline_at)
                    check_deadline('response processing')
                    reply={'job_index':job_index,'attempt':attempt,'http_status':status,
                           'request_payload':job,'response_bytes':len(raw),
                           'raw_response_sha256':sha256(raw).hexdigest(),
                           'received_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
                    body_file = out.parent / (out.stem+f'.job{job_index:02}.attempt{attempt}.sanitized.json')
                    try:
                        full = json.loads(raw)
                        sanitized = _sanitize(full)
                    except (ValueError,UnicodeDecodeError):
                        sanitized={'raw_text':_sanitize(raw.decode('utf-8','replace'))}
                    check_deadline('before sanitized evidence write')
                    _synced_json(body_file, sanitized, exclusive=True)
                    check_deadline('after sanitized evidence write')
                    reply['sanitized_response_body']=str(body_file)
                    reply['sanitized_body_sha256']=sha256(body_file.read_bytes()).hexdigest()
                    if status in (401,403):
                        reply['error']='PROVIDER_AUTH_DENIED'
                        receipt['status']='AUTH_DENIED_STOP'
                    elif status==429:
                        reply['error']='PROVIDER_RATE_LIMIT'
                        receipt['status']='RATE_LIMIT_STOP'
                    elif status>=500:
                        reply['error']='PROVIDER_TRANSIENT_ERROR'
                        receipt['status']='PROVIDER_5XX_STOP'
                    elif status!=200:
                        reply['error']='PROVIDER_NON_200'
                        receipt['status']='PROVIDER_NON_200_STOP'
                    else:
                        # Same strict gate for saved and live provider responses.
                        # Never trust a requested store label or weak legacy verdict.
                        from .classic_qualification import qualify_envelope
                        from .config import Category
                        check_deadline('before strict source qualification')
                        review_category = Category(name='UNVERIFIED_DIAGNOSTIC_CATEGORY',
                                                   subcategory='', url=url)
                        proof, candidate, _ = qualify_envelope(
                            full if isinstance(full,dict) else {},
                            store=store, observed_url=url,
                            product_id_expected=product_id, category=review_category)
                        check_deadline('after strict source qualification')
                        qualified = (candidate is not None and proof.get('status') ==
                           'STRICT_OFFLINE_SOURCE_SHAPE_CANDIDATE_NOT_LIVE_AUTHENTICATED')
                        proof['source_kind']='PROVIDER_TRANSPORT_OBSERVED_NOT_INDEPENDENTLY_AUTHENTICATED'
                        proof['verified_genuine_live_products']=0
                        proof['buyer_acceptance']=False
                        for field in ('store_verified','pickup_verified',
                                      'first_party_verified','price_verified',
                                      'price_context_binding_verified'):
                            proof[field]=bool(qualified)
                        reply['source_evidence']=proof
                        reply['job_id']=proof.get('provider_job_id','')
                        reply['source_url']=proof.get('actual_returned_url','')
                        if qualified:
                            receipt['source_shape_verified_records']+=1
                            receipt['status']='STRICT_SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE'
                            reply['candidate_record_sha256']=proof.get('candidate_record_sha256','')
                        else:
                            reasons = proof.get('reasons',[])
                            detail = ' '.join(str(value).lower() for value in reasons)
                            if 'missing actual returned retailer source url' in detail:
                                receipt['status']='UNVERIFIED_RESPONSE_STOP'
                                reply['error']='MISSING_OR_UNSAFE_RETURNED_SOURCE_URL'
                            elif ('returned url must be a real' in detail or
                                  'returned source url product id' in detail):
                                receipt['status']='UNVERIFIED_RESPONSE_STOP'
                                reply['error']='RETURNED_PRODUCT_URL_ID_MISMATCH'
                            elif any(token in detail for token in (
                                    'blocked','captcha','challenge','robot','access restriction')):
                                receipt['status']='RETAILER_ACCESS_STOP'
                                reply['error']='RETAILER_CHALLENGE_IN_SOURCE_BODY'
                            else:
                                receipt['status']='STORE_PICKUP_PRICE_UNVERIFIED_STOP'
                                reply['error']='STRICT_SOURCE_QUALIFICATION_FAILED'
                            reply['qualification_reasons']=reasons
                        check_deadline('after verdict before persistence')
                    receipt['results'].append(reply)
                    _save_incomplete_receipt(budget,receipt)
                    if status>=500 and attempt<=max_retries and time.monotonic()<deadline_at:
                        # A retry is always a separately durably reserved possible charge.
                        receipt.pop('status',None)
                        continue
                    break
                except RequestDeadlineExceeded as exc:
                    deadline_exceeded=True
                    receipt['status']='DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN'
                    receipt['results'].append({'job_index':job_index,'attempt':attempt,
                                               'error':type(exc).__name__,'message':str(exc)})
                    _save_incomplete_receipt(budget,receipt)
                    break
                except (requests.RequestException,ResponseBodyLimit,OxylabsProbeError,OSError,ValueError) as exc:
                    receipt['status']='TRANSPORT_OR_LIMIT_STOP_RESERVED_OUTCOME_UNCERTAIN'
                    receipt['results'].append({'job_index':job_index,'attempt':attempt,
                                               'error':type(exc).__name__,'message':str(exc)[:200]})
                    _save_incomplete_receipt(budget,receipt)
                    break
            if receipt.get('status'):
                break
        receipt.setdefault('status','STORE_PICKUP_PRICE_UNVERIFIED_STOP')
    finally:
        # Session cleanup belongs to the same deadline; never block the caller
        # waiting on a slow provider adapter's .close().
        cleanup_completed=True
        if session is not None and not deadline_exceeded and hasattr(session,'close'):
            closed={'finished':False}
            def close_session():
                try: session.close()
                except Exception: pass
                finally: closed['finished']=True
            closer=Thread(target=close_session,daemon=True)
            closer.start()
            closer.join(max(0.0,deadline_at-time.monotonic()))
            cleanup_completed=closed['finished']
        if (deadline_exceeded or not cleanup_completed or
                (_cancelled is not None and _cancelled.is_set()) or
                time.monotonic()>=deadline_at):
            _invalidate_timed_out_proof(receipt)
        receipt['duration_seconds']=round(time.monotonic()-start,3)
        receipt['finished_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
        _save_incomplete_receipt(budget,receipt)
        # The worker NEVER publishes positive terminal status; if a save has
        # crossed the cap, the next persisted snapshot explicitly fails.
        if ((_cancelled is not None and _cancelled.is_set()) or
                time.monotonic()>=deadline_at):
            _invalidate_timed_out_proof(receipt)
            _save_incomplete_receipt(budget,receipt)
    return receipt


def run_probe(**kwargs) -> dict:
    """Bounded two-phase worker/finalizer; expired watchdog does no file I/O.

    All unfinished saved receipts are unqualified. The fixed approval ledger
    holds the authoritative, permanently consumed billed-attempt reservation.
    """
    if not kwargs.get('execute_billable',False):
        return _run_probe_core(**kwargs)
    deadline_at=time.monotonic()+kwargs.get('max_seconds',90)
    cancelled=Event()
    progress={'requests_sent':None,'authorization_ledger':''}
    state={}

    def deadline_failure(note='Inspect the fixed approval ledger for reserved/uncertain attempts; no automatic retry.'):
        return {'release':'0.5.5','status':'DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN',
                'deadline_exceeded':True,'source_shape_verified_records':0,
                'genuine_products_verified':0,'buyer_acceptance':False,
                'receipt_finalized':False,'requests_sent':progress['requests_sent'],
                'authorization_ledger':progress['authorization_ledger'],
                'receipt_path':kwargs.get('output',''),'note':note}

    def work():
        try:
            state['result']=_run_probe_core(_absolute_deadline=deadline_at,
                _shared_progress=progress,_cancelled=cancelled,**kwargs)
        except BaseException as exc:
            state['error']=exc

    thread=Thread(target=work,name='classic-reserved-probe',daemon=True)
    thread.start()
    thread.join(max(0.0,deadline_at-time.monotonic()))
    if thread.is_alive() or time.monotonic()>=deadline_at:
        cancelled.set()
        return deadline_failure()
    if 'error' in state:
        raise state['error']

    # Source checks, session cleanup, and all provisional fsyncs have completed.
    # Positive terminal status is forbidden in the core worker.
    final=state['result']
    final['receipt_finalized']=True
    final['finalization_state']='COMPLETE'
    publish={}
    def finalize():
        try:
            publish['ok']=_publish_terminal_receipt(
                Path(kwargs['output']),final,deadline_at,cancelled)
        except BaseException as exc:
            publish['error']=exc
    finisher=Thread(target=finalize,name='classic-terminal-receipt-publisher',daemon=True)
    finisher.start()
    finisher.join(max(0.0,deadline_at-time.monotonic()))
    if finisher.is_alive() or not publish.get('ok',False):
        cancelled.set()
        return deadline_failure('Terminal receipt publication incomplete/uncertain; review the pending receipt and fixed ledger; no automatic retry.')
    return final


def review_saved_response(input_file: str, output_file: str, store: Store) -> dict:
    """Zero-network reader for a client-supplied Classic response JSON envelope.

    This is NOT source authentication; it checks format and fields only. The
    input path may contain sensitive vendor material: do not publish it.
    """
    raw=Path(input_file).read_bytes()
    if len(raw)>5_000_000:
        raise OxylabsProbeError('Offline response exceeds 5 MB review limit')
    try:
        provider=json.loads(raw)
    except (ValueError,UnicodeDecodeError) as exc:
        raise OxylabsProbeError('Input is not a JSON Classic API response') from exc
    results=provider.get('results') if isinstance(provider,dict) else None
    if not isinstance(results,list) or not 1<=len(results)<=2:
        raise OxylabsProbeError('Expected 1 or 2 Classic API results')
    assessments=[]
    # Even the legacy saved-response review MUST use the same strict gate
    # as the live probe and oxylabs-qualify CLI. A URL drawn from the provider
    # envelope is not independently authenticated, so review never claims LIVE.
    from .classic_qualification import qualify_envelope, ID_REGEX
    from .config import Category
    for entry in results:
        if not isinstance(entry,dict) or entry.get('status_code')!=200:
            raise OxylabsProbeError('Source result missing or not HTTP 200')
        source_url=str(entry.get('url') or '')
        parsed=urlparse(source_url)
        if parsed.scheme!='https' or parsed.hostname not in ('www.walmart.com','walmart.com'):
            raise OxylabsProbeError('Source URL missing or not an actual Walmart URL')
        if parsed.path.casefold().startswith(('/blocked','/challenge','/captcha')):
            raise OxylabsProbeError('Source returned an access-restriction page')
        id_match=ID_REGEX.search(parsed.path)
        if not id_match:
            raise OxylabsProbeError('Source product URL lacks a numeric Walmart ID')
        proof,candidate,_=qualify_envelope({'results':[entry]},store=store,
            observed_url=source_url,product_id_expected=id_match.group(1),
            category=Category(name='UNVERIFIED_OFFLINE_LABEL',subcategory='',url=source_url))
        proof['source_url_origin']='UNAUTHENTICATED_PROVIDER_ENVELOPE_ONLY'
        proof['buyer_acceptance']=False
        strict_ok=candidate is not None and proof.get('status')=='STRICT_OFFLINE_SOURCE_SHAPE_CANDIDATE_NOT_LIVE_AUTHENTICATED'
        for flag in ('store_verified','pickup_verified','price_verified',
                     'first_party_verified','price_context_binding_verified'):
            proof[flag]=bool(strict_ok)
        assessments.append({'source_url':source_url,
            'job_id':str(entry.get('job_id') or ''),'source_fields':proof})
    result={'status':'OFFLINE_SOURCE_SHAPE_REVIEW_ONLY','source_input_sha256':sha256(raw).hexdigest(),
            'store_expected':store.id,'pickup_required':'PICKUP',
            'results':assessments,'network_requests':0,'paid_execution':False,
            'genuine_products_verified':0,'buyer_acceptance':False,
            'note':'Input may be genuine or synthetic. Independently authenticate job IDs and compare live prices before acceptance.'}
    out=Path(output_file)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
