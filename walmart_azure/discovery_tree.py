"""Fail-closed recursive category-navigation inventory, not acceptance certification.

A candidate category link may be unrelated navigation; the resulting graph
requires independent scope review. A blocked or missing page never counts as
an empty child and any resource/depth limit leaves the inventory incomplete.
"""
from __future__ import annotations
import asyncio
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Awaitable, Callable
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from .config import Category
from .discovery import discover_candidates
from .browser import is_allowed_retail_url


def canonical_category_url(url: str) -> str:
    if not is_allowed_retail_url(url):
        raise ValueError('Non-Walmart or insecure URL in discovered category')
    parsed = urlparse(url)
    if not parsed.path.startswith(('/cp/', '/browse/')):
        raise ValueError('Not a category/browse URL')
    # Remove marketing attribution only; never transform a product ID.
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() not in {'povid', 'adid', 'athbdg', 'athcpid'}]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=''))


def _save_receipt(path: str | None, result: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(target)


async def discover_recursive(categories: list[Category],
                             fetch: Callable[[str], Awaitable[str]], *,
                             max_pages: int = 100, max_depth: int = 7,
                             max_seconds: int = 600, receipt_path: str | None = None,
                             source: str = 'unverified') -> dict:
    """Breadth-first discovery, closed on errors, cycles, missing landmarks and budgets.

    Browsing all *candidate* links still cannot prove all subcategories exist;
    a human must review scoping, deepest links and independently confirm coverage.
    """
    if not 1 <= max_pages <= 10000 or not 0 <= max_depth <= 30 or not 1 <= max_seconds <= 7200:
        raise ValueError('Invalid discovery safety budget')
    result = {'version':'0.5.0', 'status':'INCOMPLETE', 'review_required':True,
              'live_product_data':False, 'source':source,
              'started_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'roots':[{'category':c.name, 'url':c.url, 'exclusions':list(c.exclusions)} for c in categories],
              'max_pages':max_pages, 'max_depth':max_depth, 'max_seconds':max_seconds,
              'visited':[], 'candidate_edges':[], 'excluded':[], 'failures':[],
              'pending':[], 'pages_fetched':0}
    queue = deque()
    for cat in categories:
        queue.append((cat.name, cat.url, cat.exclusions, 0, '', cat.name))
    visited = set()
    started=time.monotonic()
    while queue:
        if time.monotonic()-started > max_seconds:
            result['failures'].append({'type':'TIME_BUDGET', 'message':'Discovery deadline reached; not complete'})
            break
        if result['pages_fetched'] >= max_pages:
            result['failures'].append({'type':'PAGE_BUDGET', 'message':'Discovery page limit reached; not complete'})
            break
        parent_name, url, exclusions, depth, ancestor_url, label = queue.popleft()
        try:
            canonical = canonical_category_url(url)
        except ValueError as exc:
            result['failures'].append({'url':url, 'type':'UNSAFE_URL', 'message':str(exc)})
            break
        if (parent_name, canonical) in visited:
            continue
        if depth > max_depth:
            result['failures'].append({'url':canonical,'type':'DEPTH_BUDGET', 'message':'Unexplored descendants; not complete'})
            break
        visited.add((parent_name, canonical))
        try:
            html = await asyncio.wait_for(fetch(url), timeout=max(1, max_seconds-int(time.monotonic()-started)))
            parsed = discover_candidates(html, parent_name, canonical, exclusions)
            if not isinstance(html, str) or not html.strip() or any('landmark_missing' in x for x in parsed['warnings']):
                raise ValueError('Category main landmark missing; cannot inventory child links')
        except Exception as exc:
            result['failures'].append({'url':canonical,'type':type(exc).__name__, 'message':str(exc)[:250]})
            break
        result['pages_fetched']+=1
        result['visited'].append({'category':parent_name,'display_name':label,'url':canonical,
                                  'parent_url':ancestor_url,'depth':depth,
                                  'html_sha256':hashlib.sha256(html.encode('utf-8')).hexdigest(),
                                  'potential_child_count':len(parsed['candidates']),
                                  'reviewed':False, 'children_exhaustive_verified':False})
        for item in parsed['excluded']:
            result['excluded'].append({'root_category':parent_name,'parent_url':canonical,
                                       'name':item['name'],'url':item['url'],
                                       'descendants_suppressed':True})
        for item in parsed['candidates']:
            new_url=item['url']
            try:
                ck=canonical_category_url(new_url)
            except ValueError:
                result['failures'].append({'url':new_url, 'type':'UNSAFE_CHILD', 'message':'Invalid discovered link'})
                continue
            result['candidate_edges'].append({'root_category':parent_name, 'from_url':canonical,
                                              'to_url':ck,'text':item['candidate_subcategory'],
                                              'relationship_reviewed':False})
            if (parent_name, ck) not in visited:
                queue.append((parent_name, new_url, exclusions, depth+1, canonical,
                              item['candidate_subcategory']))
        result['pending']=[{'category':a, 'url':b, 'depth':d} for a,b,_,d,_,_ in queue]
        _save_receipt(receipt_path, result)
    result['pending']=[{'category':a, 'url':b, 'depth':d} for a,b,_,d,_,_ in queue]
    result['graph_traversed_without_known_fetch_errors'] = not result['failures'] and not queue
    result['status']='REVIEW_REQUIRED' if result['graph_traversed_without_known_fetch_errors'] else 'INCOMPLETE'
    result['finished_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
    result['duration_seconds']=round(time.monotonic()-started,2)
    result['acceptance_coverage_certified']=False  # human/source verification is separate
    _save_receipt(receipt_path, result)
    return result
