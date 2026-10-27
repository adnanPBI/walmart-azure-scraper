"""Synthetic contract/regression tests for v0.4.0; not live Walmart evidence."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from walmart_azure.browser import WalmartBrowser, BrowserFailure, selected_location_from_data, StoreMismatch
from walmart_azure.config import Category, Store, Limits, load_categories
from walmart_azure.discovery_tree import discover_recursive, canonical_category_url
from walmart_azure.extract import parse_listing, parse_detail, ParseError

STORE=Store('3891','60085','Walmart Supercenter #3891','3900 Fountain Square Pl','Waukegan','IL')
FOOD=Category('Food','','https://www.walmart.com/cp/food/976759',
              exclusions=('Shop All Foods','Recipes'),requires_subcategory_discovery=True)


def h(body:dict)->str:
    return '<html><head></head><body><main></main><script id="__NEXT_DATA__" type="application/json">'+json.dumps(body)+'</script></body></html>'


def test_tempo_homepage_hydration_does_not_invent_product():
    data={'props':{'pageProps':{'initialTempoData':{'data':{'header':{'some':'thing'}}}}}}
    assert selected_location_from_data(data)==('','')
    with pytest.raises(ParseError,match='Missing searchResult'):
        parse_listing(h(data))


def test_tempo_category_parser_reads_explicit_searchresult():
    data={'props':{'pageProps':{'initialTempoData':{'data':{'searchResult':{
        'itemStacks':[{'items':[{'usItemId':'1234567890','canonicalUrl':'/ip/Test/1234567890'}]}],
        'aggregatedCount':1,'paginationV2':{'maxPage':1}}}}}}}
    listing=parse_listing(h(data))
    assert len(listing.products)==1 and listing.products[0]['usItemId']=='1234567890'


def test_tempo_detail_parser_reads_product():
    data={'props':{'pageProps':{'initialTempoData':{'data':{'product':{'usItemId':'1234567890','name':'Synthetic Milk'}}}}}}
    p,_=parse_detail(h(data))
    assert p['name']=='Synthetic Milk'


def test_tempo_store_location_explicit_only():
    data={'props':{'pageProps':{'initialTempoData':{'data':{'location':{'storeIds':['3891']}}}}}}
    assert selected_location_from_data(data)[0]=='3891'
    data['props']['pageProps']['initialTempoData']['data']['location']['storeIds']=['100']
    assert selected_location_from_data(data)[0]=='100'


def test_blocked_redirect_with_200_is_not_accepted():
    class DummyPage:
        url='https://www.walmart.com/blocked?url=L2Nw'
        async def goto(self,*a,**kw):return type('Response',(),{'status':200})()
    async def go():
        b=WalmartBrowser(STORE,Limits())
        b.page=DummyPage()
        b.pace=AsyncMock()
        with pytest.raises(Exception,match='access-restriction'):
            await b.goto('https://www.walmart.com/cp/food/976759')
    asyncio.run(go())


def html_links(items):
    return '<html><main>'+''.join(f'<a href="{u}">{label}</a>' for label,u in items)+'</main></html>'


def test_recursive_discovery_propagates_exclusions_and_records_depth(tmp_path):
    root='https://www.walmart.com/cp/food/976759'
    milk='https://www.walmart.com/cp/milk/555'
    yogurt='https://www.walmart.com/cp/yogurt/666'
    excluded='https://www.walmart.com/cp/recipes/777'
    pages={root:html_links([('Milk',milk),('Recipes',excluded)]),
           milk:html_links([('Yogurt',yogurt),('Food',root)]),
           yogurt:html_links([('Recipes',excluded)])}
    async def fetch(url):return pages[url]
    receipt=tmp_path/'tree.json'
    r=asyncio.run(discover_recursive([FOOD],fetch,max_pages=10,receipt_path=str(receipt)))
    assert r['status']=='REVIEW_REQUIRED'
    assert r['pages_fetched']==3
    assert len(r['excluded'])==2
    assert r['review_required'] and not r['acceptance_coverage_certified']
    assert not any(n['url']==excluded for n in r['visited'])
    assert max(n['depth'] for n in r['visited'])==2
    assert json.loads(receipt.read_text())['pages_fetched']==3


def test_recursive_discovery_budget_fails_closed():
    root=FOOD.url
    next_url='https://www.walmart.com/cp/milk/555'
    async def fetch(url):return html_links([('Milk',next_url)])
    r=asyncio.run(discover_recursive([FOOD],fetch,max_pages=1))
    assert r['status']=='INCOMPLETE'
    assert r['failures'][0]['type']=='PAGE_BUDGET'
    assert r['pending']


def test_recursive_discovery_blocked_page_is_not_empty():
    async def fetch(url):raise RuntimeError('Retailer redirect /blocked')
    r=asyncio.run(discover_recursive([FOOD],fetch,max_pages=5))
    assert r['status']=='INCOMPLETE' and r['pages_fetched']==0
    assert r['failures'] and not r['acceptance_coverage_certified']


def test_recursive_discovery_main_absent_is_unverified():
    async def fetch(url):return '<html><a href="/cp/milk/555">Milk</a></html>'
    r=asyncio.run(discover_recursive([FOOD],fetch))
    assert r['status']=='INCOMPLETE' and r['failures']


def test_category_url_canonicalization_no_cross_site():
    assert canonical_category_url('https://www.walmart.com/cp/food/976759?povid=abc') == FOOD.url
    with pytest.raises(ValueError):canonical_category_url('https://evil.example/cp/food/976759')
    with pytest.raises(ValueError):canonical_category_url('https://www.walmart.com/ip/test/999999')


def test_all_client_categories_have_no_wrong_retailer_or_unreadable_exclusion():
    cats=load_categories('config/categories.csv')
    assert len(cats)==11
    ex={c.name:c.exclusions for c in cats}
    assert ex['Food']==('Shop All Foods','Recipes')
    assert ex['Pets']==('Farm Animals',)
    assert all(c.requires_subcategory_discovery for c in cats)
