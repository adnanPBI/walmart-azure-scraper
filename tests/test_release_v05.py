"""v0.5.0 independent synthetic runner regressions and Classic API transport tests.
Never claim these fixture responses are observed Walmart data.
"""
from __future__ import annotations
import asyncio
import json
import hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import pytest
from walmart_azure.extract import parse_deals, get_weight, parse_listing, ParseError
from walmart_azure.report import record_identity
from walmart_azure.pipeline import run_store
from walmart_azure.storage import LocalStorage
from walmart_azure.browser import BrowserFailure
from walmart_azure.oxylabs_classic import run_probe, payloads, OxylabsProbeError, _evaluate_source
from walmart_azure.paid_budget import PaidBudget
from test_pipeline import FakeBrowser, STORE, CFG, CATS
from walmart_azure.config import Store

WAUKEGAN=Store('3891','60085','Walmart Supercenter #3891','3900 Fountain Square Pl','Waukegan','IL')
SOURCE_URL='https://www.walmart.com/ip/item/1234567890'


def test_pack_preservation_not_derived_total():
    assert get_weight({'name':'Soda 12 pack of 12 fl oz cans', 'size':'12 fl oz'}) == '12 pack of 12 fl oz cans'
    assert get_weight({'name':'Soda 6 x 16.9 fl oz bottles'}) == '6 x 16.9 fl oz bottles'
    assert get_weight({'name':'Single fresh milk 14 oz'}) == '14 oz'


def test_complete_linked_offer_terms_not_savings_price():
    offers={'promotions':[
        {'type':'MULTIBUY','text':'2 for $5', 'terms':{'limit':'Limit 1 offer per household',
                                                  'validThrough':'Valid through 10/31',
                                                  'eligibility':'Mix and match qualifying items',
                                                  'quantity':2}},
        {'type':'DIGITAL_COUPON','text':'Save $2 each with Digital Coupon',
         'conditions':{'clippingRequirement':'Clip coupon', 'limit':'Limit 4',
                       'validUntil':'Valid through 10/31'}}]}
    got=parse_deals(offers)
    assert got['volume_deals_price']=='5.00'
    assert 'Limit 1 offer per household' in got['volume_deals_description']
    assert 'Valid through 10/31' in got['volume_deals_description']
    assert 'Mix and match qualifying items' in got['volume_deals_description']
    assert got['digital_deals_price']==''
    assert 'Limit 4' in got['digital_deals_description']
    assert 'Clip coupon' in got['digital_deals_description']
    assert 'Valid through 10/31' in got['digital_deals_description']
    assert 'Limit 1' not in got['digital_deals_description']
    assert 'Clip coupon' not in got['volume_deals_description']


def test_only_stated_payable_price():
    assert parse_deals({'coupon':{'type':'DIGITAL_COUPON','text':'Save $2 each with Digital Coupon'}})['digital_deals_price']==''
    assert parse_deals({'coupon':{'type':'DIGITAL_COUPON','text':'$3.99 each with Digital Coupon'}})['digital_deals_price']=='3.99'
    assert parse_deals({'promotions':[{'text':'Buy 1, Get 1 Free'}]})['volume_deals_price']==''


def test_pagination_never_assumes_one_page_without_positive_source():
    node={'props':{'pageProps':{'initialData':{'searchResult':{'itemStacks':[
        {'items':[{'usItemId':'1234567890','canonicalUrl':'/ip/fake/1234567890'}]}]}}}}}
    def html(): return '<html><script id="__NEXT_DATA__">'+json.dumps(node)+'</script></html>'
    with pytest.raises(ParseError,match='Pagination missing'):
        parse_listing(html())
    node['props']['pageProps']['initialData']['searchResult']['paginationV2']={'hasNextPage':False}
    assert parse_listing(html()).max_page==1


class OneDisappears(FakeBrowser):
    async def listing(self,url):
        _, meta, products = await super().listing(url)
        if '/milk/' in url:
            meta['reported_count']=299
            if parse_qs(urlparse(url).query).get('page',['1'])[0]=='2':
                products=products[1:]
        return '',meta,products


