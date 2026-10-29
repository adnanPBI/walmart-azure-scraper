"""Command line entry: no background workers, secrets or demo output are implicit."""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import os
from .config import load_config, load_categories
from .schema import FIELDS, validate_record
from .pipeline import run_store
from .storage import create_storage
from .acceptance import run_audit
from .discovery import discover_candidates
from .discovery_tree import discover_recursive
from .diagnostic import diagnostic_probe
from .oxylabs_classic import run_probe as oxylabs_classic_probe, review_saved_response, DEFAULT_URL
from .paid_budget import PaidBudget
from .classic_qualification import capabilities as classic_capabilities, qualify_saved_response as classic_qualify_saved_response


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                           'level':record.levelname, 'logger':record.name,
                           'message':record.getMessage()}, ensure_ascii=False)


def configure_logging():
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _add_configs(parser):
    parser.add_argument('--categories', default=os.getenv('CATEGORIES_CSV', 'config/categories.csv'))
    parser.add_argument('--stores', default=os.getenv('STORES_YAML', 'config/stores.yaml'))


def require_reviewed_manifest(categories, allow_parent_only_demo: bool = False) -> None:
    pending = sorted({c.name for c in categories if c.requires_subcategory_discovery})
    if pending and not allow_parent_only_demo:
        raise ValueError('Unreviewed parent categories require full subcategory discovery: '
                         + ', '.join(pending) + '. Use an expanded reviewed CSV. '
                         'For diagnostic trials only, supply --allow-parent-only-demo '
                         '(publication remains blocked).')


async def _run(args) -> int:
    cfg = load_config(args.categories, args.stores)
    require_reviewed_manifest(cfg.categories, getattr(args, "allow_parent_only_demo", False))
    stores = [s for s in cfg.stores if not args.store or s.id == args.store]
    if not stores:
        raise ValueError(f'Configured store not found: {args.store}')
    storage = create_storage(args.storage, args.output)
    all_ok = True
    for store in stores:
        try:
            result = await run_store(store, cfg, storage, args.run_id or datetime.now(timezone.utc).strftime('%Y%m%d'),
                                     headless=not args.headed)
        except Exception as exc:
            # One store must not prevent remaining stores from completing independent runs.
            all_ok = False
            logging.getLogger('walmart').exception('store_failed id=%s reason=%s', store.id, exc)
            continue
        all_ok = all_ok and result['status'] == 'PASS'
        logging.getLogger('walmart').info('run_result %s',json.dumps({
            'store':store.id, 'status':result['status'], 'unique':result['total_unique'],
            'reasons':result['reasons'], 'runtime':result['runtime_seconds']}))
    return 0 if all_ok else 2


async def _bootstrap(args) -> int:
    from playwright.async_api import async_playwright
    from .extract import parse_next_data
    from .browser import page_proof
    cfg = load_config(args.categories, args.stores)
    store = next((s for s in cfg.stores if s.id == args.store), None)
    if store is None:
        raise ValueError('Specify --store with a configured store number')
    if Path(args.output).exists() and not args.overwrite:
        raise ValueError('Bootstrap state already exists. Use --overwrite to replace intentionally')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(locale='en-US', viewport={'width':1440,'height':940})
        page = await context.new_page()
        await page.goto('https://www.walmart.com/', wait_until='domcontentloaded')
        print('In the opened browser, manually select the exact store and PICKUP. Return here when done.')
        input('Press Enter after verifying store and local PICKUP visually...')
        proof = await page_proof(page, store, parse_next_data(await page.content()))
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=args.output)
        os.chmod(args.output, 0o600)
        print('Verified browser state saved privately:', args.output)
        print('Proof:',json.dumps(proof.as_dict()))
        await browser.close()
    return 0


