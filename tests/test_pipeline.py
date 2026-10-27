"""Full pipeline tests use clearly SYNTHETIC in-memory browser responses, NOT Walmart records."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import pytest
from walmart_azure.config import Store, Category, Config, Limits, load_config, load_categories
from walmart_azure.browser import Proof, StoreMismatch, next_page_url, selected_location_from_data
from walmart_azure.storage import LocalStorage, ConcurrentRun
from walmart_azure.pipeline import run_store, page_key
from walmart_azure.schema import FIELDS

STORE = Store('100','72712','Bentonville Supercenter','406 S Walton Blvd','Bentonville','AR')
CATS = [Category('Food','Milk','https://www.walmart.com/browse/food/milk/976759_9176907'),
        Category('Home','Cleaning','https://www.walmart.com/browse/home/cleaning/1115193_1071966')]
CFG = Config([STORE], CATS, Limits(min_total_records=500, min_category_records=100,
                                     max_pages_per_category=4, page_retries=0,
                                     min_price_shard_yield_ratio=0.4))


class FakeBrowser:
    """Deterministic synthetic pages prove checkpoint/publish logic without pretending to crawl live Walmart."""
    fail_page = None
    wrong_store_on_id = None
    thin = False
    total_listing_calls = 0
    def __init__(self, store, limits, headless=True):
        self.store = store
        self.limits = limits
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    async def select_store(self):
        return Proof('https://www.walmart.com/', self.store.id, 'fixture', 'PICKUP', '2026-10-18T00:00Z')
    async def listing(self, url):
        cls = type(self)
        cls.total_listing_calls += 1
        page = int(parse_qs(urlparse(url).query).get('page', ['1'])[0])
        idx = 0 if '/milk/' in url else 1
        if cls.fail_page == (idx, page):
            raise RuntimeError('Synthetic interruption')
        count = 4 if cls.thin else 150
        start = idx * 300 + (page - 1) * 150 + 1000000000
        items = [{'usItemId':str(start+n), 'canonicalUrl':f'/ip/fake-item/{start+n}'} for n in range(count)]
        return '', {'max_page':2, 'reported_count': 300, 'proof': Proof(url,self.store.id,'fixture','PICKUP','now',f'synthetic-hash-{idx}-{page}').as_dict()}, items
    async def detail(self,url,expected_id):
        if type(self).wrong_store_on_id == expected_id:
            raise StoreMismatch('Synthetic store switched mid-run')
        price = '2.00' if int(expected_id) % 2 else '3.00'
        data = {'usItemId':expected_id, 'name':f'SYNTHETIC item {expected_id}, 12 oz',
                'canonicalUrl':url,'brand':'Great Value' if int(expected_id)%2 else 'National Brand',
                'upc':str(expected_id).zfill(12), 'sellerName':'Walmart.com',
                'location':{'storeIds':['100']},
                'imageInfo':{'thumbnailUrl':'https://i5.walmartimages.com/asr/synthetic.jpg'},
                'fulfillmentOptions':[{'type':'PICKUP','status':'IN_STOCK'}],
                'priceInfo':{'currentPrice':{'price':price}, 'unitPrice':{'displayText':'$0.20/oz'}}}
        if int(expected_id) % 11 == 0:
            data['promotions'] = [{'text':'2 for $5'}]
        if int(expected_id) % 13 == 0:
            data.setdefault('promotions', []).append({'text':'$1.99 each with Digital Coupon'})
        return data, Proof(url,self.store.id,'fixture-detail','PICKUP','now')


@pytest.fixture(autouse=True)
def reset_fake():
    FakeBrowser.fail_page = None
    FakeBrowser.wrong_store_on_id = None
    FakeBrowser.thin = False
    FakeBrowser.total_listing_calls = 0
    yield


@pytest.mark.asyncio
async def test_end_to_end_publish_600_distinct(tmp_path):
    store = LocalStorage(str(tmp_path))
    result = await run_store(STORE, CFG, store, 'fixture-run-1', browser_type=FakeBrowser)
    assert result['status']=='PASS' and result['total_unique']==600
    assert result['page_count']==4
    assert result['field_completeness']['gupc']['nonempty']==0
    assert result['field_completeness']['unit_price']['nonempty']==0
    assert result['examples']['ppm'] and result['examples']['volume_deal'] and result['examples']['digital_deal']
    assert FakeBrowser.total_listing_calls == 4
    pointer = store.load('latest/100.json')
    assert pointer['total_unique']==600
    catalog = store.load(pointer['products_key'])
    assert len(catalog)==600
    assert all(list(x)==list(FIELDS) for x in catalog)
    assert all(x['store_location']==STORE.location for x in catalog)
    assert all(x['gupc']=='' and x['unit_price']=='' for x in catalog)
    # Idempotent same run (no remote browse requests).
    again = await run_store(STORE, CFG, store, 'fixture-run-1', browser_type=FakeBrowser)
    assert again['total_unique'] == 600 and FakeBrowser.total_listing_calls == 4


@pytest.mark.asyncio
async def test_failure_does_not_clobber_previous_dataset(tmp_path):
    db=LocalStorage(str(tmp_path))
    first=await run_store(STORE, CFG, db, 'good', browser_type=FakeBrowser)
    assert first['status']=='PASS'
    old_pointer = db.load('latest/100.json')
    FakeBrowser.thin=True
    failed = await run_store(STORE, CFG, db, 'thin', browser_type=FakeBrowser)
    assert failed['status'] == 'FAIL'
    assert any('below_minimum' in x for x in failed['reasons'])
    assert db.load('latest/100.json') == old_pointer
    assert db.load('runs/100/thin/report.json')['status'] == 'FAIL'


@pytest.mark.asyncio
async def test_interruption_resume_page_checkpoints(tmp_path):
    db=LocalStorage(str(tmp_path))
    FakeBrowser.fail_page=(0,2)
    with pytest.raises(Exception, match='Synthetic interruption'):
        await run_store(STORE, CFG, db, 'interrupted', browser_type=FakeBrowser)
    assert db.load(page_key(STORE,'interrupted',CATS[0],1)) is not None
    assert db.load('latest/100.json') is None
    FakeBrowser.fail_page=None
    FakeBrowser.total_listing_calls=0
    result=await run_store(STORE, CFG, db, 'interrupted', browser_type=FakeBrowser)
    assert result['status']=='PASS'
    assert FakeBrowser.total_listing_calls == 3, 'only uncheckpointed pages refetched'


@pytest.mark.asyncio
async def test_store_mismatch_is_fatal_without_publish(tmp_path):
    db=LocalStorage(str(tmp_path))
    FakeBrowser.wrong_store_on_id='1000000002'
    with pytest.raises(StoreMismatch):
        await run_store(STORE, CFG, db, 'mismatch', browser_type=FakeBrowser)
    assert db.load('latest/100.json') is None
    failure=db.load('runs/100/mismatch/failure.json')
    assert failure['failure_type']=='StoreMismatch'


@pytest.mark.asyncio
async def test_cas_republishes_after_final_pointer_crash(tmp_path):
    db=LocalStorage(str(tmp_path))
    result=await run_store(STORE,CFG,db,'recovery',browser_type=FakeBrowser)
    assert result['status']=='PASS'
    pointer_path=tmp_path/'latest/100.json'
    pointer_path.unlink()
    FakeBrowser.total_listing_calls=0
    result=await run_store(STORE,CFG,db,'recovery',browser_type=FakeBrowser)
    assert result['status']=='PASS'
    assert FakeBrowser.total_listing_calls==0
    assert db.load('latest/100.json')['run_id']=='recovery'


def test_config_rows_and_shards(tmp_path):
    csv=tmp_path/'cats.csv'
    csv.write_text('Category;Sub Category;Sub Category URL;Min Price;Max Price\nFood;Milk;https://www.walmart.com/browse/food/milk;0;25\n')
    categories=load_categories(str(csv))
    assert len(categories)==1
    assert categories[0].browse_url.endswith('min_price=0&max_price=25')
    yaml=tmp_path/'stores.yaml'
    yaml.write_text('stores:\n  - id: "100"\n    zipcode: "72712"\n    name: Bentonville Supercenter\n    address: 406 S Walton Blvd\n    city: Bentonville\n    state: AR\n')
    config=load_config(str(csv),str(yaml))
    assert config.stores[0].id=='100' and config.categories[0].min_price=='0'


def test_bad_stores_rejected(tmp_path):
    csv=tmp_path/'categories.csv'
    csv.write_text('category,url\nFood,https://www.walmart.com/browse/food/976759\n')
    yaml=tmp_path/'stores.yaml'
    yaml.write_text('stores:\n - id: REPLACE\n   zipcode: "72712"\n   name: EXAMPLE\n   address: EXAMPLE\n   city: Bentonville\n   state: AR\n')
    with pytest.raises(ValueError):
        load_config(str(csv),str(yaml))


def test_store_id_proof_uses_only_location_field():
    hyd={'props':{'pageProps':{'initialData':{'data':{'product':{'location':{'storeIds':['100']}}}}}}}
    assert selected_location_from_data(hyd)==('100','hydration.location[0]')
    hyd={'props': {'pageProps': {'initialData': {'data': {'products': [{'storeIds': ['200']}]}}}}}
    assert selected_location_from_data(hyd)==('','')


def test_next_page_preserves_price_shards():
    out=next_page_url('https://www.walmart.com/browse/milk?min_price=0&max_price=10',2)
    assert 'max_price=10' in out and 'page=2' in out


def test_local_keys_cannot_escape_root(tmp_path):
    db=LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        db.write('../../etc/passwd',{})
    with pytest.raises(ValueError):
        db.write('/abs/path',{})
    db.write('test/data.json',{'a':1})
    with pytest.raises(ConcurrentRun):
        db.write('test/data.json',{'a':2})


@pytest.mark.asyncio
async def test_optional_listing_mode_requires_explicit_store_seller_pickup_and_price(tmp_path):
    class TrustedListingBrowser(FakeBrowser):
        detail_count=0
        async def listing(self, url):
            _, meta, items = await super().listing(url)
            for item in items:
                item.update(name=f'SYNTHETIC local grocery {item["usItemId"]}, 14 oz',
                    brand='Great Value',sellerName='Walmart.com',
                    location={'storeIds':['100']},
                    fulfillmentOptions=[{'type':'PICKUP','status':'IN_STOCK'}],
                    priceInfo={'currentPrice':{'price':'2.50'}})
            return '', meta, items
        async def detail(self, url, expected_id):
            type(self).detail_count+=1
            return await super().detail(url,expected_id)
    config=Config([STORE],CATS,replace(CFG.limits, detail_mode='missing_local_and_price'))
    result=await run_store(STORE,config,LocalStorage(str(tmp_path)),'listing-mode',browser_type=TrustedListingBrowser)
    assert result['status']=='PASS' and result['total_unique']==600
    assert result['detail_attempted']==0 and TrustedListingBrowser.detail_count==0


@pytest.mark.asyncio
async def test_duplicate_products_in_different_categories_count_once(tmp_path):
    class WithOverlap(FakeBrowser):
        async def listing(self, url):
            _, meta, items=await super().listing(url)
            if '/cleaning/' in url and 'page=2' not in url:
                for i in range(20):
                    pid=str(1000000000+i)
                    items[i]={'usItemId':pid,'canonicalUrl':f'/ip/fake-item/{pid}'}
            return '',meta,items
    result=await run_store(STORE,CFG,LocalStorage(str(tmp_path)),'duplicates',browser_type=WithOverlap)
    assert result['status']=='PASS'
    assert result['total_unique']==580
    assert result['duplicate_count']==20
    assert result['category_counts']['Food | Milk']==300
    assert result['category_counts']['Home | Cleaning']==300


@pytest.mark.asyncio
async def test_stale_old_pass_cannot_undo_newer_pass(tmp_path):
    db=LocalStorage(str(tmp_path))
    await run_store(STORE,CFG,db,'first',browser_type=FakeBrowser)
    await run_store(STORE,CFG,db,'second',browser_type=FakeBrowser)
    pointer=db.load('latest/100.json')
    assert pointer['run_id']=='second'
    with pytest.raises(Exception, match='newer good run'):
        await run_store(STORE,CFG,db,'first',browser_type=FakeBrowser)
    assert db.load('latest/100.json')==pointer