@pytest.mark.asyncio
async def test_runner_600_then_599_carries_missing_product_with_provenance(tmp_path):
    db=LocalStorage(str(tmp_path))
    first=await run_store(STORE,CFG,db,'fixture-good-600',browser_type=FakeBrowser)
    assert first['status']=='PASS' and first['total_unique']==600
    before=db.load('runs/100/fixture-good-600/products.json')
    missing_pid='1000000150'
    original=next(r for r in before if record_identity(r)==missing_pid)
    second=await run_store(STORE,CFG,db,'fixture-good-599',browser_type=OneDisappears)
    assert second['status']=='PASS',second['reasons']
    assert second['fresh_unique']==599
    assert second['carried_forward_count']==1
    assert second['total_unique']==600
    assert second['priced_record_count']==599
    after=db.load('runs/100/fixture-good-599/products.json')
    assert len(after)==600
    restored=next(r for r in after if record_identity(r)==missing_pid)
    assert restored==original
    sidecar=db.load('runs/100/fixture-good-599/product_source_evidence.json')
    r=next(x for x in sidecar['records'] if x['product_id']==missing_pid)
    assert r['observation_state']=='CARRIED_FORWARD_MISSING'
    assert r['last_known_availability']=='AVAILABLE'
    assert r['current_price_verified'] is False and r['historical_prices_not_current'] is True
    assert r['first_observed_date']==original['crawl_date']
    assert r['last_observed_date']==original['crawl_date']
    assert r['detail_proof']['store_id']=='100'
    assert db.load('latest/100.json')['total_unique']==600
    third=await run_store(STORE,CFG,db,'fixture-good-598',browser_type=OneDisappears)
    assert third['status']=='PASS' and third['carried_forward_count']==1
    assert third['total_unique']==600


class OneOutOfStock(FakeBrowser):
    async def detail(self,url,expected_id):
        data,proof=await super().detail(url,expected_id)
        if expected_id=='1000000150':
            data['fulfillmentOptions']=[{'type':'PICKUP','status':'OUT_OF_STOCK'}]
            data['priceInfo']={}
        return data,proof


@pytest.mark.asyncio
async def test_runner_explicit_oos_retained_and_disappearance_next_run(tmp_path):
    db=LocalStorage(str(tmp_path))
    first=await run_store(STORE,CFG,db,'fixture-oos',browser_type=OneOutOfStock)
    assert first['status']=='PASS' and first['unpriced_unavailable_count']==1
    assert first['priced_record_count']==599
    second=await run_store(STORE,CFG,db,'fixture-oos-missing',browser_type=OneDisappears)
    assert second['status']=='PASS'
    assert second['carried_forward_count']==1
    src=db.load('runs/100/fixture-oos-missing/product_source_evidence.json')['records']
    missing=next(x for x in src if x['product_id']=='1000000150')
    assert missing['availability']=='UNAVAILABLE'
    assert missing['last_known_availability']=='UNAVAILABLE'
    assert missing['observation_state']=='CARRIED_FORWARD_MISSING'


class FailedDetail(FakeBrowser):
    async def detail(self,url,expected_id):
        if expected_id=='1000000150':
            raise BrowserFailure('synthetic detail failure')
        return await super().detail(url,expected_id)


@pytest.mark.asyncio
async def test_runner_one_required_detail_failure_rejects_publish(tmp_path):
    db=LocalStorage(str(tmp_path))
    first=await run_store(STORE,CFG,db,'fixture-before',browser_type=FakeBrowser)
    pointer=db.load('latest/100.json')
    second=await run_store(STORE,CFG,db,'fixture-failed-one',browser_type=FailedDetail)
    assert second['status']=='FAIL'
    assert any('required_detail_failed' in r for r in second['reasons'])
    assert any('unresolved_candidates' in r for r in second['reasons'])
    assert db.load('latest/100.json')==pointer