def _validate(args) -> int:
    data = json.loads(Path(args.catalog).read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('Catalog must be a JSON list')
    invalid = []
    source_map = {}
    if args.product_sources:
        from .report import record_identity
        source_data = json.loads(Path(args.product_sources).read_text(encoding='utf-8'))
        if not isinstance(source_data, dict) or not isinstance(source_data.get('records'), list):
            raise ValueError('Invalid product_source_evidence.json sidecar')
        source_map = {x.get('product_id'): x for x in source_data['records'] if isinstance(x, dict)}
    for i, record in enumerate(data):
        if not isinstance(record, dict):
            invalid.append([i, ['not_an_object']])
        else:
            if source_map:
                from .report import record_identity
                source = source_map.get(record_identity(record), {})
                explicit_unavailable = (source.get('availability') == 'UNAVAILABLE' and
                    source.get('price_bearing') is False and
                    source.get('detail_proof', {}).get('fulfillment') == 'PICKUP' and
                    source.get('url') == record.get('url'))
            else:
                explicit_unavailable = False
            issues = validate_record(record, strict=not explicit_unavailable)
            if issues:
                invalid.append([i, issues])
    summary = {'total':len(data),'valid':len(data)-len(invalid), 'invalid_count':len(invalid),
               'invalid_samples':invalid[:20],'fields_in_order':list(FIELDS)}
    print(json.dumps(summary, indent=2))
    return 0 if data and not invalid else 2


def main() -> None:
    parser = argparse.ArgumentParser(prog='walmart-crawl', description='Store-verified Azure Walmart scraper')
    parser.add_argument('--version', action='version', version='walmart-crawl 0.5.3')
    subs = parser.add_subparsers(dest='command', required=True)
    inspect = subs.add_parser('inspect-categories', help='Inspect the supplied Walmart CSV; no store, Azure or network access needed')
    inspect.add_argument('--categories', default=os.getenv('CATEGORIES_CSV', 'config/categories.csv'))
    run = subs.add_parser('run', help='Crawl configured store(s); data published ONLY on validation PASS')
    _add_configs(run)
    run.add_argument('--store', default='', help='Exact store number, or all configured stores')
    run.add_argument('--run-id', default='', help='Stable checkpoint ID; UTC date if omitted')
    run.add_argument('--storage', choices=['local', 'azure'], default='local')
    run.add_argument('--output', default='./output', help='Local staging root (for --storage local)')
    run.add_argument('--allow-parent-only-demo', action='store_true',
                     help='Diagnostic trial only; parent-only category output will NEVER pass publication')
    run.add_argument('--headed', action='store_true', help='Show Playwright browser on a desktop')
    check = subs.add_parser('preflight', help='Validate category/store configuration without any web requests')
    _add_configs(check)
    check.add_argument('--show-urls', action='store_true')
    validate = subs.add_parser('validate', help='Validate the exact 22-key JSON contract')
    validate.add_argument('--catalog', required=True)
    validate.add_argument('--product-sources', default='', help='Optional source sidecar required for explicit unpriced-unavailable records')
    discovery = subs.add_parser('discover-candidates', help='Parse saved category HTML into review-only candidate navigation links')
    discovery.add_argument('--html', required=True, help='Saved authorized Walmart parent category page HTML')
    discovery.add_argument('--category', required=True, help='Parent name exactly as in supplied CSV')
    discovery.add_argument('--categories', default=os.getenv('CATEGORIES_CSV', 'config/categories.csv'))
    discovery.add_argument('--output', default='', help='Write JSON report here, or stdout when omitted')
    tree = subs.add_parser('discover-tree', help='Recursively inventory category links; review-only, fails closed on blocked/partial scope')
    _add_configs(tree)
    tree.add_argument('--store', default='3891')
    tree.add_argument('--output', default='output/diagnostics/category-tree.json')
    tree.add_argument('--max-pages', type=int, default=100)
    tree.add_argument('--max-depth', type=int, default=7)
    tree.add_argument('--max-seconds', type=int, default=600)
    tree.add_argument('--max-http-requests', type=int, default=1500)
    tree.add_argument('--headed', action='store_true')
    tree.add_argument('--fixtures', default='', help='Offline URL-to-HTML fixture JSON, never counted as live access')
    audit = subs.add_parser('audit', help='Read-only acceptance evidence check; never certifies live collection')
    audit.add_argument('--catalog', required=True)
    audit.add_argument('--categories', default=os.getenv('CATEGORIES_CSV', 'config/categories.csv'))
    audit.add_argument('--report', default='')
    audit.add_argument('--evidence', default='')
    audit.add_argument('--product-sources', default='', help='Optional product_source_evidence.json for availability/price consistency')
    audit.add_argument('--minimum', type=int, default=500)
    probe = subs.add_parser('probe', help='Bounded Walmart store/pickup/price diagnostic only; never publishes data')
    _add_configs(probe)
    probe.add_argument('--store', default='3891', help='Configured store #; default Waukegan 3891')
    probe.add_argument('--output', default='output/diagnostics/waukegan-3891-probe.json')
    probe.add_argument('--max-requests', type=int, default=8)
    probe.add_argument('--max-http-requests', type=int, default=250,
                       help='Upper bound including browser assets and XHR; aborted above cap')
    probe.add_argument('--max-seconds', type=int, default=300)
    probe.add_argument('--max-categories', type=int, default=2)
    probe.add_argument('--max-details', type=int, default=3)
    probe.add_argument('--headed', action='store_true')
    probe.add_argument('--azure-receipt', action='store_true', help='Save sanitized probe receipt to private Azure Blob using managed identity')
    oxy = subs.add_parser('oxylabs-probe', help='Classic Web Scraper API: dry-run by default; paid only with two opt-ins')
    _add_configs(oxy)
    oxy.add_argument('--store', default='3891')
    oxy.add_argument('--url', default=DEFAULT_URL, help='Original Walmart /ip/ product URL required for raw HTML response; must match item ID')
    oxy.add_argument('--product-id', default='', help='Source-observed product ID; also requires its original --url')
    oxy.add_argument('--render-html', action='store_true', help='Optional JS rendering; increases cost')
    oxy.add_argument('--output', default='output/diagnostics/oxylabs-classic-review.json')
    oxy.add_argument('--max-requests', type=int, default=1)
    oxy.add_argument('--max-retries', type=int, default=0)
    oxy.add_argument('--max-seconds', type=int, default=90)
    oxy.add_argument('--max-body-bytes', type=int, default=2000000)
    oxy.add_argument('--execute-billable', action='store_true')
    oxy.add_argument('--billing-approved', action='store_true')
    oxy.add_argument('--authorization-id', default='', help='Client-approved paid budget ID; required only for billable execution')
    enroll = subs.add_parser('oxylabs-enroll-approval', help='Manually register a pre-approved request cap in ONE durable ledger root; zero network')
    enroll.add_argument('--authorization-id', required=True)
    enroll.add_argument('--max-requests', type=int, default=1)
    enroll.add_argument('--confirm-client-approval', action='store_true')
    caps = subs.add_parser('oxylabs-capabilities', help='Zero-cost Classic capabilities and exact PICKUP proof requirements')
    qual = subs.add_parser('oxylabs-qualify', help='Strict OFFLINE review of saved Classic raw-HTML product response')
    _add_configs(qual)
    qual.add_argument('--store', default='3891')
    qual.add_argument('--response', required=True, help='Saved provider response envelope, no network calls')
    qual.add_argument('--url', required=True, help='Source-observed Walmart /ip/ product URL')
    qual.add_argument('--product-id', required=True)
    qual.add_argument('--category', required=True, help='Operator label, not independent category coverage')
    qual.add_argument('--sub-category', default='')
    qual.add_argument('--expected-job-id', default='', help='Optional job ID comparison, not authentication')
    qual.add_argument('--output-dir', default='output/diagnostics/classic-strict-review')
    oxyreview = subs.add_parser('oxylabs-review', help='Review a saved Classic response with ZERO network/billing')
    _add_configs(oxyreview)
    oxyreview.add_argument('--store', default='3891')
    oxyreview.add_argument('--response', required=True, help='Full provider response JSON, may be private')
    oxyreview.add_argument('--output', default='output/diagnostics/oxylabs-offline-review.json')
    bootstrap = subs.add_parser('bootstrap', help='One-time authorized manual browser session initialization')
    _add_configs(bootstrap)
    bootstrap.add_argument('--store', required=True)
    bootstrap.add_argument('--output', required=True)
    bootstrap.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    configure_logging()
    try:
        if args.command == 'inspect-categories':
            categories = load_categories(args.categories)
            print(json.dumps({'parent_rows': len(categories),
                              'requiring_subcategory_discovery': sum(c.requires_subcategory_discovery for c in categories),
                              'category_rules': [{'category':c.name, 'url':c.url,
                                                  'exclusions':list(c.exclusions),
                                                  'requires_discovery':c.requires_subcategory_discovery}
                                                 for c in categories],
                              'discovery_accepted':False,
                              'warning':'All-subcategory coverage cannot be proven from the parent list alone.'},
                             indent=2, ensure_ascii=False))
            code = 0
        elif args.command == 'preflight':
            cfg = load_config(args.categories, args.stores)
            print(json.dumps({'stores':[s.id for s in cfg.stores], 'category_shards':len(cfg.categories),
                              'fingerprint':cfg.fingerprint,
                              'subcategory_discovery_pending':sorted({c.name for c in cfg.categories if c.requires_subcategory_discovery}),
                              'configuration_ready_for_live_full_run': not any(c.requires_subcategory_discovery for c in cfg.categories),
                              'buyer_acceptance': 'NOT_CERTIFIED',
                              'urls':[c.browse_url for c in cfg.categories] if args.show_urls else 'omitted'}, indent=2))
            code = 0
        elif args.command == 'run':
            code = asyncio.run(_run(args))
        elif args.command == 'validate':
            code = _validate(args)
        elif args.command == 'discover-candidates':
            cats = [c for c in load_categories(args.categories) if c.name == args.category]
            if not cats:
                raise ValueError('Specified category not found in source CSV')
            result = discover_candidates(Path(args.html).read_text(encoding='utf-8'),
                                         cats[0].name, cats[0].url, cats[0].exclusions)
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({'parent': result['parent'], 'candidate_count':len(result['candidates']),
                              'excluded_count':len(result['excluded']), 'status':result['status'],
                              'output': args.output or 'stdout', 'warnings':result['warnings']}, indent=2))
            if not args.output:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            code = 0
        elif args.command == 'probe':
            cfg = load_config(args.categories, args.stores)
            store = next((s for s in cfg.stores if s.id == args.store), None)
            if store is None:
                raise ValueError(f'Configured store #{args.store} not found')
            result = asyncio.run(diagnostic_probe(store, cfg, args.output,
                args.max_requests, args.max_seconds, args.max_categories, args.max_details,
                args.headed, max_http_requests=args.max_http_requests))
            if args.azure_receipt:
                # This is a single bounded receipt; never publishes the last-good pointer.
                storage = create_storage('azure', '')
                receipt_key = 'diagnostics/{store}/{time}/probe.json'.format(
                    store=store.id, time=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
                storage.write(receipt_key, {k:v for k,v in result.items() if k != 'report_file'})
                result['azure_receipt_key'] = receipt_key
            print(json.dumps({'status': result['status'], 'store': store.id,
                'source_adapter': result['source_adapter'],
                'navigation_attempts':result['navigation_attempts'],
                'browser_http_requests_seen':result['browser_http_requests_seen'],
                'price_bearing_verified':result['price_bearing_verified'],
                'errors':result['errors'], 'evidence_file':result['report_file'],
                'azure_receipt_key':result.get('azure_receipt_key','')},indent=2))
            code = 0 if result['status'] == 'PROBE_VERIFIED_NOT_ACCEPTANCE' else 2
        elif args.command == 'oxylabs-probe':
            cfg = load_config(args.categories,args.stores)
            store = next((s for s in cfg.stores if s.id == args.store),None)
            if not store:
                raise ValueError('Oxylabs diagnostic store not in configured stores')
            result = oxylabs_classic_probe(store=store,url=args.url,product_id=args.product_id,
                render=args.render_html,output=args.output,execute_billable=args.execute_billable,
                billing_approved=args.billing_approved,authorization_id=args.authorization_id,max_requests=args.max_requests,
                max_retries=args.max_retries,max_seconds=args.max_seconds,
                max_body_bytes=args.max_body_bytes)
            print(json.dumps({'status':result['status'],'network_requests_sent':result['requests_sent'],
                'buyer_acceptance':False, 'verified_products':result['genuine_products_verified'],
                'receipt':args.output},indent=2))
            code = 0 if not args.execute_billable else (0 if result['status']=='SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE' else 2)
        elif args.command == 'oxylabs-enroll-approval':
            if not args.confirm_client_approval:
                raise ValueError('No buyer authorization: --confirm-client-approval is required; no grant created')
            ledger = PaidBudget.register_authorization(args.authorization_id,args.max_requests)
            print(json.dumps({'status':'APPROVAL_ENROLLED_NO_NETWORK',
                              'ledger':str(ledger),'attempt_cap':args.max_requests,
                              'paid_requests_executed':0},indent=2))
            code=0
        elif args.command == 'oxylabs-capabilities':
            print(json.dumps(classic_capabilities(),indent=2))
            code=0
        elif args.command == 'oxylabs-qualify':
            cfg=load_config(args.categories,args.stores)
            store=next((x for x in cfg.stores if x.id==args.store),None)
            if store is None: raise ValueError('Configured store not found')
            category=Category(args.category,args.sub_category,
                              next((c.url for c in cfg.categories if c.name==args.category),
                                   'https://www.walmart.com/cp/food/976759'))
            result=classic_qualify_saved_response(
                response_file=args.response,output_dir=args.output_dir,store=store,
                observed_url=args.url,product_id_expected=args.product_id,
                category=category,expected_job_id=args.expected_job_id)
            print(json.dumps({'status':result['status'],'reasons':result['reasons'],
                              'original_html_sha256':result.get('original_html_sha256',''),
                              'output_dir':args.output_dir,'buyer_acceptance':False,
                              'genuine_products_verified':0,'network_requests':0},indent=2))
            code=0 if result['status'].startswith('STRICT_OFFLINE') else 2
        elif args.command == 'oxylabs-review':
            cfg=load_config(args.categories,args.stores)
            store=next((x for x in cfg.stores if x.id==args.store),None)
            if store is None: raise ValueError('Unknown store')
            result=review_saved_response(args.response,args.output,store)
            print(json.dumps({'status':result['status'],'buyer_acceptance':False,
                              'results':len(result['results']),'receipt':args.output},indent=2))
            code=0
        elif args.command == 'discover-tree':
            cfg=load_config(args.categories,args.stores)
            if args.fixtures:
                mapping=json.loads(Path(args.fixtures).read_text(encoding='utf-8'))
                async def fetch(url):
                    if url not in mapping:
                        raise FileNotFoundError('Fixture missing; cannot call discovery complete')
                    return Path(mapping[url]).read_text(encoding='utf-8')
                result=asyncio.run(discover_recursive(cfg.categories,fetch,
                    max_pages=args.max_pages,max_depth=args.max_depth,
                    max_seconds=args.max_seconds,receipt_path=args.output,
                    source='offline_fixture_not_live'))
            else:
                from .browser import WalmartBrowser, page_proof
                from .extract import parse_next_data
                async def run_live():
                    store=next((s for s in cfg.stores if s.id==args.store),None)
                    if store is None: raise ValueError('Store not configured')
                    instance=WalmartBrowser(store,cfg.limits,headless=not args.headed)
                    instance.http_request_budget=args.max_http_requests
                    instance.navigation_budget=args.max_pages+3
                    async with instance as b:
                        await b.select_store()
                        async def fetch(url):
                            html,status=await b.goto(url)
                            await page_proof(b.page,store,parse_next_data(html,status))
                            return html
                        return await discover_recursive(cfg.categories,fetch,
                            max_pages=args.max_pages,max_depth=args.max_depth,
                            max_seconds=args.max_seconds,receipt_path=args.output,
                            source='playwright_live_navigation_not_acceptance')
                result=asyncio.run(run_live())
            print(json.dumps({'status':result['status'],'pages_fetched':result['pages_fetched'],
                'candidate_links':len(result['candidate_edges']),'excluded':len(result['excluded']),
                'errors':result['failures'][:5],'review_required':True,
                'acceptance_coverage_certified':False,'receipt':args.output},indent=2))
            code=0 if result['status']=='REVIEW_REQUIRED' else 2
        elif args.command == 'audit':
            result = run_audit(args.catalog, args.categories, args.report, args.evidence, args.minimum, args.product_sources)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            code = 0 if result['status'] == 'PASS_STATIC_ONLY' else 2
        elif args.command == 'bootstrap':
            code = asyncio.run(_bootstrap(args))
        else:
            code = 2
        raise SystemExit(code)
    except KeyboardInterrupt:
        logging.getLogger('walmart').error('Interrupted: last good dataset untouched')
        raise SystemExit(130)
    except Exception as exc:
        logging.getLogger('walmart').exception('ERROR %s', str(exc))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
