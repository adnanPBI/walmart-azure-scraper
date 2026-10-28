"""Independent client review examples, entirely synthetic except localhost streaming.

No Walmart, Azure or paid Oxylabs requests are made by these tests.
"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
import time
import pytest
from walmart_azure import oxylabs_classic as classic
from walmart_azure.config import Config
from walmart_azure.extract import get_weight, parse_deals, ParseError, find_ppm
from walmart_azure.pipeline import run_store
from walmart_azure.storage import LocalStorage
from test_release_v05 import WAUKEGAN, FakeBrowser, OneDisappears, STORE, CFG, MockResponse, MockSession

PID='1234567890'
PRODUCT_URL=f'https://www.walmart.com/ip/item/{PID}'


def product(store_ids=('3891',), price_store=None, pickup_store=None, clipping=False):
    price={'currentPrice':{'price':'4.00'},'unitPrice':'$0.25/oz'}
    if price_store: price['storeId']=price_store
    pickup={'type':'PICKUP','status':'IN_STOCK'}
    if pickup_store: pickup['storeId']=pickup_store
    return {'usItemId':PID, 'name':'SYNTHETIC Soda 12 fl oz, 12 Pack',
            'size':'12 fl oz', 'canonicalUrl':f'/ip/item/{PID}', 'sellerName':'Walmart.com',
            'location':{'storeIds':list(store_ids)},'fulfillmentOptions':[pickup],
            'priceInfo':price, 'promotions':[{'type':'MULTIBUY','text':'2 for $5',
                                            'requiresClipping':clipping,'terms':'Valid through 10/31'}]}


def html_for(p, page_store='3891'):
    return '<html><script id="__NEXT_DATA__">'+json.dumps({
        'props':{'pageProps':{'initialData':{
            'location':{'storeId':page_store}, 'product':p}}}})+'</script></html>'


def source_envelope(content, url=PRODUCT_URL):
    entry={'status_code':200,'job_id':'SYNTHETIC_JOB','content':content}
    if url is not None: entry['url']=url
    return {'results':[entry]}


def test_cross_store_page_100_product_3891_rejected():
    evidence=classic._evaluate_source(html_for(product(), page_store='100'),WAUKEGAN,PRODUCT_URL)
    assert not evidence['store_verified']
    assert not evidence['pickup_verified']
    assert not evidence['price_verified']
    assert 'Page selected store' in evidence['source_parse_error']


def test_multistore_product_is_not_price_bound_to_requested_store():
    evidence=classic._evaluate_source(html_for(product(('100','3891'))),WAUKEGAN,PRODUCT_URL)
    assert not evidence['price_verified'] and not evidence['store_verified']
    assert 'multiple' in evidence['source_parse_error']


@pytest.mark.parametrize('kwargs', [{'price_store':'100'}, {'pickup_store':'100'}])
def test_conflicting_price_or_pickup_scope_never_verifies(kwargs):
    evidence=classic._evaluate_source(html_for(product(**kwargs)),WAUKEGAN,PRODUCT_URL)
    assert not evidence['price_verified'] and not evidence['pickup_verified']
    assert 'scope' in evidence['source_parse_error']


def test_positive_synthetic_html_has_auditable_shared_context():
    e=classic._evaluate_source(html_for(product()),WAUKEGAN,PRODUCT_URL)
    assert e['store_verified'] and e['pickup_verified'] and e['price_verified']
    assert e['price_context']['selected_page_store']=='3891'
    assert e['ppm_direct']=='$0.25/oz'
    assert not e['buyer_acceptance']


def test_parsed_product_without_page_selection_never_claims_locality():
    e=classic._evaluate_source(product(),WAUKEGAN,PRODUCT_URL)
    assert not e['store_verified'] and not e['pickup_verified'] and not e['price_verified']


def test_missing_returned_url_is_not_synthesized(tmp_path, monkeypatch):
    monkeypatch.setenv('OXY_WSA_USERNAME','fixture')
    monkeypatch.setenv('OXY_WSA_PASSWORD','fixture')
    session=MockSession(MockResponse(source_envelope(html_for(product()),url=None)))
    result=classic.run_probe(store=WAUKEGAN,product_id=PID,output=str(tmp_path/'no-url.json'),
        execute_billable=True,billing_approved=True,authorization_id='TEST-URL-MISSING',
        session_factory=lambda:session)
    assert result['status']=='UNVERIFIED_RESPONSE_STOP'
    assert result['results'][0]['error']=='MISSING_OR_UNSAFE_RETURNED_SOURCE_URL'
    assert result['source_shape_verified_records']==0
    assert result['requests_sent']==1


def test_primary_product_only_and_default_without_id_no_network(tmp_path):
    assert classic.payloads(product_id=PID)==[{'source':'walmart_product','query':PID,'parse':True}]
    assert classic.payloads()==[]
    r=classic.run_probe(store=WAUKEGAN,output=str(tmp_path/'dry.json'))
    assert r['status']=='NEEDS_PRODUCT_ID_NO_NETWORK_NO_COST' and r['requests_sent']==0
    with pytest.raises(classic.OxylabsProbeError,match='product-id'):
        classic.run_probe(store=WAUKEGAN,output=str(tmp_path/'paid.json'),execute_billable=True,
                          billing_approved=True)


def test_ledger_reservation_is_durable_and_reused_approval_stops(tmp_path,monkeypatch):
    monkeypatch.setenv('OXY_WSA_USERNAME','fixture')
    monkeypatch.setenv('OXY_WSA_PASSWORD','fixture')
    approval='CLIENT-FIXTURE-GRANT-1'
    mock=MockSession(MockResponse({'error':'provider down'},503))
    first=classic.run_probe(store=WAUKEGAN,product_id=PID,output=str(tmp_path/'first.json'),
        execute_billable=True,billing_approved=True,authorization_id=approval,session_factory=lambda:mock)
    assert first['requests_sent']==1 and first['status']=='PROVIDER_5XX_STOP'
    ledger=Path(first['authorization_ledger'])
    assert ledger.exists() and len(json.loads(ledger.read_text())['attempts'])==1
    second_session=MockSession(MockResponse({'message':'should not dispatch'},503))
    second=classic.run_probe(store=WAUKEGAN,product_id=PID,output=str(tmp_path/'second.json'),
        execute_billable=True,billing_approved=True,authorization_id=approval,
        session_factory=lambda:second_session)
    assert second['status']=='BUDGET_RESERVATION_REFUSED_STOP'
    assert second['requests_sent']==0 and not second_session.calls
    assert len(json.loads(ledger.read_text())['attempts'])==1
    with pytest.raises(classic.OxylabsProbeError,match='already exists'):
        classic.run_probe(store=WAUKEGAN,product_id=PID,output=str(tmp_path/'first.json'),
            execute_billable=True,billing_approved=True,authorization_id=approval,
            session_factory=lambda:second_session)


def test_slow_localhost_stream_has_independent_hard_return_deadline(tmp_path,monkeypatch):
    class SlowStream(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            for _ in range(200):
                try:
                    self.wfile.write(b'X'*64)
                    self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):
                    break
                time.sleep(.025)
    server=ThreadingHTTPServer(('127.0.0.1',0),SlowStream)
    server.daemon_threads=True
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    monkeypatch.setattr(classic,'ENDPOINT',f'http://127.0.0.1:{server.server_port}/v1/queries')
    monkeypatch.setenv('OXY_WSA_USERNAME','fixture')
    monkeypatch.setenv('OXY_WSA_PASSWORD','fixture')
    try:
        start=time.monotonic()
        r=classic.run_probe(store=WAUKEGAN,product_id=PID,output=str(tmp_path/'slow.json'),
            execute_billable=True,billing_approved=True,authorization_id='TEST-SLOW-STREAM-1',
            max_seconds=1)
        elapsed=time.monotonic()-start
        assert elapsed<1.50,elapsed
        assert r['requests_sent']==1 and r['status']=='DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN'
        assert Path(r['authorization_ledger']).exists()
        assert json.loads((tmp_path/'slow.json').read_text())['attempts'][0]['billing_outcome'].startswith('UNKNOWN')
    finally:
        server.shutdown()
        server.server_close()


def test_clipping_multibuy_is_digital_with_complete_terms_and_price():
    p=product(clipping=True)
    p['promotions'][0]['terms']={'limit':'Limit 1 offer per household','validUntil':'Valid through 10/31',
                                  'eligibility':'One clipped offer only'}
    o=parse_deals(p)
    assert o['volume_deals_description']==''
    assert o['digital_deals_price']=='5.00'
    for x in ('Limit 1 offer per household','Valid through 10/31','One clipped offer only'):
        assert x in o['digital_deals_description']


def test_long_offer_terms_are_not_silently_truncated():
    terms='T'*3500
    o=parse_deals({'promotions':[{'type':'MULTIBUY','text':'2 for $5','terms':terms}]})
    assert terms in o['volume_deals_description']
    with pytest.raises(ParseError,match='exceed review limit'):
        parse_deals({'promotions':[{'type':'MULTIBUY','text':'2 for $5','terms':'Z'*200100}]})


def test_trailing_pack_count_preserved_and_ppm_direct_only():
    p={'name':'Soda 12 fl oz, 12 Pack', 'size':'12 fl oz',
       'priceInfo':{'unitPrice':'$0.25/fl oz'}}
    assert get_weight(p)=='12 fl oz, 12 Pack'
    assert find_ppm(p)=='$0.25/fl oz'
    assert get_weight({'name':'Soda 12 pack of 12 fl oz cans'})=='12 pack of 12 fl oz cans'


@pytest.mark.asyncio
async def test_carried_canary_is_not_fresh_canary(tmp_path):
    from test_release_v05 import OneDisappears
    db=LocalStorage(str(tmp_path))
    chosen=replace(STORE,canary_item_ids=('1000000150',))
    cfg=Config(stores=[chosen],categories=CFG.categories,limits=CFG.limits)
    first=await run_store(chosen,cfg,db,'canary-first',browser_type=FakeBrowser)
    assert first['status']=='PASS',first['reasons']
    pointer=db.load('latest/100.json')
    second=await run_store(chosen,cfg,db,'canary-disappears',browser_type=OneDisappears)
    assert second['status']=='FAIL'
    assert second['carried_forward_count']==1
    assert any('canary_missing' in reason for reason in second['reasons'])
    assert db.load('latest/100.json')==pointer
