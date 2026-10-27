from pathlib import Path
from datetime import date
import json
import pytest
from walmart_azure.config import Store, Category, load_categories
from walmart_azure.schema import (FIELDS, price_string, validate_record, approximate_weight, private_label)
from walmart_azure.extract import (parse_listing, parse_detail, BlockedResponse, ParseError,
    make_record, seller_is_walmart, local_pickup_offer, product_id, sponsored, parse_deals, find_ppm,
    get_weight, match_location)

F = Path(__file__).parent / 'fixtures'
STORE = Store('100','72712','Bentonville Supercenter','406 S Walton Blvd','Bentonville','AR')
CATEGORY = Category('Food','Milk','https://www.walmart.com/browse/food/milk/976759_9176907')


def test_field_contract():
    assert len(FIELDS) == 22 and FIELDS[-1] == 'crawl_date'
    assert FIELDS[18:22] == ('gupc','ppm','unit_price','crawl_date')


@pytest.mark.parametrize('raw,expected', [('$3.5','3.50'),(3,'3.00'),('2,350.15','2350.15'),
                                            ('Save $1',''),(-3,''),('$1.999',''),(None,''),
                                            ({'price':2.4},'2.40')])
def test_explicit_price(raw, expected):
    assert price_string(raw) == expected


def test_listing_reads_two_stacks_and_sponsored_flag():
    page = parse_listing((F/'category_live_shape.html').read_text())
    assert page.max_page == 1 and page.reported_count == 3
    assert len(page.products) == 3
    assert sum(sponsored(x) for x in page.products) == 1


def test_product_locality_prices_upc_and_empty_downstream_fields():
    product, _ = parse_detail((F/'product_live_shape.html').read_text())
    assert seller_is_walmart(product)
    assert local_pickup_offer(product)
    assert match_location(product, STORE)[0]
    record = make_record(product, STORE, CATEGORY, date.today().isoformat())
    assert not validate_record(record)
    assert list(record) == list(FIELDS)
    assert record['regular_price'] == '3.50' and record['sale_price'] == '3.12'
    assert record['ppm'] == '$0.02/fl oz'
    assert record['upc'] == '001234567890'
    assert record['gupc'] == '' and record['unit_price'] == ''
    assert record['store_brand'] == 'yes'
    assert record['volume_deals_description'] == '2 for $5'
    assert record['volume_deals_price'] == '5.00'
    assert record['digital_deals_description'] == 'Clip Coupon: Save $1'
    assert record['digital_deals_price'] == ''


def test_200_challenge_is_not_valid_data():
    with pytest.raises(BlockedResponse):
        parse_listing((F/'blocked_200.html').read_text(), 200)


def test_missing_ssr_fails_not_empty():
    with pytest.raises(ParseError):
        parse_listing('<html><body>empty site</body></html>')


def test_marketplace_and_shipping_only_rejected():
    item = {'sellerName':'Some third party', 'fulfillmentOptions':[{'type':'SHIPPING','status':'IN_STOCK'}]}
    assert not seller_is_walmart(item)
    assert not local_pickup_offer(item)
    assert not local_pickup_offer({'sellerName':'Walmart.com', 'fulfillmentOptions':[{'type':'PICKUP','status':'OUT_OF_STOCK'}]})
    assert not local_pickup_offer({'fulfillmentOptions':[{'type':'PICKUP','status':'UNKNOWN'}]})


def test_deals_never_invent_pricing():
    item={'promotions':[{'text':'Buy 1, Get 1 Free'},
                        {'text':'Save $5 when you buy 5'},
                        {'text':'$3.99 each with Digital Coupon'},
                        {'text':'Walmart Cash: Get $2'}]}
    got=parse_deals(item)
    assert 'Buy 1, Get 1 Free' in got['volume_deals_description']
    assert got['volume_deals_price'] == ''
    assert got['digital_deals_price'] == '3.99'
    assert 'Walmart Cash' not in str(got)


@pytest.mark.parametrize('size', ['approx 2 lb','Approximately 3 lb','about 1 kg', 'Random Weight 5 lb', 'variable wt 3lb'])
def test_approx_weight_exclusion(size):
    assert approximate_weight(size)


def test_explicit_ppm_only():
    assert find_ppm({'priceInfo':{'unitPrice':{'price':1.50, 'unit':'oz'}}}) == ''
    assert find_ppm({'priceInfo':{'unitPrice':'$0.18/fl oz'}}) == '$0.18/fl oz'
    assert get_weight({'name':'Great Value 14 oz'}) == '14 oz'


def test_own_brands():
    assert private_label('Great Value') == 'yes'
    assert private_label('National Brand') == 'no'


def test_retain_original_urls():
    p, _ = parse_detail((F/'product_live_shape.html').read_text())
    rec = make_record(p,STORE,CATEGORY,'2026-10-18')
    assert rec['url'].endswith('/ip/Great-Value-Milk/1111111111')
    assert rec['image_url'].endswith('/milk.jpg')


def test_weight_approximation_words_are_not_lost():
    # A normalizer may extract "1 lb" from a title saying "approx 1 lb".
    product = {'name':'Fresh chicken, approx 1 lb', 'usItemId':'11222334455'}
    assert approximate_weight(product['name'])

def test_external_product_url_is_not_followed():
    from walmart_azure.extract import product_url
    assert product_url({'usItemId':'12345678','canonicalUrl':'https://attacker.example/ip/12345678'}) == ''


def test_digital_metadata_type_without_invented_price():
    from walmart_azure.extract import parse_deals
    offer={'promotions':[{'type':'DIGITAL_COUPON','description':'Save $2 when you clip'}]}
    out=parse_deals(offer)
    assert out['digital_deals_description']=='Save $2 when you clip'
    assert out['digital_deals_price']==''
