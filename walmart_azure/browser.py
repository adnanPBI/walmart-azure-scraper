"""Playwright browser session: explicitly choose, repeatedly verify and fail closed on wrong store.

This module DOES NOT solve captchas, impersonate users, forge cookies, or replay
undocumented Walmart API requests. Respect the site's terms and authorized access.
"""
from __future__ import annotations
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import random
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from playwright.async_api import async_playwright, Page, BrowserContext, Browser
from .config import Store, Limits
from .extract import parse_next_data, parse_listing, parse_detail, ParseError, BlockedResponse, match_location, nested, product_id, product_url, hydration_roots


class StoreMismatch(RuntimeError):
    pass


class BrowserFailure(RuntimeError):
    pass


def is_allowed_retail_url(url: str) -> bool:
    """Disallow any cross-site redirect before interpreting price or store evidence."""
    try:
        parsed = urlparse(url)
        return (parsed.scheme == 'https' and
                (parsed.hostname or '').lower() in ('walmart.com', 'www.walmart.com'))
    except ValueError:
        return False


@dataclass
class Proof:
    url: str
    store_id: str
    source: str
    fulfillment: str
    timestamp: str
    hash: str = ''

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def selected_location_from_data(data: dict) -> tuple[str, str]:
    """Only structured *active location* candidates; never search arbitrary marketing data."""
    options = []
    for root in hydration_roots(data):
        options.extend((
            nested(root, 'data', 'product', 'location'), nested(root, 'data', 'location'),
            root.get('location'), nested(root, 'data', 'customerLocation'),
            nested(root, 'data', 'pickupStore'), root.get('pickupStore'),
            nested(root, 'data', 'storeInfo'), nested(root, 'data', 'selectedStore'),
        ))
    for pos, loc in enumerate(options):
        if not isinstance(loc, dict):
            continue
        ids = loc.get('storeIds') or loc.get('storeId') or loc.get('pickupStoreId')
        if isinstance(ids, list):
            ids = ids[0] if len(ids) == 1 else ''
        if ids is not None and str(ids).isdigit():
            return str(ids), f'hydration.location[{pos}]'
    return '', ''


async def page_proof(page: Page, store: Store, hydration: dict, require_pickup: bool = True) -> Proof:
    """Prove selected store via SSR *and* the page's fulfillment UI.

    If Walmart changes selectors, stop rather than silently accept IP-geolocated prices.
    """
    found_id, source = selected_location_from_data(hydration)
    if found_id and found_id != store.id:
        raise StoreMismatch(f'Page location switched to store #{found_id}; required #{store.id}')
    # This checks page UI, not a string in a hidden payload.
    snapshot = await page.evaluate('''() => {
      const els = Array.from(document.querySelectorAll('button, [role="button"], [aria-selected], [data-automation-id]'));
      return els.slice(0, 250).map(el => ({
        text: (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' ').slice(0,260),
        active: el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-pressed') === 'true' ||
                el.getAttribute('data-state') === 'active' || el.getAttribute('data-selected') === 'true'
      })).filter(x => x.text).slice(0, 120);
    }''')
    address = store.address.casefold()
    # A generic name such as "Walmart Supercenter" never suffices by itself.
    # A visible *option* in a picker is not proof of a selected store.
    selected_address_pickup = any(address in x['text'].casefold() and
        (x['active'] or 'pickup from' in x['text'].casefold()) for x in snapshot if address)
    number_pattern = re.compile(rf'(?:#|store\s*#?\s*){re.escape(store.id)}\b', re.I)
    explicit_number_present = any(number_pattern.search(x['text']) and
        (x['active'] or 'pickup from' in x['text'].casefold()) for x in snapshot)
    pickup_selected = any(
        (x['active'] and re.search(r'\bpickup\b', x['text'], re.I)) or
        (re.search(r'\bpickup\s+from\b', x['text'], re.I) and
         (address in x['text'].casefold() or (store.city.casefold() in x['text'].casefold() and len(store.city) >= 4)))
        for x in snapshot
    )
    if not found_id and not (explicit_number_present or selected_address_pickup):
        raise StoreMismatch('No explicit store ID or exact street address visible; cannot prove selected store')
    if require_pickup and not pickup_selected:
        raise StoreMismatch('No active PICKUP / Pickup from this store in UI; cannot verify fulfillment')
    proof_source = (source + '+ui') if found_id else 'ui-address-or-number'
    return Proof(url=page.url, store_id=store.id, source=proof_source,
                 fulfillment='PICKUP' if pickup_selected else 'UNKNOWN',
                 timestamp=datetime.now(timezone.utc).isoformat(timespec='seconds'))