def test_classic_payload_review_and_credentials_never_needed_offline(tmp_path,monkeypatch):
    monkeypatch.delenv('OXY_WSA_USERNAME',raising=False)
    monkeypatch.delenv('OXY_WSA_PASSWORD',raising=False)
    path=tmp_path/'receipt.json'
    r=run_probe(store=WAUKEGAN,product_id='1234567890',url=SOURCE_URL,output=str(path))
    assert r['status']=='DRY_RUN_NO_NETWORK_NO_COST' and r['requests_sent']==0
    assert r['jobs_planned']==[{'source':'walmart','url':SOURCE_URL,'parse':False}]
    assert json.loads(path.read_text())==r
    with pytest.raises(OxylabsProbeError,match='Paid execution'):
        run_probe(store=WAUKEGAN,output=str(tmp_path/'not-allowed.json'),execute_billable=True)
    with pytest.raises(ValueError,match='review caps'):
        run_probe(store=WAUKEGAN,output=str(tmp_path/'bad.json'),product_id='1234567890',max_requests=0)
    assert payloads(product_id='1234567890')==[]
    assert payloads(url=SOURCE_URL,product_id='1234567890')[0]=={'source':'walmart','url':SOURCE_URL,'parse':False}


class MockResponse:
    def __init__(self,payload,status=200):
        self.body=json.dumps(payload).encode()
        self.status_code=status
    def iter_content(self,chunk_size=65536):
        yield self.body


class MockSession:
    def __init__(self,response):
        self.response=response
        self.calls=[]
    def post(self,url,**kw):
        self.calls.append((url,kw))
        return self.response
    def close(self):pass


def test_classic_transport_is_bounded_sanitized_and_evidence_separated(tmp_path,monkeypatch):
    PaidBudget.register_authorization('TEST-APPROVAL-123',1)
    monkeypatch.setenv('OXY_WSA_USERNAME','synthetic-account')
    monkeypatch.setenv('OXY_WSA_PASSWORD','TOPSECRET')
    product={'usItemId':'1234567890','name':'SYNTHETIC item 12 oz',
             'canonicalUrl':'/ip/item/1234567890', 'sellerName':'Walmart.com',
             'location':{'storeIds':['3891']},
             'fulfillmentOptions':[{'type':'PICKUP','status':'IN_STOCK'}],
             'priceInfo':{'currentPrice':{'price':'2.50'},'unitPrice':'$0.25/oz'},
             'promotions':[{'text':'2 for $5','terms':'Limit 1; Valid through 10/31'}]}
    hydration={'props':{'pageProps':{'initialData':{'location':{'storeId':'3891'},'product':product}}}}
    html='<html><script id="__NEXT_DATA__">'+json.dumps(hydration)+'</script></html>'
    response={'results':[{'status_code':200,'url':'https://www.walmart.com/ip/item/1234567890',
                           'job_id':'synthetic_job','content':html}],
              'session_token':'do-not-store-this'}
    session=MockSession(MockResponse(response))
    path=tmp_path/'probe.json'
    r=run_probe(store=WAUKEGAN,output=str(path),execute_billable=True,billing_approved=True,product_id='1234567890',url=SOURCE_URL,authorization_id='TEST-APPROVAL-123',
                session_factory=lambda:session,max_requests=1)
    assert r['requests_sent']==1
    assert r['source_shape_verified_records']==1
    assert r['genuine_products_verified']==0
    assert r['buyer_acceptance'] is False
    assert r['status']=='SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE'
    assert len(session.calls)==1 and session.calls[0][1]['json']['source']=='walmart'
    sanitized=Path(r['results'][0]['sanitized_response_body']).read_text()
    assert 'TOPSECRET' not in sanitized and 'do-not-store-this' not in sanitized
    assert '$0.25/oz' in sanitized and 'Limit 1' in sanitized and '2.50' in sanitized
    assert r['results'][0]['source_evidence']['pickup_verified']
    assert r['results'][0]['raw_response_sha256']==hashlib.sha256(json.dumps(response).encode()).hexdigest()


