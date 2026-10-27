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
from .browser import selected_location_from_data
from .extract import (parse_next_data, parse_detail, parse_listing, seller_is_walmart,
                      pickup_availability, match_location, regular_sale, find_ppm, parse_deals,
                      BlockedResponse, ParseError)
from .config import Store

ENDPOINT = 'https://realtime.oxylabs.io/v1/queries'
STORE_ID = '3891'
DEFAULT_URL = 'https://www.walmart.com/cp/food/976759'
SENSITIVE_KEY = re.compile(r'(?:password|secret|token|authorization|cookie|session|credential|csrf|nonce|api[_-]?key)',re.I)
SENSITIVE_TEXT = re.compile(r'(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[\w.\-+/=]+|(?i:(?:access_token|refresh_token|api_key|password|secret|sessionid)\s*[=:]\s*["\']?)[\w.\-+/=]+')


class OxylabsProbeError(RuntimeError):
    pass


def payloads(url: str = DEFAULT_URL, product_id: str = '', render: bool = False) -> list[dict]:
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('www.walmart.com', 'walmart.com') or
        parsed.username or parsed.password):
        raise ValueError('Probe accepts only an HTTPS walmart.com page URL')
    jobs = [{'source':'walmart', 'url':url}]
    if render:
        jobs[0]['render'] = 'html'  # JS rendering must be explicitly approved
    if product_id:
        if not re.fullmatch(r'\d{5,20}',product_id):
            raise ValueError('Product ID must be 5-20 digits observed from source')
        jobs.append({'source':'walmart_product','query':product_id,'parse':True})
    return jobs


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


def _evaluate_source(content, expected_store: Store, target_url: str) -> dict:
    """Never infer local pickup from ZIP, geo-location or API 200 status."""
    result = {'store_expected':expected_store.id,'pickup_required':'PICKUP',
              'store_verified':False,'pickup_verified':False,'first_party_verified':False,
              'price_verified':False,'ppm_direct':'','offer_description':{},
              'verification_status':'UNVERIFIED', 'buyer_acceptance':False}
    if isinstance(content, dict):
        result['original_retailer_html_available'] = False
        # Parsed Oxylabs response shape is NOT guaranteed to have storefront
        # store/pickup provenance. Detect only known explicit source models.
        data = content
        product = data.get('product') if isinstance(data.get('product'),dict) else data
    elif isinstance(content,str):
        result['original_retailer_html_available'] = True
        try:
            data = parse_next_data(content)
        except (BlockedResponse,ParseError) as exc:
            result['source_parse_error'] = type(exc).__name__ + ': ' + str(exc)
            return result
        location,_ = selected_location_from_data(data)
        result['store_proven_in_page'] = location or ''
        from .extract import _explicit_node
        product = _explicit_node(data,'product')
        try:
            listing = parse_listing(content)
            result['listing_candidate_count']=len(listing.products)
            result['reported_count']=listing.reported_count
            result['max_page']=listing.max_page
        except (BlockedResponse,ParseError) as exc:
            result['listing_parse_status']=type(exc).__name__
    else:
        result['source_parse_error']='Unrecognized Oxylabs content type'
        return result
    if isinstance(product,dict):
        store_ok,reason=match_location(product,expected_store)
        result['store_proven_in_product']=reason if store_ok else ''
        result['store_verified']=bool(store_ok)
        result['pickup_verified']=pickup_availability(product) in ('AVAILABLE','UNAVAILABLE') and store_ok
        result['first_party_verified']=seller_is_walmart(product)
        price=regular_sale(product)[0]
        result['observed_price']=price
        result['price_verified']=bool(price and result['pickup_verified'] and result['first_party_verified'])
        result['ppm_direct']=find_ppm(product)
        result['offer_description']=parse_deals(product)
        result['product_id']=str(product.get('usItemId') or product.get('itemId') or '')
    if (result.get('original_retailer_html_available') and
        all(result.get(key) for key in ('store_verified','pickup_verified','first_party_verified','price_verified'))):
        result['verification_status']='SOURCE_SHAPE_VERIFIED_NEEDS_HUMAN_COMPARISON'
    return result


