"""Offline REAL Playwright Chromium integration with intercepted synthetic HTML.

This never contacts walmart.com and MUST NOT be used as live contest evidence.
"""
from __future__ import annotations
import json
import shutil
from urllib.parse import urlparse
import pytest
from playwright.async_api import async_playwright
from walmart_azure.browser import WalmartBrowser
from walmart_azure.config import Config, Category, Limits, Store
from walmart_azure.storage import LocalStorage
from walmart_azure.pipeline import run_store

ST = Store('100','72712','Bentonville Supercenter','406 S Walton Blvd','Bentonville','AR')
CATEGORIES=[Category('Food','Milk','https://www.walmart.com/browse/food/milk'),
            Category('Home','Cleaning','https://www.walmart.com/browse/home/cleaning')]
CFG=Config([ST], CATEGORIES,Limits(min_total_records=4, min_category_records=2,max_scroll_rounds=5))


def html(next_data, cards=''):
    return ('<!doctype html><html><head><title>OFFLINE SYNTHETIC</title></head><body>'
        '<button aria-pressed="true">Pickup from Bentonville Supercenter</button>'
        '<script id="__NEXT_DATA__" type="application/json">'
        +json.dumps({'props':{'pageProps':{'initialData':next_data}}})+'</script>'+cards+'</body></html>')


class RoutedMockBrowser(WalmartBrowser):
    async def __aenter__(self):
        self._pw=await async_playwright().start()
        self.browser=await self._pw.chromium.launch(headless=True, executable_path=shutil.which('chromium'),args=['--no-sandbox'])
        self.context=await self.browser.new_context(locale='en-US',viewport={'width':1440,'height':940})
        self.page=await self.context.new_page()
        self.page.set_default_timeout(3000)
        self.delay_min=0
        self.delay_max=0
        return self

    async def goto(self, url):
        # Unprivileged fixture navigation: no Walmart request or remote route occurs.
        path=urlparse(url).path
        body=''
        if path=='/':
            body=html({'data':{'location':{'storeId':'100'}}})
        elif path.startswith('/browse/'):
            first='milk' in path
            ids=[str(i) for i in (123450001,123450002,123450003) if first] + [str(i) for i in (123460001,123460002,123460003) if not first]
            items=[{'usItemId':x,'canonicalUrl':'/ip/SYNTHETIC/'+x,'name':'SYNTHETIC SKU '+x} for x in ids]
            cards=''.join(f'<div data-item-id="{x}"><a href="/ip/SYNTHETIC/{x}">{x}</a></div>' for x in ids)
            body=html({'location':{'storeId':'100'},'searchResult':{'aggregatedCount':len(items),
                 'paginationV2':{'maxPage':1},'itemStacks':[{'items':items}]}},cards)
        elif path.startswith('/ip/'):
            item_id=path.rsplit('/',1)[-1]
            product={'usItemId':item_id,'canonicalUrl':path,'name':'SYNTHETIC Milk 12 oz',
                'sellerName':'Walmart.com','upc':item_id.zfill(12),
                'location':{'storeIds':['100']},
                'fulfillmentOptions':[{'type':'PICKUP','status':'IN_STOCK'}],
                'priceInfo':{'currentPrice':{'price':2.47},'unitPrice':{'displayText':'$0.20/oz'}},
                'promotions':[{'text':'2 for $5'}]}
            body=html({'data':{'product':product}})
        else:
            raise ValueError('Unknown synthetic fixture URL '+url)
        await self.page.set_content(body, wait_until='domcontentloaded')
        self.requests += 1
        result = await self.page.content()
        return result, 200


@pytest.mark.skipif(not shutil.which('chromium'), reason='System Chromium absent; fixture test needs browser')
@pytest.mark.asyncio
async def test_full_real_playwright_workflow_over_offline_fixture(tmp_path):
    output=LocalStorage(str(tmp_path))
    report=await run_store(ST,CFG,output,'browser-fixture',browser_type=RoutedMockBrowser)
    assert report['status']=='PASS' and report['total_unique']==6
    assert report['page_count']==2
    assert report['field_completeness']['ppm']['nonempty']==6
    assert output.load('latest/100.json')['total_unique']==6