def test_classic_body_cap_and_auth_denial_stop_without_retry(tmp_path,monkeypatch):
    PaidBudget.register_authorization('TEST-APPROVAL-123',2)
    monkeypatch.setenv('OXY_WSA_USERNAME','test')
    monkeypatch.setenv('OXY_WSA_PASSWORD','test')
    path=tmp_path/'denied.json'
    session=MockSession(MockResponse({'error':'auth refused'},401))
    r=run_probe(store=WAUKEGAN,output=str(path),execute_billable=True,billing_approved=True,product_id='1234567890',url=SOURCE_URL,authorization_id='TEST-APPROVAL-123',
                session_factory=lambda:session,max_requests=2,max_retries=1)
    assert r['status']=='AUTH_DENIED_STOP' and r['requests_sent']==1
    assert len(session.calls)==1
    with pytest.raises(ValueError):
        run_probe(store=WAUKEGAN,output=str(tmp_path/'bad.json'),max_requests=3)



def test_savings_with_up_to_are_not_payable_prices():
    out=parse_deals({'promotions':[{'type':'DIGITAL_COUPON','text':'Save up to $2 each with Digital Coupon'}]})
    assert out['digital_deals_price']==''


class InflatedPageCount(FakeBrowser):
    async def listing(self,url):
        _,meta,products=await super().listing(url)
        if '/milk/' in url:
            meta['reported_count']=301
        return '',meta,products


@pytest.mark.asyncio
async def test_runner_rejects_one_unreconciled_listing_even_above_500(tmp_path):
    db=LocalStorage(str(tmp_path))
    await run_store(STORE,CFG,db,'baseline',browser_type=FakeBrowser)
    before=db.load('latest/100.json')
    bad=await run_store(STORE,CFG,db,'one-unresolved',browser_type=InflatedPageCount)
    assert bad['status']=='FAIL'
    assert any('pagination_truncation_or_thin_result' in s for s in bad['reasons'])
    assert db.load('latest/100.json')==before


def test_offline_classic_saved_response_never_claims_live(tmp_path):
    from walmart_azure.oxylabs_classic import review_saved_response
    src=tmp_path/'synthetic-provider-response.json'
    src.write_text(json.dumps({'results':[{ 'status_code':200,
       'url':'https://www.walmart.com/ip/item/1234567890',
       'content':'<html>synthetic no product</html>'}]}))
    reviewed=review_saved_response(str(src),str(tmp_path/'review.json'),WAUKEGAN)
    assert reviewed['status']=='OFFLINE_SOURCE_SHAPE_REVIEW_ONLY'
    assert reviewed['buyer_acceptance'] is False
    assert reviewed['genuine_products_verified']==0
    assert reviewed['results'][0]['source_fields']['store_verified'] is False


def test_classic_provider_server_error_no_success(tmp_path,monkeypatch):
    PaidBudget.register_authorization('TEST-APPROVAL-123',1)
    monkeypatch.setenv('OXY_WSA_USERNAME','mockuser')
    monkeypatch.setenv('OXY_WSA_PASSWORD','mockpass')
    session=MockSession(MockResponse({'message':'unavailable'},503))
    r=run_probe(store=WAUKEGAN,output=str(tmp_path/'servererror.json'),
        execute_billable=True,billing_approved=True,product_id='1234567890',url=SOURCE_URL,authorization_id='TEST-APPROVAL-123',session_factory=lambda:session,max_requests=1)
    assert r['status']=='PROVIDER_5XX_STOP'
    assert r['source_shape_verified_records']==0


class OutOfStockWithHistoricalDisplay(FakeBrowser):
    async def detail(self,url,expected_id):
        item,proof=await super().detail(url,expected_id)
        if expected_id=='1000000150':
            item['fulfillmentOptions']=[{'type':'PICKUP','status':'OUT_OF_STOCK'}]
        return item,proof


