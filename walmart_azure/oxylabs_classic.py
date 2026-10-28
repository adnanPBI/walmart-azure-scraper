"""Billed-only-on-explicit-approval probe for Oxylabs Web Scraper API (Classic).

HTTP POST https://realtime.oxylabs.io/v1/queries with Basic-auth API USER/PASS.
This adapter does NOT claim store-specific pickup correctness unless the returned
Walmart source independently proves store 3891, pickup, seller and price.
No paid requests run in dry-run mode (the default).
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
import json
import os
import re
import time

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
    """One primary Walmart product job; no implicit Food/category request.

    `--store` is a diagnostic EXPECTATION, not a supported Classic store
    selector. Explicit Waukegan PICKUP source proof remains mandatory.
    """
    if url:
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('www.walmart.com','walmart.com')
            or parsed.username or parsed.password or not parsed.path.startswith('/ip/')):
            raise ValueError('Optional source URL must be an HTTPS Walmart product detail (/ip/) URL')
    if not product_id:
        return []
    if not re.fullmatch(r'\d{5,20}', product_id):
        raise ValueError('Product ID must be a 5-20 digit item ID observed from source')
    if url:
        match = re.search(r'/(\d{5,20})(?:[/?#]|$)', url)
        if not match or match.group(1) != product_id:
            raise ValueError('Product URL must refer to the requested product ID')
    if render:
        raise ValueError('Rendering must be separately qualified for this Classic product source; no implicit render')
    return [{'source': 'walmart_product', 'query': product_id, 'parse': True}]


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
    # A per-store price/promo/fulfillment override that conflicts with the
    # selected store cannot be declared price-bound to this response.
    scopes = []
    for value in (product.get('priceInfo'), product.get('price'), product.get('promotions'),
                  product.get('promotionInfo'), product.get('coupon'), product.get('coupons'),
                  product.get('fulfillmentOptions')):
        if isinstance(value, list): scopes.extend(v for v in value if isinstance(v, dict))
        elif isinstance(value, dict): scopes.append(value)
    for value in scopes:
        if _store_ids(value) and _store_ids(value) != {expected_store.id}:
            result['source_parse_error'] = 'Price/offer/PICKUP store scope contradicts selected store'
            return result
    # Nested explicit store-scoped monetary options must not quietly override
    # the selected page/product context.
    for scope in (product.get('priceInfo'), product.get('promotions'), product.get('promotionInfo')):
        if isinstance(scope, dict):
            for nested_value in scope.values():
                if isinstance(nested_value, dict) and _store_ids(nested_value) and _store_ids(nested_value) != {expected_store.id}:
                    result['source_parse_error'] = 'Nested price/offer store scope conflicts'
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


def run_probe(*, store: Store, url: str = DEFAULT_URL, product_id: str = '',
              render: bool = False, output: str, execute_billable: bool = False,
              billing_approved: bool = False, authorization_id: str = '',
              max_requests: int = 1, max_retries: int = 0, max_seconds: int = 90,
              max_body_bytes: int = 2_000_000,
              session_factory: Callable[[],object] = requests.Session) -> dict:
    if store.id != STORE_ID or store.zipcode != '60085' or '3900 Fountain Square' not in store.address:
        raise ValueError('Diagnostic is bound to client-confirmed Waukegan #3891, ZIP 60085')
    if not (1 <= max_requests <= 2 and 0 <= max_retries <= 1 and 1 <= max_seconds <= 180 and
            32_768 <= max_body_bytes <= 5_000_000):
        raise ValueError('Exceeds fixed review caps: 2 paid jobs, 1 retry, 180 seconds, 5 MB per body')
    jobs = payloads(url, product_id, render)
    if jobs and len(jobs) * (max_retries + 1) > max_requests:
        raise ValueError('Requests including retries exceed approved request cap')
    start = time.monotonic()
    deadline_at = start + max_seconds
    out = Path(output)
    receipt = {'release':'0.5.1', 'provider':'Oxylabs Web Scraper API (Classic)',
               'endpoint': ENDPOINT, 'selected_store':store.id, 'selected_zip':store.zipcode,
               'pickup_required':'PICKUP', 'store_selection_in_api_payload':'NOT_ESTABLISHED',
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
                             else 'NEEDS_PRODUCT_ID_NO_NETWORK_NO_COST')
        receipt['note'] = ('No credential access or paid request. Product ID must come from an observed Walmart source. '
                           'Classic product query has no confirmed Waukegan/PICKUP selector; response must independently prove local price.')
        out.parent.mkdir(parents=True,exist_ok=True)
        _synced_json(out, receipt)  # never a billing reservation
        return receipt
    if not billing_approved:
        raise OxylabsProbeError('Paid execution requires both --execute-billable and --billing-approved')
    if not jobs:
        raise OxylabsProbeError('Provide --product-id for a primary product diagnostic before paid execution')
    username = os.getenv('OXY_WSA_USERNAME','')
    password = os.getenv('OXY_WSA_PASSWORD','')
    if not username or not password:
        raise OxylabsProbeError('Missing Classic API credentials; do not place them in source')
    try:
        budget = PaidBudget(out, authorization_id, max_requests)
        budget.open_receipt(receipt)  # exclusive; no concurrent receipt reuse
    except BudgetError as exc:
        raise OxylabsProbeError(str(exc)) from exc
    session = None
    deadline_exceeded = False
    try:
        session = session_factory()
        for job_index, job in enumerate(jobs, 1):
            for attempt in range(1, max_retries + 2):
                if time.monotonic() >= deadline_at:
                    receipt['status'] = 'DEADLINE_STOP'
                    break
                try:
                    budget.reserve(receipt, job, attempt)  # fsync ledger AND receipt before dispatch
                except BudgetError as exc:
                    receipt['results'].append({'job_index':job_index,'attempt':attempt,'error':str(exc)})
                    receipt['status']='BUDGET_RESERVATION_REFUSED_STOP'
                    break
                try:
                    status, raw = bounded_post(session, ENDPOINT, (username,password), job,
                                               max_body_bytes, deadline_at)
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
                    _synced_json(body_file, sanitized, exclusive=True)
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
                        results=sanitized.get('results') if isinstance(sanitized,dict) else None
                        if not isinstance(results,list) or len(results)!=1 or not isinstance(results[0],dict):
                            reply['error']='UNEXPECTED_CLASSIC_RESPONSE_SHAPE'
                            receipt['status']='UNVERIFIED_RESPONSE_STOP'
                        else:
                            answer=results[0]
                            # Critical: NEVER substitute requested URL for absent returned URL.
                            source_url=answer.get('url')
                            reply['source_url']=source_url or ''
                            reply['job_id']=str(answer.get('job_id') or '')
                            reply['source_status_code']=answer.get('status_code')
                            parsed=urlparse(source_url) if isinstance(source_url,str) else urlparse('')
                            if parsed.scheme!='https' or parsed.hostname not in ('walmart.com','www.walmart.com'):
                                reply['error']='MISSING_OR_UNSAFE_RETURNED_SOURCE_URL'
                                receipt['status']='UNVERIFIED_RESPONSE_STOP'
                            elif parsed.path.casefold().startswith(('/blocked','/challenge','/captcha')) or answer.get('status_code')!=200:
                                reply['error']='RETAILER_ACCESS_RESTRICTION_OR_NON_200'
                                receipt['status']='RETAILER_ACCESS_STOP'
                            elif not re.search(r'/ip/(?:[^/?]+/)?'+re.escape(product_id)+r'(?:[/?#]|$)',parsed.path):
                                reply['error']='RETURNED_PRODUCT_URL_ID_MISMATCH'
                                receipt['status']='UNVERIFIED_RESPONSE_STOP'
                            else:
                                proof=_evaluate_source(answer.get('content'), store, source_url)
                                reply['source_evidence']=proof
                                if str(proof.get('source_parse_error','')).startswith('BlockedResponse'):
                                    reply['error']='RETAILER_CHALLENGE_IN_SOURCE_BODY'
                                    receipt['status']='RETAILER_ACCESS_STOP'
                                elif str(proof.get('product_id','')) != product_id:
                                    reply['error']='PRODUCT_ID_SOURCE_MISMATCH'
                                    receipt['status']='UNVERIFIED_RESPONSE_STOP'
                                elif proof['verification_status']!='SOURCE_SHAPE_VERIFIED_NEEDS_HUMAN_COMPARISON':
                                    receipt['status']='STORE_PICKUP_PRICE_UNVERIFIED_STOP'
                                else:
                                    receipt['source_shape_verified_records']+=1
                                    receipt['status']='SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE'
                    receipt['results'].append(reply)
                    budget.save_receipt(receipt)
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
                    budget.save_receipt(receipt)
                    break
                except (requests.RequestException,ResponseBodyLimit,OxylabsProbeError,OSError,ValueError) as exc:
                    receipt['status']='TRANSPORT_OR_LIMIT_STOP_RESERVED_OUTCOME_UNCERTAIN'
                    receipt['results'].append({'job_index':job_index,'attempt':attempt,
                                               'error':type(exc).__name__,'message':str(exc)[:200]})
                    budget.save_receipt(receipt)
                    break
            if receipt.get('status'):
                break
        receipt.setdefault('status','STORE_PICKUP_PRICE_UNVERIFIED_STOP')
    finally:
        # A timed-out background transport may still be blocked in a socket read;
        # do not block this bounded call waiting for it. It owns NO new paid jobs.
        if session is not None and not deadline_exceeded and hasattr(session,'close'):
            try: session.close()
            except Exception: pass
        receipt['duration_seconds']=round(time.monotonic()-start,3)
        receipt['finished_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
        budget.save_receipt(receipt)
    return receipt


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
    for entry in results:
        if not isinstance(entry,dict) or entry.get('status_code')!=200:
            raise OxylabsProbeError('Source result missing or not HTTP 200')
        url=str(entry.get('url') or '')
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in ('www.walmart.com','walmart.com'):
            raise OxylabsProbeError('Source URL missing or not an actual Walmart URL')
        if parsed.path.casefold().startswith(('/blocked','/challenge','/captcha')):
            raise OxylabsProbeError('Source returned an access-restriction page')
        assessments.append({'source_url':url,'job_id':str(entry.get('job_id') or ''),
                            'source_fields':_evaluate_source(entry.get('content'),store,url)})
    result={'status':'OFFLINE_SOURCE_SHAPE_REVIEW_ONLY','source_input_sha256':sha256(raw).hexdigest(),
            'store_expected':store.id,'pickup_required':'PICKUP',
            'results':assessments,'network_requests':0,'paid_execution':False,
            'genuine_products_verified':0,'buyer_acceptance':False,
            'note':'Input may be genuine or synthetic. Independently authenticate job IDs and compare live prices before acceptance.'}
    out=Path(output_file)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
