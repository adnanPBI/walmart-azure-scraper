"""Local proof tests use fake DOM snapshots and synthetic hydration."""
import pytest
from walmart_azure.browser import page_proof, StoreMismatch
from walmart_azure.config import Store

STORE=Store('100','72712','Bentonville Supercenter','406 S Walton Blvd','Bentonville','AR')


class BrowserSnapshot:
    url='https://www.walmart.com/browse/food/milk'
    def __init__(self, rows):
        self.rows=rows
    async def evaluate(self, js):
        return self.rows


def hydration(selected):
    return {'props':{'pageProps':{'initialData':{'data':{'location':{'storeId':selected}}}}}}


@pytest.mark.asyncio
async def test_structured_id_and_pickup_pass():
    page=BrowserSnapshot([{'text':'Pickup from Bentonville Supercenter','active':True}])
    proof=await page_proof(page,STORE,hydration('100'))
    assert proof.store_id=='100' and proof.fulfillment=='PICKUP'
    assert 'hydration' in proof.source


@pytest.mark.asyncio
async def test_other_structured_store_fails_even_if_pickup_shown():
    page=BrowserSnapshot([{'text':'Pickup from Bentonville Supercenter','active':True}])
    with pytest.raises(StoreMismatch,match='switched'):
        await page_proof(page,STORE,hydration('200'))


@pytest.mark.asyncio
async def test_picker_option_address_does_not_qualify_as_selected_store():
    page=BrowserSnapshot([{'text':'406 S Walton Blvd, Bentonville','active':False},
                          {'text':'Pickup from Another City','active':True}])
    with pytest.raises(StoreMismatch,match='No explicit store'):
        await page_proof(page,STORE,{})


@pytest.mark.asyncio
async def test_absent_active_pickup_fails():
    page=BrowserSnapshot([{'text':'Store #100','active':True}, {'text':'Shipping','active':True}])
    with pytest.raises(StoreMismatch,match='PICKUP'):
        await page_proof(page,STORE,hydration('100'))