@pytest.mark.asyncio
async def test_out_of_stock_displayed_price_cannot_count_as_current_pickup_price(tmp_path):
    db=LocalStorage(str(tmp_path))
    report=await run_store(STORE,CFG,db,'oos-with-price',browser_type=OutOfStockWithHistoricalDisplay)
    assert report['status']=='PASS' and report['priced_record_count']==599
    assert report['unavailable_count']==1 and report['total_unique']==600
    from walmart_azure.acceptance import audit_dataset
    items=db.load('runs/100/oos-with-price/products.json')
    sources=db.load('runs/100/oos-with-price/product_source_evidence.json')
    review=audit_dataset(items,CATS,report,
         db.load('runs/100/oos-with-price/evidence.json'),minimum=600,product_sources=sources)
    assert review['price_bearing_records']==599
    assert any('below_minimum_priced:599<600' in x for x in review['issues'])


def test_classic_rejects_source_redirect_with_same_http_200(tmp_path,monkeypatch):
    PaidBudget.register_authorization('TEST-APPROVAL-123',1)
    monkeypatch.setenv('OXY_WSA_USERNAME','mockuser')
    monkeypatch.setenv('OXY_WSA_PASSWORD','mockpass')
    response={'results':[{'status_code':200,'url':'https://www.walmart.com/',
                         'content':'<html>homepage 200 but no requested category</html>'}]}
    r=run_probe(store=WAUKEGAN,output=str(tmp_path/'redirect.json'),execute_billable=True,product_id='1234567890',url=SOURCE_URL,authorization_id='TEST-APPROVAL-123',
                billing_approved=True,session_factory=lambda:MockSession(MockResponse(response)))
    assert r['status']=='UNVERIFIED_RESPONSE_STOP'
    assert r['results'][0]['error']=='RETURNED_PRODUCT_URL_ID_MISMATCH'


def test_classic_rejects_captcha_even_with_provider_200(tmp_path,monkeypatch):
    PaidBudget.register_authorization('TEST-APPROVAL-123',1)
    monkeypatch.setenv('OXY_WSA_USERNAME','mockuser')
    monkeypatch.setenv('OXY_WSA_PASSWORD','mockpass')
    response={'results':[{'status_code':200,'url':'https://www.walmart.com/ip/item/1234567890',
                          'content':'<html><body>Robot or human? CAPTCHA required</body></html>'}]}
    r=run_probe(store=WAUKEGAN,output=str(tmp_path/'challenge.json'),execute_billable=True,product_id='1234567890',url=SOURCE_URL,authorization_id='TEST-APPROVAL-123',
                billing_approved=True,session_factory=lambda:MockSession(MockResponse(response)))
    assert r['status']=='RETAILER_ACCESS_STOP'
    assert r['results'][0]['error']=='RETAILER_CHALLENGE_IN_SOURCE_BODY'


def test_classic_response_size_cap_stops(tmp_path,monkeypatch):
    PaidBudget.register_authorization('TEST-APPROVAL-123',1)
    monkeypatch.setenv('OXY_WSA_USERNAME','mockuser')
    monkeypatch.setenv('OXY_WSA_PASSWORD','mockpass')
    response={'results':[{'content':'x'*80000,'status_code':200,
                          'url':'https://www.walmart.com/ip/item/1234567890'}]}
    r=run_probe(store=WAUKEGAN,output=str(tmp_path/'oversize.json'),execute_billable=True,product_id='1234567890',url=SOURCE_URL,authorization_id='TEST-APPROVAL-123',
                billing_approved=True,max_body_bytes=32768,
                session_factory=lambda:MockSession(MockResponse(response)))
    assert r['status']=='TRANSPORT_OR_LIMIT_STOP_RESERVED_OUTCOME_UNCERTAIN'
    assert r['requests_sent']==1 and r['genuine_products_verified']==0


def test_explicit_promotion_price_field_is_not_savings():
    item={'promotions':[{'type':'DIGITAL_COUPON',
                         'text':'Save $2 each with Digital Coupon',
                         'displayedPromotionalPrice':'Save $2'}]}
    out=parse_deals(item)
    assert 'Save $2' in out['digital_deals_description']
    assert out['digital_deals_price']==''
    item['promotions'][0]['displayedPromotionalPrice']='$3.99'
    assert parse_deals(item)['digital_deals_price']=='3.99'