class WalmartBrowser:
    def __init__(self, store: Store, limits: Limits, headless: bool = True):
        self.store, self.limits, self.headless = store, limits, headless
        self._pw = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.requests = 0
        self.navigation_budget: int | None = None  # diagnostic-only top-level limit
        self.http_request_budget: int | None = None  # diagnostic-only global browser request limit
        self.http_requests_seen = 0
        self.http_budget_hit = False
        self.delay_min = float(os.getenv('WALMART_MIN_DELAY_SECONDS', '1.5'))
        self.delay_max = float(os.getenv('WALMART_MAX_DELAY_SECONDS', '3.0'))

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        # Explicit executable override is for supported systems with preinstalled
        # Chromium; production uses the Playwright-matched vendor image/browser.
        browser_exe = os.getenv('WALMART_CHROMIUM_EXECUTABLE') or None
        self.browser = await self._pw.chromium.launch(headless=self.headless,
                                                     executable_path=browser_exe)
        kwargs = dict(locale='en-US', viewport={'width': 1440, 'height': 940},
                      service_workers='block' if self.http_request_budget is not None else 'allow')
        if self.store.session_state:
            kwargs['storage_state'] = self.store.session_state
        self.context = await self.browser.new_context(**kwargs)
        if self.http_request_budget is not None:
            await self.context.route('**/*', self._limit_http_request)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(12000)
        self.page.set_default_navigation_timeout(60000)
        return self

    async def __aexit__(self, *_):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    async def _limit_http_request(self, route) -> None:
        # Count all browser requests (including scripts, XHR and images), not only
        # page.goto. Once the budget is used, further requests are aborted locally.
        self.http_requests_seen += 1
        if (self.http_request_budget is not None and
                self.http_requests_seen > self.http_request_budget):
            self.http_budget_hit = True
            await route.abort('blockedbyclient')
            return
        await route.continue_()

    async def pace(self):
        await asyncio.sleep(random.uniform(self.delay_min, max(self.delay_min, self.delay_max)))

    async def goto(self, url: str) -> tuple[str, int]:
        await self.pace()
        assert self.page is not None
        if self.navigation_budget is not None and self.requests >= self.navigation_budget:
            raise BrowserFailure(f'BUDGET_STOP: {self.navigation_budget} navigations reached')
        self.requests += 1  # include failed HTTP/network attempts in the budget
        try:
            response = await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        except Exception as exc:
            if self.http_budget_hit:
                raise BrowserFailure('HTTP_REQUEST_BUDGET_STOP: browser subrequest cap reached') from exc
            raise
        if self.http_budget_hit:
            raise BrowserFailure('HTTP_REQUEST_BUDGET_STOP: browser subrequest cap reached')
        if not is_allowed_retail_url(self.page.url):
            raise BrowserFailure('Retailer navigation left allowed Walmart domain; reject redirect')
        # Walmart may respond HTTP 200 after redirecting to /blocked.
        # A successful transport status is never a product-page success.
        path = urlparse(self.page.url).path.casefold()
        if path.startswith(('/blocked', '/challenge', '/captcha')):
            raise BlockedResponse('Retailer access-restriction page reached; STOP without bypass')
        status = response.status if response else 0
        if status == 0:
            raise BrowserFailure(f'Navigation returned no HTTP status: {url}')
        await self.page.wait_for_timeout(700)
        html = await self.page.content()
        if len(html) > 10_000_000:
            raise ParseError(f'Response too large: {len(html)} bytes')
        parse_next_data(html, status)  # catches silent interstitial and missing data
        return html, status

    async def _click_first(self, selectors: list[str]) -> bool:
        assert self.page
        for selector in selectors:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible(timeout=1200):
                    await locator.click(timeout=3500)
                    return True
            except Exception:
                continue
        return False

    async def select_store(self) -> Proof:
        """Select explicitly via Walmart's visible store picker (never by guessed geolocation).

        Because retailer UX changes, a setup-time browser storage_state file can be supplied
        per store. Every visit still needs active store and fulfillment verification.
        """
        assert self.page
        try:
            _, _ = await self.goto('https://www.walmart.com/')
            data = parse_next_data(await self.page.content())
            return await page_proof(self.page, self.store, data)
        except StoreMismatch:
            pass
        # Open store/fulfillment picker using public UI. These are candidate selectors,
        # not an anti-detection technique. If the workflow changes we fail closed.
        did_open = await self._click_first([
            '[data-automation-id="header-location-button"]',
            'button[aria-label*="Pickup or delivery" i]',
            'button[aria-label*="How do you want your items" i]',
            'button[aria-label*="Change store" i]',
            'button:has-text("Pickup or delivery")',
            'button:has-text("Change store")',
        ])
        if not did_open:
            raise StoreMismatch('Walmart location picker not found; manual UI adapter maintenance needed')
        await self.page.wait_for_timeout(500)
        # Switch to explicit local pickup fulfillment before locating the store.
        await self._click_first(['button:has-text("Pickup")', '[role="tab"]:has-text("Pickup")'])
        await self._click_first(['button:has-text("Change")', 'button:has-text("Find a store")',
                                 'button:has-text("Search stores")'])
        entry = None
        for css in ('input[placeholder*="ZIP" i]', 'input[aria-label*="ZIP" i]',
                    'input[placeholder*="city" i]', 'input[name="zipCode"]'):
            input_ = self.page.locator(css).first
            if await input_.count():
                entry = input_
                break
        if entry is None:
            raise StoreMismatch('Store selector lacks postal-code input; cannot safely auto-select')
        await entry.fill(self.store.zipcode)
        await entry.press('Enter')
        await self.page.wait_for_timeout(1200)
        # Store card must include exact street address or store number.
        escaped_address = re.escape(self.store.address)
        escaped_id = re.escape(self.store.id)
        target = self.page.locator('[data-testid*="store" i], [data-automation-id*="store" i], article, [role="listitem"]')
        cards = await target.all()
        chosen = False
        for card in cards[:80]:
            try:
                txt = await card.inner_text(timeout=750)
                if not (re.search(escaped_address, txt, re.I) or re.search(rf'(?:#|store\s*#?\s*){escaped_id}\b', txt, re.I)):
                    continue
                button = card.get_by_role('button', name=re.compile(r'select|choose|set|pickup|use\s*this', re.I)).first
                if await button.count():
                    await button.click(timeout=2000)
                else:
                    await card.click(timeout=2000)
                chosen = True
                break
            except Exception:
                continue
        if not chosen:
            raise StoreMismatch(f'Exact store #{self.store.id} / {self.store.address} not found in picker')
        await self.page.wait_for_timeout(1500)
        # Reload server-side state: an optimistic picker modal is not store provenance.
        await self.goto('https://www.walmart.com/')
        try:
            return await page_proof(self.page, self.store, parse_next_data(await self.page.content()))
        except StoreMismatch as exc:
            raise StoreMismatch(f'Store picker clicked but live context is unverified: {exc}') from exc

    async def listing(self, url: str) -> tuple[str, dict, list[dict]]:
        """Scroll visible grid to include lazy cards; do not mistake a pagination cap for completion."""
        html, status = await self.goto(url)
        assert self.page
        data = parse_next_data(html, status)
        proof = await page_proof(self.page, self.store, data)
        previous = -1
        stable = 0
        for i in range(self.limits.max_scroll_rounds):
            count = await self.page.locator('[data-item-id]').count()
            if count == previous:
                stable += 1
            else:
                stable = 0
            if stable >= 3:
                break
            previous = count
            # A load-more button is followed only when it is part of the active category grid.
            await self._click_first(['button:has-text("Load more")', 'button:has-text("Show more results")'])
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await self.page.wait_for_timeout(500)
        else:
            raise ParseError('Scroll limit reached before listing stabilized: incomplete category')
        html = await self.page.content()
        listing = parse_listing(html)
        # Missing cards from hydration are discovered in DOM but *not* trusted as offers;
        # they must be confirmed on their own product detail pages.
        dom = await self.page.evaluate('''() => Array.from(document.querySelectorAll('[data-item-id]')).map(el => {
          const id = el.getAttribute('data-item-id');
          const link = el.querySelector('a[href*="/ip/"]');
          return {usItemId:id, canonicalUrl: link?.getAttribute('href') || '',
                  isSponsoredFlag:/\\bsponsored\\b/i.test((el.innerText||'').slice(0,200))};
        }).filter(x => x.usItemId)''')
        combined = listing.products[:]
        known = {product_id(p) for p in combined}
        by_id = {product_id(p): p for p in combined}
        for item in dom:
            pid = product_id(item)
            if not pid:
                continue
            if pid not in known:
                combined.append(item)
                known.add(pid)
            elif not product_url(by_id[pid]) and product_url(item):
                # Use the original DOM anchor rather than synthesizing a URL.
                by_id[pid]['canonicalUrl'] = item['canonicalUrl']
        proof.hash = listing.page_hash
        return html, {'proof':proof.as_dict(), 'http_status':status, 'reported_count':listing.reported_count,
                      'max_page':listing.max_page, 'total_candidates':len(combined)}, combined

    async def detail(self, url: str, expected_id: str) -> tuple[dict, Proof]:
        html, status = await self.goto(url)
        assert self.page
        product, hydration = parse_detail(html, status)
        if product_id(product) != expected_id:
            raise ParseError(f'Product identity shifted: expected {expected_id} got {product_id(product)}')
        proof = await page_proof(self.page, self.store, hydration)
        matches, reason = match_location(product, self.store)
        if not matches:
            raise StoreMismatch(f'Local price provenance missing/mismatched: {reason}')
        # The price is never accepted from a page that offers only shipping.
        proof.source += '+product.location'
        proof.hash = hashlib.sha256(html.encode()).hexdigest()
        return product, proof


def next_page_url(url: str, next_number: int) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['page'] = str(next_number)
    return urlunparse(parts._replace(query=urlencode(query)))
