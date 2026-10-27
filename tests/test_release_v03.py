"""v0.3: all synthetic/offline tests; never retailer live collection evidence."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import pytest
from walmart_azure.config import Store, Category, Config, Limits, load_config
from walmart_azure.browser import Proof, BrowserFailure, WalmartBrowser
from walmart_azure.extract import (pickup_availability, local_pickup_offer, parse_deals,
                                  find_ppm, parse_listing, ParseError, make_record)
from walmart_azure.pipeline import fetch_category_page, run_store
from walmart_azure.storage import LocalStorage
from walmart_azure.acceptance import audit_dataset
from walmart_azure.diagnostic import diagnostic_probe, validate_probe_budget
from walmart_azure.schema import FIELDS, validate_record

STORE = Store('3891','60085','Walmart Supercenter #3891','3900 Fountain Square Pl','Waukegan','IL')
CAT = Category('Food','Milk','https://www.walmart.com/browse/food/milk/976759_123')
CONFIG = Config([STORE],[CAT],Limits(min_total_records=1,min_category_records=1, page_retries=0,
                                     min_price_shard_yield_ratio=0.01, max_pages_per_category=0))


def product(pid:str,stock='IN_STOCK', price='2.75'):
    return {'usItemId':pid,'canonicalUrl':f'https://www.walmart.com/ip/Item/{pid}',
            'name':f'SYNTHETIC Food Item {pid} 12 oz','sellerName':'Walmart.com',
            'location':{'storeIds':['3891']},
            'fulfillmentOptions':[{'type':'PICKUP','status':stock}],
            'priceInfo': {'currentPrice':{'price':price} if price else { },
                          'unitPrice':{'displayText':'$0.23/oz'}}}


class FakeBrowser:
    synthetic=True
    def __init__(self, store, limits, headless=True):
        self.store=store;self.limits=limits;self.requests=0
        self.navigation_budget=None
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def select_store(self):return Proof('https://www.walmart.com/',self.store.id,'synthetic-ui','PICKUP','2026-10-25T00:00:00Z')
    async def listing(self,url):
        self.requests+=1
        if self.navigation_budget is not None and self.requests > self.navigation_budget:
            raise BrowserFailure('BUDGET_STOP')
        return '',{'max_page':1,'reported_count':2,'proof':Proof(url,self.store.id,'fixture','PICKUP','now','fixture-hash-'+str(self.requests)).as_dict(), 'http_status':200},[
            {'usItemId':'12345678901','canonicalUrl':'/ip/Item/12345678901'},
            {'usItemId':'12345678902','canonicalUrl':'/ip/Item/12345678902'}]
    async def detail(self,url,expected_id):
        self.requests+=1
        if self.navigation_budget is not None and self.requests > self.navigation_budget:
            raise BrowserFailure('BUDGET_STOP')
        item=product(expected_id,'IN_STOCK','2.75') if expected_id.endswith('1') else product(expected_id,'OUT_OF_STOCK','')
        return item,Proof(url,self.store.id,'fixture-detail','PICKUP','now','fixture-detail-hash')


def test_waukegan_store_config_exact_public_example():
    cfg=load_config('config/categories.csv','config/stores.yaml')
    store=cfg.stores[0]
    assert (store.id,store.zipcode,store.address,store.city,store.state)==('3891','60085','3900 Fountain Square Pl','Waukegan','IL')
    assert cfg.limits.max_pages_per_category==0
    assert len(cfg.categories)==11


def test_explicit_pickup_unavailable_retention_classification():
    a=product('12345678901')
    b=product('12345678902','OUT_OF_STOCK','')
    assert pickup_availability(a)=='AVAILABLE' and local_pickup_offer(a)
    assert pickup_availability(b)=='UNAVAILABLE' and not local_pickup_offer(b)
    assert pickup_availability({'fulfillmentOptions':[{'type':'SHIPPING','status':'IN_STOCK'}]})=='UNKNOWN'
    assert pickup_availability({'fulfillmentOptions':[{'type':'SHIPPING','status':'OUT_OF_STOCK'}]})=='UNKNOWN'
    assert pickup_availability({'fulfillmentOptions':[{'type':'PICKUP','status':'UNKNOWN'}]})=='UNKNOWN'


def test_stated_ppm_is_not_derived_and_offers_are_separate():
    p=product('12345678901')
    p['promotions']=[
        {'text':'Buy 1 Get 1 Free, limit 2'},
        {'text':'2 for $5.00'},
        {'text':'Clip Coupon: $1.99 each with Digital Coupon, limit 5'},
        {'text':'Earn $2 Walmart Cash cashback'},
    ]
    d=parse_deals(p)
    assert 'Buy 1 Get 1 Free' in d['volume_deals_description']
    assert d['volume_deals_price']=='5.00'
    assert 'Clip Coupon' in d['digital_deals_description']
    assert d['digital_deals_price']=='1.99'
    assert 'Walmart Cash' not in repr(d)
    assert find_ppm(p)=='$0.23/oz'
    assert find_ppm({'priceInfo':{'unitPrice':{'price':'0.20','unit':'oz'}}})==''
    record=make_record(p, STORE, CAT, '2026-10-25')
    assert tuple(record)==FIELDS
    assert record['unit_price']=='' and record['gupc']==''
    assert record['ppm']=='$0.23/oz'


def test_malformed_or_indeterminate_pagination_rejected():
    data={'props':{'pageProps':{'initialData':{'searchResult':{'itemStacks':[
        {'items':[{'usItemId':'12345678901'}]}], 'aggregatedCount':500}}}}}
    html='<html><script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script></html>'
    with pytest.raises(ParseError, match='Pagination missing'):
        parse_listing(html)
    data['props']['pageProps']['initialData']['searchResult']['paginationV2']={'maxPage':1500}
    html='<html><script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script></html>'
    assert parse_listing(html).max_page==1500


@pytest.mark.asyncio
async def test_unlimited_pagination_accepts_page_report_over_250():
    class Page:
        async def listing(self,url):
            return '', {'max_page':1700,'reported_count':1,
                        'proof': Proof(url,STORE.id,'test','PICKUP','now','hash').as_dict(), 'http_status':200},[
                          {'usItemId':'12345678901','canonicalUrl':'/ip/Item/12345678901'}]
        async def detail(self,url,expected_id):
            return product(expected_id),Proof(url,STORE.id,'test','PICKUP','now')
    chunk=await fetch_category_page(Page(),CONFIG,STORE,CAT,1,CAT.url,'synthetic',{})
    assert chunk['max_page']==1700 and chunk['next_url']


@pytest.mark.asyncio
async def test_unavailable_retained_without_price_and_not_counted_for_500(tmp_path):
    storage=LocalStorage(str(tmp_path))
    report=await run_store(STORE,CONFIG,storage,'offline-unavailable',browser_type=FakeBrowser)
    assert report['status']=='PASS'
    assert (report['total_unique'],report['priced_record_count'],report['unavailable_count'],report['unpriced_unavailable_count'])==(2,1,1,1)
    products=storage.load('runs/3891/offline-unavailable/products.json')
    assert products[1]['regular_price']==''
    sidecar=storage.load('runs/3891/offline-unavailable/product_source_evidence.json')
    assert len(sidecar['records'])==2
    assert sidecar['records'][1]['availability']=='UNAVAILABLE'
    assert sidecar['source_kind']=='custom_or_test'
    static=audit_dataset(products,[CAT],report,storage.load('runs/3891/offline-unavailable/evidence.json'),minimum=2,product_sources=sidecar)
    assert static['price_bearing_records']==1
    assert any('below_minimum_priced:1<2' in x for x in static['issues'])
    assert static['buyer_acceptance']=='NOT_CERTIFIED'


@pytest.mark.asyncio
async def test_all_unavailable_cannot_pass_even_if_minimum_count(tmp_path):
    class NoPrices(FakeBrowser):
        async def detail(self,url,expected_id):
            return product(expected_id,'OUT_OF_STOCK',''),Proof(url,STORE.id,'fixture','PICKUP','now')
    db=LocalStorage(str(tmp_path))
    report=await run_store(STORE,CONFIG,db,'all-unavail',browser_type=NoPrices)
    assert report['total_unique']==2 and report['priced_record_count']==0
    assert report['status']=='FAIL'
    assert any('below_minimum_priced_records' in x for x in report['reasons'])
    assert db.load('latest/3891.json') is None


def test_probe_quota_guard_bounds():
    for args in [(13,300,1,1),(5,601,1,1),(8,300,3,1),(8,300,1,5)]:
        with pytest.raises(ValueError):validate_probe_budget(*args)
    validate_probe_budget(8,300,2,3)


@pytest.mark.asyncio
async def test_custom_probe_never_certifies_live(tmp_path):
    report=await diagnostic_probe(STORE,CONFIG,str(tmp_path/'probe.json'),browser_type=FakeBrowser)
    assert report['status']=='PROBE_VERIFIED_NOT_ACCEPTANCE'
    assert report['price_bearing_verified']==1
    assert report['genuine_verified_product_count']==0
    assert report['buyer_acceptance']=='NOT_CERTIFIED'
    assert report['navigation_attempts']==3
    assert json.loads((tmp_path/'probe.json').read_text())['source_adapter']=='custom_or_test'


@pytest.mark.asyncio
async def test_failed_probe_always_writes_receipt(tmp_path):
    class WrongStore(FakeBrowser):
        async def select_store(self):
            raise RuntimeError('Selected wrong store')
    report=await diagnostic_probe(STORE,CONFIG,str(tmp_path/'failed-probe.json'),browser_type=WrongStore)
    assert report['status']=='FAIL_DIAGNOSTIC'
    assert report['price_bearing_verified']==0
    assert (tmp_path/'failed-probe.json').exists()


def test_price_proof_unchanged_on_missing_price():
    p=product('12345678902','OUT_OF_STOCK','')
    rec=make_record(p,STORE,CAT,'2026-10-25')
    assert rec['regular_price']==''
    assert validate_record(rec,strict=False)==[]
    assert 'missing_regular_price' in validate_record(rec,strict=True)


def test_container_build_context_has_only_public_store_profile():
    dockerfile=Path('Dockerfile').read_text()
    # Azure build cannot silently include a private CLI browser profile.
    assert 'stores.azure.yaml' in dockerfile
    assert 'COPY config/ /opt/scraper/config/' not in dockerfile

@pytest.mark.asyncio
async def test_http_request_budget_aborts_third_request():
    class Route:
        def __init__(self):self.allowed=False;self.aborted=False
        async def continue_(self):self.allowed=True
        async def abort(self,reason):self.aborted=True
    browser=WalmartBrowser(STORE,CONFIG.limits)
    browser.http_request_budget=2
    routes=[Route(), Route(), Route()]
    for route in routes: await browser._limit_http_request(route)
    assert browser.http_requests_seen==3
    assert [r.allowed for r in routes]==[True,True,False]
    assert routes[2].aborted and browser.http_budget_hit


def test_cloud_job_cannot_run_as_scheduled_by_this_script():
    script=Path('azure/deploy.sh').read_text()
    assert "AZ_AUTHORIZE_RESOURCE_CREATION" in script
    assert "AZ_QUOTE_ACCEPTED" in script
    assert "exit 6" in script
    assert "--replica-retry-limit 0" in script
    assert 'max-http-requests' in script


def test_cli_schema_validation_requires_source_sidecar_for_unavailable(tmp_path):
    from types import SimpleNamespace
    from walmart_azure.cli import _validate
    rec=make_record(product('12345678902','OUT_OF_STOCK',''),STORE,CAT,'2026-10-25')
    catalog=tmp_path/'products.json';catalog.write_text(json.dumps([rec]))
    sidecar=tmp_path/'sources.json';sidecar.write_text(json.dumps({'records':[{'product_id':'12345678902',
        'availability':'UNAVAILABLE','price_bearing':False,'url':rec['url'],
        'detail_proof':{'fulfillment':'PICKUP','store_id':'3891'}}]}))
    assert _validate(SimpleNamespace(catalog=str(catalog),product_sources=''))==2
    assert _validate(SimpleNamespace(catalog=str(catalog),product_sources=str(sidecar)))==0


def test_diagnostic_blocks_service_worker_requests_that_bypass_http_interception():
    source=Path('walmart_azure/browser.py').read_text()
    assert "service_workers='block' if self.http_request_budget is not None" in source
