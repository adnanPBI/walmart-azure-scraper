"""Actual client CSV + validation gate regression, all offline."""
from pathlib import Path
import hashlib
import json
import pytest
from walmart_azure.config import load_categories, Category
from walmart_azure.discovery import discover_candidates
from walmart_azure.acceptance import audit_dataset
from walmart_azure.report import build_report
from walmart_azure.config import Config, Store, Limits
from walmart_azure.schema import FIELDS

BASE = Path(__file__).resolve().parents[1]
STORE = Store('100', '72712', 'Bentonville Supercenter', '406 S Walton Blvd', 'Bentonville', 'AR')


def test_real_client_csv_import_and_exclusions():
    categories = load_categories(str(BASE/'config/categories.csv'))
    assert len(categories) == 11
    assert all(c.requires_subcategory_discovery for c in categories)
    assert categories[0].exclusions == ('Shop All Foods', 'Recipes')
    assert next(c.exclusions for c in categories if c.name == 'Pets') == ('Farm Animals',)


def test_wrong_retailer_rejected(tmp_path):
    p = tmp_path/'cats.csv'
    p.write_text('Retailer,Category (Auto),URL\nMarianos,Food,https://www.walmart.com/cp/food/976759\n')
    with pytest.raises(ValueError, match='not Walmart'):
        load_categories(str(p))


def test_excluded_subcategory_rejected(tmp_path):
    p=tmp_path/'cats.csv'
    p.write_text('Category (Auto),SubCategory,URL,Scope,Notes\n'
                 'Pets,,https://www.walmart.com/cp/pets/5440,Category + ALL subcategories,Exclude \'Farm Animals\' subcategory\n'
                 'Pets,Farm Animals,https://www.walmart.com/cp/farm-animals/123,,\n')
    with pytest.raises(ValueError, match='Forbidden subcategory'):
        load_categories(str(p))


def test_parent_only_run_must_never_report_pass():
    cfg = Config([STORE], load_categories(str(BASE/'config/categories.csv')),
                 Limits(min_total_records=0, min_category_records=0))
    _, report = build_report(STORE, cfg, [], None, 1.0, 'parent-only')
    assert report['status'] == 'FAIL'
    assert any(x.startswith('subcategory_discovery_unverified:') for x in report['reasons'])


def test_navigation_parser_filters_excluded_and_unsafe_links():
    html = '''<html><body><main>
      <a href="/browse/food/976759_123">Milk</a>
      <a href="/cp/recipes/999">Recipes</a>
      <a href="/browse/food/976759_124">Shop All Foods</a>
      <a href="https://evil.example/browse/food">Evil</a>
      <a href="/ip/Milk/123456789">Product</a>
      <a href="/browse/food/976759_123">Milk</a>
    </main><footer><a href="/cp/office/123">Office</a></footer></body></html>'''
    result = discover_candidates(html, 'Food', 'https://www.walmart.com/cp/food/976759', ('Shop All Foods', 'Recipes'))
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['candidate_subcategory'] == 'Milk'
    assert len(result['excluded']) == 2
    assert result['status'] == 'REVIEW_REQUIRED'


def test_navigation_parser_fails_safe_without_main():
    result = discover_candidates('<a href="/cp/bread/123">Bread</a>', 'Food', 'https://www.walmart.com/cp/food/976759')
    assert result['candidates'] == [] and result['warnings']


def test_audit_synthetic_label_never_yields_buyer_acceptance():
    categories = [Category('Food','Milk','https://www.walmart.com/browse/food/milk')]
    rec = dict.fromkeys(FIELDS, '')
    rec.update({'zipcode':'72712','store_name':'Bentonville Supercenter',
        'store_location':STORE.location,'category':'Food','sub_category':'Milk',
        'product_title':'SYNTHETIC Milk 1 gal','regular_price':'2.00',
        'url':'https://www.walmart.com/ip/SYNTHETIC/1234567890','crawl_date':'2026-10-24'})
    payload = [rec]
    h = hashlib.sha256(json.dumps(payload,ensure_ascii=False,indent=2).encode()).hexdigest()
    report = {'status':'PASS','total_unique':1,'store_id':'100','zipcode':'72712','run_id':'mock',
              'source_page_hashes':[{'sha256':'abc'}],
              'category_counts':{'Food | Milk':1},
              'store_proofs':[{'store_id':'100','fulfillment':'PICKUP'}]}
    evidence = {'product_json_sha256':h,'run_id':'mock','store':'100',
                'synthetic':True,'runtime_adapter':'custom_or_test'}
    result=audit_dataset(payload,categories,report,evidence,minimum=1)
    assert result['status']=='FAIL_STATIC'
    assert 'synthetic_or_custom_adapter_not_live_evidence' in result['issues']
    assert result['buyer_acceptance']=='NOT_CERTIFIED'


def test_audit_valid_static_still_does_not_certify_live():
    categories = [Category('Food','Milk','https://www.walmart.com/browse/food/milk')]
    rec = dict.fromkeys(FIELDS, '')
    rec.update({'zipcode':'72712','store_name':'Bentonville Supercenter',
        'store_location':STORE.location,'category':'Food','sub_category':'Milk',
        'product_title':'Test 12 oz','regular_price':'2.00',
        'url':'https://www.walmart.com/ip/Test/1234567890','crawl_date':'2026-10-24'})
    payload=[rec]
    h=hashlib.sha256(json.dumps(payload,ensure_ascii=False,indent=2).encode()).hexdigest()
    report={'status':'PASS','total_unique':1,'store_id':'100','zipcode':'72712','run_id':'r',
            'source_page_hashes':[{'sha256':'abc'}], 'category_counts':{'Food | Milk':1},
            'store_proofs':[{'store_id':'100','fulfillment':'PICKUP'}]}
    evidence={'product_json_sha256':h,'run_id':'r','store':'100',
              'synthetic':False,'runtime_adapter':'playwright_live','acceptance_verified':False}
    result=audit_dataset(payload,categories,report,evidence,minimum=1)
    assert result['status']=='PASS_STATIC_ONLY'
    assert result['buyer_acceptance']=='NOT_CERTIFIED'


def test_audit_flags_missing_and_excluded_product():
    categories=load_categories(str(BASE/'config/categories.csv'))
    rec=dict.fromkeys(FIELDS,'')
    rec.update({'category':'Pets','sub_category':'Farm Animals', 'product_title':'Test pet feed',
                'url':'https://www.walmart.com/ip/1234567890', 'regular_price':'1.00',
                'crawl_date':'2026-10-24'})
    result=audit_dataset([rec],categories,minimum=500)
    assert any(x.startswith('excluded_subcategories_found:') for x in result['issues'])
    assert any(x.startswith('missing_parent_categories:') for x in result['issues'])


def test_parent_only_default_run_is_blocked_before_browser():
    from walmart_azure.cli import require_reviewed_manifest
    cats = load_categories(str(BASE/'config/categories.csv'))
    with pytest.raises(ValueError, match='full subcategory discovery'):
        require_reviewed_manifest(cats)
    # Explicit diagnostic demo still cannot cause publication PASS because report gate rejects it.
    require_reviewed_manifest(cats, allow_parent_only_demo=True)
