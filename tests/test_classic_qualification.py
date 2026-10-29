"""Client-facing Waukegan #3891 Classic qualification contracts; entirely synthetic.

These tests NEVER call Oxylabs, Walmart, or Azure. Positive fixture proves the
verifier's behavior, not the authenticity of any real external source response.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest

from walmart_azure.classic_qualification import (
    capabilities, qualify_envelope, qualify_saved_response,
)
from walmart_azure.config import Store, Category
from walmart_azure.schema import FIELDS

STORE=Store('3891','60085','Walmart #3891','3900 Fountain Square Pl','Waukegan','IL')
CATEGORY=Category('Food','Soft Drinks','https://www.walmart.com/cp/food/976759')
PID='1234567890'  # synthetic; never present as a genuine user-side Walmart product
URL=f'https://www.walmart.com/ip/SYNTHETIC-DO-NOT-SUBMIT/{PID}'


def product():
    return {'usItemId':PID, 'canonicalUrl':f'/ip/SYNTHETIC-DO-NOT-SUBMIT/{PID}',
            'name':'SYNTHETIC Soda 12 fl oz, 12 Pack', 'size':'12 fl oz',
            'brand':'Great Value','sellerName':'Walmart.com',
            'location':{'storeId':'3891'},
            'fulfillmentOptions':[{'type':'PICKUP','storeId':'3891','status':'IN_STOCK'}],
            'priceInfo':{'storeId':'3891','fulfillmentType':'PICKUP',
                         'currentPrice':{'price':'4.00'},
                         'unitPrice':'$0.25/fl oz'},
            'promotions':[{'type':'MULTIBUY','text':'2 for $5',
                           'requiresClipping':True,'terms':'Limit 1; Valid through 10/31',
                           'storeId':'3891','fulfillmentType':'PICKUP'}]}


def envelope(p=None,page_store='3891',page_mode='PICKUP',return_url=URL,status=200,html=True):
    p=product() if p is None else p
    nested={'props':{'pageProps':{'initialData':{
        'location':{'storeId':page_store,'fulfillmentType':page_mode},
        'product':p}}}}
    content='<!DOCTYPE html><html><script id="__NEXT_DATA__">'+json.dumps(nested)+'</script></html>'
    if not html:content={'product':p}
    row={'job_id':'SYNTHETIC_JOB_NOT_AUTHENTIC','status_code':status,'content':content}
    if return_url is not None:row['url']=return_url
    return {'results':[row]}


def qualify(payload=None):
    return qualify_envelope(payload if payload is not None else envelope(),store=STORE,
             observed_url=URL,product_id_expected=PID,category=CATEGORY)


def test_no_live_or_spending_capability_claim():
    c=capabilities()
    assert c['classic_exact_store_selector_verified'] is False
    assert c['geo_location_is_exact_store_selector'] is False
    assert c['no_paid_request_authorized'] is True
    assert c['documented_raw_html_request']['parse'] is False


def test_strict_synthetic_product_candidate_not_live():
    receipt,record,html=qualify()
    assert receipt['status']=='STRICT_OFFLINE_SOURCE_SHAPE_CANDIDATE_NOT_LIVE_AUTHENTICATED',receipt['reasons']
    assert receipt['source_pickup_availability']=='AVAILABLE'
    assert receipt['source_product_id']==PID
    assert receipt['selected_page_store_ids']==['3891']
    assert receipt['selected_page_fulfillment']==['PICKUP']
    assert receipt['selected_pickup_option_store_ids']==[['3891']]
    assert record and tuple(record)==FIELDS and record['regular_price']=='4.00'
    assert record['gupc']==record['unit_price']==''
    assert record['ppm']=='$0.25/fl oz'
    assert '12 Pack' in record['weight']
    assert 'Limit 1' in record['digital_deals_description']
    assert receipt['buyer_acceptance'] is False and receipt['verified_genuine_live_products']==0
    assert receipt['network_requests']==receipt['paid_requests']==0
    assert isinstance(html,str) and 'SYNTHETIC' in html


@pytest.mark.parametrize('mutation,reason',[
    ('page_shipping','does not explicitly select PICKUP'),
    ('page_other_store','not exclusively'),
    ('price_shipping','shipping'),
    ('price_other_store','monetary store'),
    ('ppm_shipping','shipping'),
    ('offer_shipping','shipping'),
    ('offer_no_scope','PICKUP monetary'),
    ('price_no_scope','PICKUP monetary'),
    ('price_no_store','store scope'),
    ('pickup_missing_store','PICKUP availability option'),
    ('pickup_wrong_store','PICKUP availability option'),
    ('seller_marketplace','first-party'),
    ('out_of_stock','not explicitly available'),
    ('id_wrong','mismatches'),
    ('price_missing','current local pickup price'),
])
def test_source_price_fulfillment_and_store_must_bind(mutation, reason):
    p=product(); kw={}
    if mutation=='page_shipping':kw['page_mode']='SHIPPING'
    if mutation=='page_other_store':kw['page_store']='100'
    if mutation=='price_shipping':p['priceInfo']['fulfillmentType']='SHIPPING'
    if mutation=='price_other_store':p['priceInfo']['storeId']='100'
    if mutation=='ppm_shipping':p['priceInfo']['unitPrice']={'displayText':'$0.25/fl oz','fulfillmentType':'SHIPPING'}
    if mutation=='offer_shipping':p['promotions'][0]['fulfillmentType']='SHIPPING'
    if mutation=='offer_no_scope':p['promotions'][0].pop('fulfillmentType')
    if mutation=='price_no_scope':p['priceInfo'].pop('fulfillmentType')
    if mutation=='price_no_store':p['priceInfo'].pop('storeId')
    if mutation=='pickup_missing_store':p['fulfillmentOptions'][0].pop('storeId')
    if mutation=='pickup_wrong_store':p['fulfillmentOptions'][0]['storeId']='100'
    if mutation=='seller_marketplace':p['sellerName']='Third Party Inc'
    if mutation=='out_of_stock':p['fulfillmentOptions'][0]['status']='OUT_OF_STOCK'
    if mutation=='id_wrong':p['usItemId']='9876543210'
    if mutation=='price_missing':p['priceInfo']['currentPrice']={}
    result,record,_=qualify(envelope(p,**kw))
    assert record is None and result['status']=='REJECTED_INSUFFICIENT_SOURCE_EVIDENCE'
    assert any(reason.casefold() in x.casefold() for x in result['reasons']),result['reasons']


@pytest.mark.parametrize('mutation', ['missing_url','wrong_returned_url','non_200','dict_content',
                                      'blocked_html','missing_job','missing_hydration'])
def test_actual_returned_source_and_retailer_content_are_required(mutation):
    e=envelope()
    row=e['results'][0]
    if mutation=='missing_url':row.pop('url')
    if mutation=='wrong_returned_url':row['url']='https://www.walmart.com/ip/other/9876543210'
    if mutation=='non_200':row['status_code']=403
    if mutation=='dict_content':row['content']={'product':product()}
    if mutation=='blocked_html':row['content']='<!DOCTYPE html><html>Robot or human</html>'
    if mutation=='missing_job':row.pop('job_id')
    if mutation=='missing_hydration':row['content']='<!DOCTYPE html><html><body>empty</body></html>'
    result,record,_=qualify(e)
    assert result['status']=='REJECTED_INSUFFICIENT_SOURCE_EVIDENCE'
    assert record is None and result['reasons']


def test_saved_offline_response_preserves_sanitized_html_and_never_publishes(tmp_path):
    response=tmp_path/'synthetic-provider.json'
    response.write_text(json.dumps(envelope()),encoding='utf-8')
    output=tmp_path/'review'
    result=qualify_saved_response(response_file=str(response),output_dir=str(output),
                    store=STORE,observed_url=URL,product_id_expected=PID,category=CATEGORY,
                    expected_job_id='SYNTHETIC_JOB_NOT_AUTHENTIC')
    assert result['status'].startswith('STRICT_OFFLINE')
    assert result['input_envelope_sha256']==hashlib.sha256(response.read_bytes()).hexdigest()
    assert (output/'qualification_receipt.json').is_file()
    assert (output/'sanitized_source.html').is_file()
    candidate=json.loads((output/'candidate_RECORD_NOT_LIVE_VERIFIED.json').read_text())
    assert len(candidate)==1 and tuple(candidate[0])==FIELDS
    assert result['live_origin_authenticated'] is False
    assert not (tmp_path/'latest').exists()
    with pytest.raises(FileExistsError):
        qualify_saved_response(response_file=str(response),output_dir=str(output),
                store=STORE,observed_url=URL,product_id_expected=PID,category=CATEGORY)


def test_untrusted_response_cannot_create_candidate(tmp_path):
    response=tmp_path/'bad.json'
    p=product(); p['priceInfo']['fulfillmentType']='SHIPPING'
    response.write_text(json.dumps(envelope(p)),encoding='utf-8')
    output=tmp_path/'rejected'
    result=qualify_saved_response(response_file=str(response),output_dir=str(output),
                     store=STORE,observed_url=URL,product_id_expected=PID,category=CATEGORY)
    assert result['status'].startswith('REJECTED')
    assert not (output/'candidate_RECORD_NOT_LIVE_VERIFIED.json').exists()
    assert (output/'sanitized_source.html').is_file()
    assert not (tmp_path/'latest').exists()
