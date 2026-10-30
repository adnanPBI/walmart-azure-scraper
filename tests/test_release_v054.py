"""v0.5.4 client review regressions: strictly synthetic + local mock only.

No Walmart requests, paid Oxylabs calls, account credentials, or Azure jobs.
"""
import copy
import json
import re
import time
from pathlib import Path

import pytest

from walmart_azure import oxylabs_classic as classic
from walmart_azure.paid_budget import PaidBudget
from test_release_v05 import MockResponse, MockSession
from test_release_v051 import WAUKEGAN, PID, PRODUCT_URL

FIXTURE=Path(__file__).resolve().parents[1]/'examples'/'oxylabs_classic_SYNTHETIC_WAUKEGAN_3891_STRICT_REVIEW.json'
STRICT_OK='STRICT_SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE'
STRICT_FAIL='STORE_PICKUP_PRICE_UNVERIFIED_STOP'


def envelope(change=None):
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    if change:
        row=raw['results'][0]
        if change in ('missing_url','missing_job_id'):
            row.pop('url' if change=='missing_url' else 'job_id',None)
        elif change=='parsed_only':
            row['content']={'product':{'usItemId':PID}}
        else:
            html=row['content']
            m=re.search(r'(<script id="__NEXT_DATA__">)(.*?)(</script>)',html,re.S)
            assert m
            d=json.loads(m.group(2))
            initial=d['props']['pageProps']['initialData']
            if change=='page_shipping':
                initial['location']['fulfillmentType']='SHIPPING'
            elif change=='page_no_mode':
                initial['location'].pop('fulfillmentType')
            elif change=='page_other_store':
                initial['location']['storeId']='100'
            elif change=='product_shipping_price':
                initial['product']['priceInfo']['fulfillmentType']='SHIPPING'
            elif change=='shipping_offer':
                initial['product']['promotions'][0]['fulfillmentType']='SHIPPING'
            elif change=='missing_price_store':
                initial['product']['priceInfo'].pop('storeId')
            else:
                raise ValueError(change)
            row['content']=html[:m.start(2)]+json.dumps(d)+html[m.end(2):]
    return raw


def invoke(tmp_path, monkeypatch, variant=None, *, session=None, seconds=10):
    monkeypatch.setenv('OXY_WSA_USERNAME','offline-test-user')
    monkeypatch.setenv('OXY_WSA_PASSWORD','offline-test-password')
    approval='LOCAL-REVIEW-'+(variant or 'positive')
    PaidBudget.register_authorization(approval,1)
    if session is None:
        session=MockSession(MockResponse(envelope(variant)))
    started=time.monotonic()
    result=classic.run_probe(store=WAUKEGAN, product_id=PID,
        url=PRODUCT_URL, output=str(tmp_path/'result.json'),
        execute_billable=True,billing_approved=True,
        authorization_id=approval,max_requests=1,max_retries=0,
        max_seconds=seconds,session_factory=lambda:session)
    return result,session,time.monotonic()-started


def test_new_documented_localized_raw_product_payload_is_exact():
    assert classic.payloads(url=PRODUCT_URL,product_id=PID)==[{
        'source':'walmart_product','product_id':PID,
        'store_id':'3891','fulfillment_type':'pickup','parse':False,'render':''}]


def test_live_probe_uses_exact_same_strict_saved_response_gate(tmp_path,monkeypatch):
    result,session,_=invoke(tmp_path,monkeypatch)
    assert len(session.calls)==1
    assert session.calls[0][1]['json']==classic.payloads(PRODUCT_URL,PID)[0]
    assert result['status']==STRICT_OK
    assert result['source_shape_verified_records']==1
    proof=result['results'][0]['source_evidence']
    assert proof['status']=='STRICT_OFFLINE_SOURCE_SHAPE_CANDIDATE_NOT_LIVE_AUTHENTICATED'
    assert proof['provider_job_id']=='SYNTHETIC_JOB_NOT_AUTHENTIC'
    assert proof['price_verified'] and proof['pickup_verified']
    assert proof['candidate_record_sha256']
    assert proof['actual_returned_url'].endswith('/1234567890')
    assert proof['verified_genuine_live_products']==0
    assert not proof['buyer_acceptance']
    assert result['genuine_products_verified']==0 and not result['buyer_acceptance']


@pytest.mark.parametrize('variant',[
    'page_shipping','page_no_mode','page_other_store',
    'product_shipping_price','shipping_offer','missing_price_store',
    'missing_url','missing_job_id','parsed_only'
])
def test_live_probe_rejects_strict_saved_gate_failures(tmp_path,monkeypatch,variant):
    result,session,_=invoke(tmp_path,monkeypatch,variant)
    assert len(session.calls)==1
    assert result['status']==STRICT_FAIL
    assert result['source_shape_verified_records']==0
    assert result['genuine_products_verified']==0
    assert result['buyer_acceptance'] is False
    proof=result['results'][0]['source_evidence']
    assert proof['status']=='REJECTED_INSUFFICIENT_SOURCE_EVIDENCE'
    assert proof['store_verified'] is False
    assert proof['pickup_verified'] is False
    assert proof['price_verified'] is False
    assert proof['price_context_binding_verified'] is False
    assert proof['reasons'] and result['results'][0]['qualification_reasons']


def test_whole_run_deadline_includes_slow_session_close(tmp_path,monkeypatch):
    class DelayedClose(MockSession):
        def close(self):
            time.sleep(1.30)
    session=DelayedClose(MockResponse(envelope()))
    result,_,elapsed=invoke(tmp_path,monkeypatch,'slow-close',session=session,seconds=1)
    assert elapsed<1.25,elapsed
    assert result['status']=='DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN'
    assert result['source_shape_verified_records']==0
    assert result['genuine_products_verified']==0
    assert result['buyer_acceptance'] is False


def test_whole_run_deadline_bounds_slow_response_processing(tmp_path,monkeypatch):
    original=classic._sanitize
    def slow_sanitize(value):
        time.sleep(1.30)
        return original(value)
    monkeypatch.setattr(classic,'_sanitize',slow_sanitize)
    result,session,elapsed=invoke(tmp_path,monkeypatch,'slow-process',seconds=1)
    assert elapsed<1.25,elapsed
    assert len(session.calls)==1
    assert result['status']=='DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN'
    assert result['source_shape_verified_records']==0
    assert result['genuine_products_verified']==0