def run_probe(*, store: Store, url: str = DEFAULT_URL, product_id: str = '',
              render: bool = False, output: str, execute_billable: bool = False,
              billing_approved: bool = False, max_requests: int = 2,
              max_retries: int = 0, max_seconds: int = 90,
              max_body_bytes: int = 2_000_000,
              session_factory: Callable[[],object] = requests.Session) -> dict:
    if store.id != STORE_ID or store.zipcode != '60085' or '3900 Fountain Square' not in store.address:
        raise ValueError('Diagnostic is bound to client-confirmed Waukegan #3891, ZIP 60085')
    if not (1 <= max_requests <= 2 and 0 <= max_retries <= 1 and 1 <= max_seconds <= 180 and
            32_768 <= max_body_bytes <= 5_000_000):
        raise ValueError('Exceeds fixed review caps: 2 jobs, 1 retry, 180 seconds, 5 MB per body')
    jobs = payloads(url,product_id,render)
    if len(jobs)*(max_retries+1) > max_requests:
        raise ValueError('Requests including retries exceed approved request cap')
    start=time.monotonic()
    out=Path(output)
    receipt={'release':'0.5.0','provider':'Oxylabs Web Scraper API (Classic)',
             'endpoint':ENDPOINT,'selected_store':store.id,'selected_zip':store.zipcode,
             'pickup_required':'PICKUP','request_cap_total_including_retries':max_requests,
             'retry_cap_per_job':max_retries,'deadline_seconds':max_seconds,
             'body_cap_bytes':max_body_bytes, 'render_requested':render,
             'paid_execution':bool(execute_billable),'requests_sent':0,
             'jobs_planned':jobs,'results':[],'genuine_products_verified':0,
             'source_shape_verified_records':0,
             'azure_execution':False,'buyer_acceptance':False,
             'started_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if not execute_billable:
        receipt['status']='DRY_RUN_NO_NETWORK_NO_COST'
        receipt['note']='No auth credentials read, no network requests sent; payloads for client approval only.'
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
        return receipt
    if not billing_approved:
        raise OxylabsProbeError('Paid execution requires BOTH --execute-billable and --billing-approved')
    username=os.getenv('OXY_WSA_USERNAME','')
    password=os.getenv('OXY_WSA_PASSWORD','')
    if not username or not password:
        raise OxylabsProbeError('Missing OXY_WSA_USERNAME/OXY_WSA_PASSWORD; do not place them in source')
    if out.exists():
        raise OxylabsProbeError('Existing receipt path; choose a new output to preserve prior evidence')
    out.parent.mkdir(parents=True,exist_ok=True)
    session=session_factory()
    try:
        for index, job in enumerate(jobs,1):
            attempts=0
            while attempts <= max_retries:
                if receipt['requests_sent'] >= max_requests:
                    receipt['status']='REQUEST_LIMIT_STOP'
                    break
                remaining=max_seconds-(time.monotonic()-start)
                if remaining <= 0:
                    receipt['status']='DEADLINE_STOP'
                    break
                receipt['requests_sent']+=1
                attempts+=1
                try:
                    response=session.post(ENDPOINT,auth=(username,password),json=job,
                                          timeout=(min(10,remaining), min(40,remaining)),
                                          allow_redirects=False,stream=True)
                    raw=b''
                    for part in response.iter_content(chunk_size=64*1024):
                        if part:
                            raw+=part
                        if len(raw)>max_body_bytes:
                            raise OxylabsProbeError('RESPONSE_BODY_LIMIT_STOP')
                        if time.monotonic()-start>=max_seconds:
                            raise OxylabsProbeError('DEADLINE_STOP')
                    reply={'job_index':index,'attempt':attempts,'http_status':response.status_code,
                           'request_payload':job,'response_bytes':len(raw),
                           'raw_response_sha256':sha256(raw).hexdigest(),
                           'received_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
                    body_path=out.parent/(out.stem+f'.job{index:02}.attempt{attempts}.sanitized.json')
                    try:
                        full=json.loads(raw)
                        sanitized=_sanitize(full)
                    except (ValueError,UnicodeDecodeError):
                        sanitized={'raw_text':_sanitize(raw.decode('utf-8','replace'))}
                    # Save the COMPLETE sanitized provider envelope, not selected fields.
                    body_path.write_text(json.dumps(sanitized,ensure_ascii=False,indent=2),encoding='utf-8')
                    reply['sanitized_response_body']=str(body_path)
                    reply['sanitized_body_sha256']=sha256(body_path.read_bytes()).hexdigest()
                    if response.status_code in (401,403):
                        reply['error']='PROVIDER_AUTH_DENIED'
                        receipt['status']='AUTH_DENIED_STOP'
                    elif response.status_code == 429:
                        reply['error']='PROVIDER_RATE_LIMIT'
                        receipt['status']='RATE_LIMIT_STOP'
                    elif response.status_code >= 500:
                        reply['error']='PROVIDER_TRANSIENT_ERROR'
                    elif response.status_code != 200:
                        reply['error']='PROVIDER_NON_200'
                        receipt['status']='PROVIDER_NON_200_STOP'
                    else:
                        results=sanitized.get('results') if isinstance(sanitized,dict) else None
                        if not isinstance(results,list) or len(results)!=1 or not isinstance(results[0],dict):
                            reply['error']='UNEXPECTED_CLASSIC_RESPONSE_SHAPE'
                            receipt['status']='UNVERIFIED_RESPONSE_STOP'
                        else:
                            answer=results[0]
                            source_url=str(answer.get('url') or job.get('url') or '')
                            reply['job_id']=str(answer.get('job_id') or '')
                            reply['source_url']=source_url
                            reply['source_status_code']=answer.get('status_code')
                            parsed_url = urlparse(source_url)
                            if parsed_url.scheme != 'https' or parsed_url.hostname not in ('www.walmart.com','walmart.com'):
                                reply['error']='MISSING_OR_UNSAFE_SOURCE_URL'
                                receipt['status']='UNVERIFIED_RESPONSE_STOP'
                            elif job.get('url') and parsed_url.path.rstrip('/') != urlparse(job['url']).path.rstrip('/'):
                                reply['error']='RETAILER_SOURCE_PATH_CHANGED_OR_REDIRECTED'
                                receipt['status']='UNVERIFIED_RESPONSE_STOP'
                            elif (answer.get('status_code') != 200 or
                                parsed_url.path.casefold().startswith(('/blocked','/challenge','/captcha'))):
                                reply['error']='RETAILER_ACCESS_RESTRICTION_OR_NON_200'
                                receipt['status']='RETAILER_ACCESS_STOP'
                            else:
                                proof=_evaluate_source(answer.get('content'),store,job.get('url') or '')
                                reply['source_evidence']=proof
                                if str(proof.get('source_parse_error','')).startswith('BlockedResponse'):
                                    reply['error']='RETAILER_CHALLENGE_IN_SOURCE_BODY'
                                    receipt['status']='RETAILER_ACCESS_STOP'
                                elif job.get('query') and proof.get('product_id') != job['query']:
                                    reply['error']='PRODUCT_ID_SOURCE_MISMATCH'
                                    receipt['status']='UNVERIFIED_RESPONSE_STOP'
                                elif proof['verification_status'] != 'SOURCE_SHAPE_VERIFIED_NEEDS_HUMAN_COMPARISON':
                                    receipt['status']='STORE_PICKUP_PRICE_UNVERIFIED_STOP'
                                else:
                                    receipt['source_shape_verified_records']+=1  # human comparison still required
                    receipt['results'].append(reply)
                    if hasattr(response,'close'):
                        response.close()
                    if receipt.get('status') in ('AUTH_DENIED_STOP','RATE_LIMIT_STOP','PROVIDER_NON_200_STOP',
                                                 'RETAILER_ACCESS_STOP','UNVERIFIED_RESPONSE_STOP',
                                                 'STORE_PICKUP_PRICE_UNVERIFIED_STOP'):
                        break
                    if response.status_code >= 500 and attempts > max_retries:
                        receipt['status']='PROVIDER_5XX_STOP'
                    if response.status_code >= 500 and attempts <= max_retries:
                        if time.monotonic()-start+2>= max_seconds:
                            receipt['status']='DEADLINE_STOP'
                            break
                        time.sleep(2)  # bounded only for server errors
                        continue
                    break
                except (requests.RequestException,OxylabsProbeError) as exc:
                    receipt['results'].append({'job_index':index,'attempt':attempts,
                                               'error':type(exc).__name__,
                                               'message':str(exc)[:200]})
                    receipt['status']='TRANSPORT_OR_LIMIT_STOP'
                    break
            if receipt.get('status'):
                break
        receipt.setdefault('status','SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE')
    finally:
        if hasattr(session,'close'):session.close()
        receipt['duration_seconds']=round(time.monotonic()-start,3)
        receipt['finished_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
        out.write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
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
