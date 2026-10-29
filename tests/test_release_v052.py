"""Review #72 focused synthetic regressions. Never contacts Walmart, Azure or Oxylabs."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
import pytest

from walmart_azure import oxylabs_classic as classic
from walmart_azure.paid_budget import PaidBudget, BudgetError
from test_release_v051 import WAUKEGAN, PID, PRODUCT_URL, product, html_for, source_envelope
from test_release_v05 import MockResponse, MockSession


def evaluate(item):
    return classic._evaluate_source(html_for(item), WAUKEGAN, PRODUCT_URL)


def test_shipping_price_with_valid_pickup_option_is_not_pickup_price():
    item = product()
    item['priceInfo']['fulfillmentType'] = 'SHIPPING'
    evidence = evaluate(item)
    assert not evidence['price_verified']
    assert not evidence['price_context_binding_verified']
    assert not evidence['pickup_verified']
    assert not evidence['store_verified']
    assert 'SHIPPING' in evidence['source_parse_error']


@pytest.mark.parametrize('field', ('currentPrice', 'unitPrice', 'promotions'))
def test_nested_shipping_price_ppm_and_offer_never_qualify(field):
    item = product()
    if field == 'currentPrice':
        item['priceInfo']['currentPrice'] = {'price':'4.00','fulfillmentType':'SHIPPING'}
    elif field == 'unitPrice':
        item['priceInfo']['unitPrice'] = {'displayText':'$0.25/oz','fulfillmentType':'SHIPPING'}
    else:
        item['promotions'][0]['fulfillmentType'] = 'SHIPPING'
    evidence = evaluate(item)
    assert not evidence['price_verified']
    assert field in evidence['source_parse_error']


def test_mixed_fulfillment_untagged_money_is_ambiguous():
    item = product()
    item['fulfillmentOptions'].append({'type':'SHIPPING','status':'IN_STOCK'})
    evidence = evaluate(item)
    assert not evidence['price_verified'] and 'ambiguous' in evidence['source_parse_error']
    item['priceInfo']['fulfillmentType']='PICKUP'
    evidence = evaluate(item)
    assert not evidence['price_verified'] and 'promotions' in evidence['source_parse_error']
    item['promotions'][0]['fulfillmentType']='PICKUP'
    evidence = evaluate(item)
    assert evidence['price_verified'] and not evidence['buyer_acceptance']


def test_mixed_fulfillment_separate_unscoped_ppm_is_rejected():
    item = product()
    item['fulfillmentOptions'].append({'type':'SHIPPING','status':'IN_STOCK'})
    item['priceInfo']['fulfillmentType']='PICKUP'
    item['promotions'][0]['fulfillmentType']='PICKUP'
    item['unitPrice']='$0.55/oz'
    assert not evaluate(item)['price_verified']


def test_product_level_shipping_selection_rejects_local_pickup_prices():
    item=product()
    item['fulfillmentType']='SHIPPING'
    assert not evaluate(item)['price_verified']


def test_provider_payload_requires_raw_html_and_exact_original_product_url():
    assert classic.payloads(product_id=PID)==[]
    assert classic.payloads(url=PRODUCT_URL,product_id=PID)==[
        {'source':'walmart','url':PRODUCT_URL,'parse':False}]
    with pytest.raises(ValueError,match='match'):
        classic.payloads(url=PRODUCT_URL,product_id='9876543210')
    with pytest.raises(ValueError,match='product detail'):
        classic.payloads(url='https://www.walmart.com/cp/food/976759',product_id=PID)


def test_parsed_json_provider_result_cannot_prove_original_html(tmp_path,monkeypatch):
    monkeypatch.setenv('OXY_WSA_USERNAME','synthetic')
    monkeypatch.setenv('OXY_WSA_PASSWORD','synthetic')
    PaidBudget.register_authorization('TEST-PARSED-HTML-1',1)
    session=MockSession(MockResponse(source_envelope(product())))
    report=classic.run_probe(store=WAUKEGAN,product_id=PID,url=PRODUCT_URL,
        output=str(tmp_path/'parsed.json'),execute_billable=True,
        billing_approved=True,authorization_id='TEST-PARSED-HTML-1',
        session_factory=lambda:session)
    assert report['requests_sent']==1 and report['source_shape_verified_records']==0
    assert not report['results'][0]['source_evidence']['price_verified']


def test_same_approval_id_cannot_dispatch_twice_across_receipt_directories(tmp_path,monkeypatch):
    monkeypatch.setenv('OXY_WSA_USERNAME','synthetic')
    monkeypatch.setenv('OXY_WSA_PASSWORD','synthetic')
    authorization='CLIENT-SAME-APPROVAL-1'
    ledger=PaidBudget.register_authorization(authorization,1)
    s1=MockSession(MockResponse({'error':'provider failed'},503))
    first=classic.run_probe(store=WAUKEGAN,product_id=PID,url=PRODUCT_URL,
        output=str(tmp_path/'first'/'receipt.json'),execute_billable=True,
        billing_approved=True,authorization_id=authorization,session_factory=lambda:s1)
    s2=MockSession(MockResponse({'error':'should never dispatch'},503))
    second=classic.run_probe(store=WAUKEGAN,product_id=PID,url=PRODUCT_URL,
        output=str(tmp_path/'second'/'receipt.json'),execute_billable=True,
        billing_approved=True,authorization_id=authorization,session_factory=lambda:s2)
    assert first['requests_sent']==1
    assert second['requests_sent']==0 and not s2.calls
    assert second['status']=='BUDGET_RESERVATION_REFUSED_STOP'
    assert len(json.loads(ledger.read_text())['attempts'])==1


def test_missing_grant_after_enrollment_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setenv('OXY_WSA_USERNAME','synthetic')
    monkeypatch.setenv('OXY_WSA_PASSWORD','synthetic')
    authorization='CLIENT-MISSING-GRANT-1'
    grant=PaidBudget.register_authorization(authorization,1)
    grant.unlink()
    with pytest.raises(classic.OxylabsProbeError,match='ledger missing'):
        classic.run_probe(store=WAUKEGAN,product_id=PID,url=PRODUCT_URL,
            output=str(tmp_path/'another-directory'/'receipt.json'),execute_billable=True,
            billing_approved=True,authorization_id=authorization,
            session_factory=lambda:MockSession(MockResponse({},200)))
    assert not grant.exists()


def test_enrollment_not_automatic_and_cannot_reset(tmp_path,monkeypatch):
    auth='CLIENT-ENROLL-ONCE-1'
    PaidBudget.register_authorization(auth,1)
    with pytest.raises(BudgetError,match='already enrolled'):
        PaidBudget.register_authorization(auth,1)
    monkeypatch.delenv('WALMART_OXYLABS_LEDGER_ROOT')
    with pytest.raises(BudgetError,match='WALMART_OXYLABS_LEDGER_ROOT'):
        PaidBudget.register_authorization('CLIENT-UNSET-ROOT-1',1)


def test_overlap_two_mock_processes_at_most_one_dispatch(tmp_path,monkeypatch):
    monkeypatch.setenv('OXY_WSA_USERNAME','synthetic')
    monkeypatch.setenv('OXY_WSA_PASSWORD','synthetic')
    auth='CLIENT-OVERLAP-CAP-1'
    grant=PaidBudget.register_authorization(auth,1)
    sessions=[]
    class Slow(MockSession):
        def post(self,*args,**kw):
            self.calls.append((args,kw))
            sleep(.1)
            return self.response
    def invoke(index):
        session=Slow(MockResponse({'error':'provider failed'},503))
        sessions.append(session)
        try:
            return classic.run_probe(store=WAUKEGAN,product_id=PID,url=PRODUCT_URL,
                output=str(tmp_path/str(index)/'receipt.json'),execute_billable=True,
                billing_approved=True,authorization_id=auth,session_factory=lambda:session)
        except classic.OxylabsProbeError:
            return None  # Other invocation held O_EXCL lock
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports=list(pool.map(invoke,(1,2)))
    assert sum(len(s.calls) for s in sessions)==1
    assert len(json.loads(grant.read_text())['attempts'])==1
    assert sum(bool(r and r['requests_sent']==1) for r in reports)==1


@pytest.mark.asyncio
async def test_production_runner_rejects_shipping_specific_price_and_preserves_last_good(tmp_path):
    from walmart_azure.pipeline import run_store
    from walmart_azure.storage import LocalStorage
    from test_pipeline import STORE, CFG, FakeBrowser
    class OneShippingPrice(FakeBrowser):
        async def detail(self,url,expected_id):
            item,proof=await super().detail(url,expected_id)
            if expected_id=='1000000150':
                item['priceInfo']['fulfillmentType']='SHIPPING'
            return item,proof
    db=LocalStorage(str(tmp_path))
    previous=await run_store(STORE,CFG,db,'baseline',browser_type=FakeBrowser)
    assert previous['status']=='PASS'
    pointer=db.load('latest/100.json')
    rejected=await run_store(STORE,CFG,db,'shipping-price',browser_type=OneShippingPrice)
    assert rejected['status']=='FAIL'
    assert any('required_detail_failed' in r for r in rejected['reasons'])
    assert db.load('latest/100.json')==pointer
