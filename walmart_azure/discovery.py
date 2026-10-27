"""Conservative review-only subcategory link extraction from saved HTML.

This is a navigation discovery assistant, NOT proof that all retailer
subcategories have been found. The accepted crawl manifest must be independently
reviewed and include deeper levels, not only links on the landing page.
"""
from __future__ import annotations
from urllib.parse import urljoin, urlparse, urldefrag, parse_qsl, urlencode, urlunparse
from bs4 import BeautifulSoup
from .browser import is_allowed_retail_url
from .extract import check_blocked


def discover_candidates(html: str, parent_name: str, parent_url: str,
                        exclusions: tuple[str, ...] = ()) -> dict:
    check_blocked(html)
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('main'):
        return {'parent': parent_name, 'parent_url': parent_url, 'status': 'REVIEW_REQUIRED',
                'candidates': [], 'excluded': [],
                'warnings': ['main_landmark_missing; category links cannot be safely scoped']}
    items = {}
    excluded = []
    excl = {x.strip().casefold() for x in exclusions}
    for a in soup.select('main a[href]'):
        raw = a.get('href','').strip()
        absolute = urljoin(parent_url, raw)
        if not is_allowed_retail_url(absolute):
            continue
        parsed = urlparse(absolute)
        if not (parsed.path.startswith('/cp/') or parsed.path.startswith('/browse/')):
            continue
        # Strip campaign/referrer tracking without guessing a new product URL.
        # This is review-only navigation metadata, never a scraped product URL.
        path = urlunparse(parsed._replace(query=urlencode([(k,v) for k,v in parse_qsl(parsed.query) if k not in ('povid', 'adid')]), fragment=''))
        if path == parent_url or parsed.path == urlparse(parent_url).path:
            continue
        name = ' '.join((a.get_text(' ', strip=True) or a.get('aria-label','') or a.get('title','')).split())
        if not name:
            continue
        if name.casefold() in excl:
            excluded.append({'name': name, 'url': path})
            continue
        items.setdefault(path, {'parent': parent_name, 'candidate_subcategory': name, 'url': path,
                                'reviewed': False, 'source': 'main_link'})
    return {'parent': parent_name, 'parent_url': parent_url,
            'status': 'REVIEW_REQUIRED', 'candidates': list(items.values()),
            'excluded': excluded,
            'warnings': ['Navigation links are candidates only; verify that each belongs to this parent and recursively inspect deeper subcategories before declaring coverage.']}
