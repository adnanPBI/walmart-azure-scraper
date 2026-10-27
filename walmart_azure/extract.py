"""Extract embedded product models; never substitute a generic shipping offer for pickup."""
from __future__ import annotations
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse
import hashlib
import json
import re
from bs4 import BeautifulSoup
from .schema import price_string, approximate_weight, private_label, empty_record
from .config import Store, Category

BLOCK_TERMS = ("robot or human", "press & hold", "verify you are a human", "access denied",
               "unusual traffic", "px-captcha", "captcha required")
_PRICE_PER_MEASURE = re.compile(r'(?:\$\s?\d+(?:\.\d+)?|\d+(?:\.\d+)?\s?¢)\s*(?:/|per\s+)\s*(?:fl\s*oz|oz|lb|kg|g|ml|l|gal|qt|ct|ea|each|pack|sheet|ft|sq\s*ft|unit|serving)\b', re.I)
_WEIGHT = re.compile(r'(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?\s*(?:fl\s*oz|oz|lb|lbs|kg|g|mg|mL|L|gal|quart|qt|ct|count|pk|pack|sheets?|rolls?|bottles?))(?![A-Za-z])', re.I)
_URL_ID = re.compile(r'/ip/(?:[^/?]+/)?(\d{5,20})(?:[/?#]|$)')
_DIGITAL = re.compile(r'\b(?:digital\s*coupon|clip(?:ped)?\s*(?:coupon|to save)|activate\s*(?:coupon|offer)|save\s*(?:coupon|offer))\b', re.I)
_VOLUME = re.compile(r'\b(?:\d+\s*for\s*\$|buy\s+\d+[^\n]*get\s+\d+|bogo\b|buy\s+one\s+get\s+one|mix\s*(?:or|&)\s*match|must\s*buy\s+\d+|save\s*\$\d+[^\n]*when\s*you\s*buy\s*\d+)\b', re.I)
_EXCLUDED_INCENTIVES = re.compile(r'\b(?:walmart\s*cash|cashback|cash\s*back|rewards?\s*points?)\b', re.I)
_EXPLICIT_UNIT_PRICE = re.compile(r'\$\s*(\d+(?:\.\d{1,2})?)\s*each\b', re.I)
_EXPLICIT_FOR_PRICE = re.compile(r'\b\d+\s*for\s*\$\s*(\d+(?:\.\d{1,2})?)\b', re.I)
# Match a composite source pack label before considering a single inner-unit size.
# Return exactly the witnessed label, never infer total volume/weight.
_PACK_WITH_UNIT = re.compile(
    r'(?<!\w)\d+\s*(?:[- ]\s*(?:pack|pk)|(?:-)?\s*(?:count|ct))\s*(?:of\s+|x\s+|,?\s+)?'
    r'\d+(?:\.\d+)?\s*(?:fl\s*oz|oz|lbs?|g|kg|ml|l|qt|gal)\b'
    r'(?:\s+(?:cans?|bottles?|pouches?|boxes?|bags?|each))?', re.I)
_MULTIPACK_X = re.compile(
    r'(?<!\w)\d+\s*[x×]\s*\d+(?:\.\d+)?\s*(?:fl\s*oz|oz|lbs?|g|kg|ml|l|qt|gal)\b'
    r'(?:\s+(?:cans?|bottles?|each))?', re.I)


class BlockedResponse(RuntimeError):
    pass


class ParseError(RuntimeError):
    pass


@dataclass
class Listing:
    products: list[dict]
    reported_count: int | None
    max_page: int
    page_hash: str
    hydration: dict


def nested(source: dict | None, *path: str) -> Any:
    cur = source
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', unescape(BeautifulSoup(value, 'html.parser').get_text(' ', strip=True))).strip()


def check_blocked(html: str, response_status: int = 200) -> None:
    if response_status in (401, 403, 407, 408, 412, 418, 429, 451, 503):
        raise BlockedResponse(f'Blocked/disallowed or throttled HTTP status {response_status}')
    sample = html[:80000].lower()
    if any(term in sample for term in BLOCK_TERMS):
        raise BlockedResponse('Challenge/interstitial detected; stop, do not bypass')


def parse_next_data(html: str, status: int = 200) -> dict:
    check_blocked(html, status)
    soup = BeautifulSoup(html, 'html.parser')
    script = soup.find('script', id='__NEXT_DATA__')
    if script is None or not script.string:
        raise ParseError('No __NEXT_DATA__ (possible JS change or silent block); never treat as empty success')
    try:
        node = json.loads(script.string)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ParseError('Invalid embedded JSON hydration') from exc
    if not isinstance(node, dict):
        raise ParseError('Unexpected hydration type')
    return node


def hydration_roots(data: dict) -> list[dict]:
    """Supported public HTML hydration containers, including observed 2026 Tempo SSR.

    Does not grant price/store provenance: callers still verify live selected
    store, seller, pickup and page identity independently.
    """
    props = nested(data, 'props', 'pageProps') or {}
    roots = []
    for field in ('initialData', 'initialTempoData'):
        payload = props.get(field)
        if isinstance(payload, dict):
            roots.append(payload)
            if isinstance(payload.get('data'), dict):
                roots.append(payload['data'])
    return roots


def _explicit_node(data: dict, name: str) -> dict | None:
    for root in hydration_roots(data):
        value = root.get(name) or nested(root, 'data', name)
        if isinstance(value, dict):
            return value
    return None


def parse_listing(html: str, status: int = 200) -> Listing:
    data = parse_next_data(html, status)
    sr = _explicit_node(data, 'searchResult')
    if sr is None:
        for root in hydration_roots(data):
            sr = nested(root, 'search', 'searchResult')
            if isinstance(sr, dict):
                break
    if not isinstance(sr, dict):
        raise ParseError('Missing searchResult: category layout changed/invalid URL')
    stacks = sr.get('itemStacks') or []
    if not isinstance(stacks, list):
        raise ParseError('Invalid itemStacks shape')
    items = []
    for stack in stacks:
        if not isinstance(stack, dict):
            continue
        for item in stack.get('items') or []:
            if isinstance(item, dict) and (item.get('usItemId') or item.get('canonicalUrl')):
                items.append(item)
    # A zero-product page must fail the category gate, not quietly declare completion.
    raw_max = nested(sr, 'paginationV2', 'maxPage') or nested(sr, 'pagination', 'maxPage') or sr.get('maxPage')
    reported_count = sr.get('aggregatedCount')
    try:
        reported_count = int(reported_count) if reported_count is not None else None
    except (ValueError, TypeError):
        reported_count = None
    if raw_max in (None, ''):
        # Only explicit, positive end-of-pagination evidence may justify completion.
        # A missing count AND pagination is *unknown*, not a one-page category.
        pagination = sr.get('paginationV2') or sr.get('pagination') or {}
        if not isinstance(pagination, dict):
            pagination = {}
        explicit_end = (pagination.get('hasNextPage') is False or
                        pagination.get('isLastPage') is True or
                        sr.get('hasNextPage') is False or
                        sr.get('isLastPage') is True)
        if reported_count is not None:
            if reported_count > len(items):
                raise ParseError('Pagination missing while reported count exceeds page products')
            if reported_count <= 0 or not items:
                raise ParseError('Missing positive proof for an empty category')
        elif not explicit_end:
            raise ParseError('Pagination missing: no total count or explicit terminal-page evidence')
        max_page = 1
    else:
        try:
            max_page = int(raw_max)
        except (ValueError, TypeError) as exc:
            raise ParseError('Unparseable maxPage; cannot establish collection coverage') from exc
        if max_page < 1:
            raise ParseError('Invalid maxPage value')
    return Listing(items, reported_count, max_page, hashlib.sha256(html.encode()).hexdigest(), data)


def parse_detail(html: str, status: int = 200) -> tuple[dict, dict]:
    data = parse_next_data(html, status)
    product = _explicit_node(data, 'product')
    if not isinstance(product, dict) or not (product.get('usItemId') or product.get('name')):
        raise ParseError('Missing product node on detail page')
    return product, data


def product_id(obj: dict) -> str:
    for key in ('usItemId', 'itemId'):
        val = obj.get(key)
        if val is not None and str(val).isdigit():
            return str(val)
    url = str(obj.get('canonicalUrl') or obj.get('productUrl') or obj.get('url') or '')
    m = _URL_ID.search(url)
    return m.group(1) if m else ''


def product_url(item: dict) -> str:
    url = str(item.get('canonicalUrl') or item.get('productUrl') or item.get('url') or '')
    if url:
        absolute = urljoin('https://www.walmart.com', url)
        # Never navigate to external URLs supplied by embedded page data.
        if urlparse(absolute).hostname not in ('walmart.com', 'www.walmart.com'):
            return ''
        return absolute
    # Never manufacture a product URL: the client requires the exact observed link.
    return ''


def first_image(item: dict) -> str:
    im = item.get('imageInfo') or {}
    if isinstance(im, str):
        return im if im.startswith('https://') else ''
    if isinstance(im, dict):
        for k in ('thumbnailUrl', 'imageUrl', 'url'):
            if isinstance(im.get(k), str):
                return im[k]
        for k in ('allImages', 'images'):
            if isinstance(im.get(k), list):
                for elem in im[k]:
                    if isinstance(elem, str) and elem.startswith('https://'):
                        return elem
                    if isinstance(elem, dict):
                        for name in ('url', 'imageUrl', 'thumbnailUrl'):
                            if isinstance(elem.get(name), str):
                                return elem[name]
    for k in ('image', 'imageUrl'):
        if isinstance(item.get(k), str):
            return item[k]
    return ''


def seller_is_walmart(item: dict) -> bool:
    seller = item.get('sellerName') or nested(item, 'sellerInfo', 'name') or nested(item, 'seller', 'name')
    seller_type = (item.get('sellerType') or nested(item, 'sellerInfo', 'sellerType') or '')
    if seller is not None:
        name = re.sub(r'\s+', ' ', str(seller).strip().casefold())
        return name in {'walmart.com', 'walmart', 'walmart stores inc.', 'walmart stores inc'}
    # Only an explicitly internal first-party item passes without a named seller.
    return str(seller_type).upper() in ('INTERNAL', 'WALMART')


def pickup_availability(item: dict) -> str:
    """Explicit, store-local pickup status (AVAILABLE, UNAVAILABLE or UNKNOWN).

    A shipping-only offer or generic OUT_OF_STOCK flag is not store pickup proof.
    UNKNOWN is never an acceptance-eligible local product.
    """
    options = item.get('fulfillmentOptions') or nested(item, 'fulfillment', 'options') or []
    if isinstance(options, dict):
        options = options.get('options') or [options]
    statuses: list[str] = []
    if isinstance(options, list):
        for opt in options:
            if not isinstance(opt, dict):
                continue
            kind = str(opt.get('type') or opt.get('fulfillmentType') or opt.get('method') or '').upper()
            if 'PICKUP' in kind or 'IN_STORE' in kind or 'INSTORE' in kind:
                statuses.append(str(opt.get('status') or opt.get('availabilityStatus') or '').upper())
    fallback = item.get('fulfillmentSummary') or item.get('fulfillment') or {}
    if isinstance(fallback, dict):
        pickup = fallback.get('pickup') or fallback.get('pickupOptions') or fallback.get('storePickup')
        if isinstance(pickup, dict):
            statuses.append(str(pickup.get('availabilityStatus') or pickup.get('status') or '').upper())
    if any(x in {'IN_STOCK', 'AVAILABLE', 'LIMITED_STOCK', 'AVAILABLE_FOR_PICKUP', 'INSTORE'} for x in statuses):
        return 'AVAILABLE'
    if any(x in {'OUT_OF_STOCK', 'UNAVAILABLE', 'NOT_AVAILABLE', 'NOT_ELIGIBLE', 'SOLD_OUT'} for x in statuses):
        return 'UNAVAILABLE'
    return 'UNKNOWN'


def local_pickup_offer(item: dict) -> bool:
    """True only when explicit local pickup is available; unavailable is retained separately."""
    return pickup_availability(item) == 'AVAILABLE'


def match_location(item: dict, store: Store) -> tuple[bool, str]:
    location = item.get('location') or {}
    if not isinstance(location, dict):
        return False, 'no structured item location'
    store_ids = location.get('storeIds') or [location.get('storeId') or location.get('pickupStoreId')]
    if not isinstance(store_ids, list):
        store_ids = [store_ids]
    if store.id not in [str(x) for x in store_ids]:
        return False, f'store_id mismatch {store_ids!r} vs requested {store.id}'
    # Walmart's postal code can represent the customer's delivery ZIP rather than the store ZIP.
    # A conflicting explicitly selected store ID is fatal; absent zipcode is not a contradiction.
    return True, f'product.location.storeIds={store_ids}'


def find_ppm(item: dict) -> str:
    """Accept only displayed price+unit text in known fields. Never calculate PPM."""
    pi = item.get('priceInfo') or {}
    values = []
    for k in ('unitPrice', 'pricePerUnit', 'pricePerMeasure', 'ppu', 'unitPriceString', 'pricePerUnitDisplay'):
        values.append(pi.get(k))
        values.append(item.get(k))
    for val in values:
        if isinstance(val, dict):
            val = val.get('priceString') or val.get('displayValue') or val.get('displayText') or val.get('formattedPrice')
        if isinstance(val, str):
            text = clean_text(val)
            m = _PRICE_PER_MEASURE.search(text)
            if m:
                return m.group(0)
    return ''


def get_weight(item: dict) -> str:
    name = clean_text(item.get('name') or item.get('productName') or '')
    # The product name may give the entire pack identity while a `size` field
    # contains only the inner-unit quantity (e.g. `12 fl oz`). Prefer the full
    # label that was actually displayed; never compute 144 fl oz.
    for regex in (_PACK_WITH_UNIT, _MULTIPACK_X):
        match = regex.search(name)
        if match:
            return match.group(0).strip()
    for k in ('size', 'sizeDisplay', 'weight', 'netWeight', 'packageSize', 'productSize', 'quantityDisplay'):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return clean_text(v)
        if isinstance(v, dict):
            label = v.get('display') or v.get('displayValue') or v.get('valueText')
            if isinstance(label, str):
                return clean_text(label)
    # In category listing, size often exists only in the displayed title.
    matches = _WEIGHT.findall(name)
    return matches[-1] if matches else ''


def _promo_entries(item: dict) -> list[tuple[str, str, str]]:
    """Retain each complete original promotion object and its linked terms.

    Return (displayed full text, classification hint, explicitly displayed
    payable price).  Savings and percentage discounts are NEVER payable prices.
    Never mingle terms belonging to separate promotion objects.
    """
    promo_fields = ('promotions', 'promotionInfo', 'promoInfo', 'promotion',
                    'badges', 'badgesInfo', 'productBadges', 'coupon', 'coupons',
                    'offer', 'offers', 'promoDescription', 'savingsText')
    primary = ('text', 'description', 'displayText', 'title', 'label', 'message',
               'badgeText', 'offerText', 'promoText')
    term_keys = ('terms', 'termsAndConditions', 'conditions', 'eligibility',
                 'quantity', 'minQuantity', 'minimumQuantity', 'limit', 'limits',
                 'maxQuantity', 'validThrough', 'validUntil', 'expiration',
                 'expiry', 'endDate', 'clippingRequirement', 'requiresClipping')
    type_keys = ('type', 'offerType', 'promotionType', 'promoType', 'couponType', 'badgeType')
    payable_keys = ('displayedPromotionalPrice', 'displayedDealPrice',
                    'promotionalPriceDisplay', 'offerPriceDisplay', 'dealPriceDisplay')
    found: list[tuple[str,str,str]] = []

    def render_term(value: Any, key: str = '') -> list[str]:
        if isinstance(value, str):
            text = clean_text(value)
            return [text] if text else []
        if isinstance(value, bool):
            return [f'{key}: {str(value).lower()}'] if key else []
        if isinstance(value, (int, float)):
            return [f'{key}: {value}'] if key else []
        if isinstance(value, list):
            return [part for el in value for part in render_term(el)]
        if isinstance(value, dict):
            parts = []
            for nested_key, nested_val in value.items():
                if nested_key.casefold() in {'id','offerid','productid','uuid'}:
                    continue
                parts.extend(render_term(nested_val, nested_key))
            return parts
        return []

    def walk(value: Any, hint: str = '', depth: int = 0):
        if depth > 5 or len(found) >= 80:
            return
        if isinstance(value, list):
            for item_value in value:
                walk(item_value, hint, depth + 1)
            return
        if isinstance(value, str):
            text = clean_text(value)
            if text:
                found.append((text[:2000], hint, ''))
            return
        if not isinstance(value, dict):
            return
        local_hint = ' '.join([hint] + [str(value[k]) for k in type_keys if isinstance(value.get(k), str)])
        texts = []
        for key in primary:
            if key in value:
                texts.extend(render_term(value[key], key))
        for key in term_keys:
            if key in value:
                texts.extend(render_term(value[key], key))
        # Repeated descriptions in one object add no independent information.
        texts = list(dict.fromkeys(x for x in texts if x))
        explicit_payable = ''
        for key in payable_keys:
            v = value.get(key)
            # Explicit *display text*, not an inferred savings amount.
            if isinstance(v, str):
                display = clean_text(v)
                # Price-related provider keys can still contain a *saving*, not
                # an amount payable. Never convert a displayed discount, rebate
                # or cashback into a purchase price.
                if re.search(r'\b(?:save|saving|discount|off|rebate|cashback)\b', display, re.I):
                    continue
                explicit = re.fullmatch(r'\$\s*\d+(?:\.\d{1,2})?\s*(?:each|ea)?', display, re.I)
                if explicit:
                    explicit_payable = price_string(display)
                    break
                direct = _payable_price(display)
                if direct:
                    explicit_payable = direct
                    break
        if texts:
            found.append(('; '.join(texts)[:3000], local_hint, explicit_payable))
        for key in promo_fields:
            if key in value:
                walk(value[key], local_hint, depth + 1)

    for root in (item, item.get('priceInfo') or {}):
        if isinstance(root, dict):
            for key in promo_fields:
                if key in root:
                    walk(root[key], 'digital coupon' if key in ('coupon','coupons') else '')
    return list(dict.fromkeys(found))


def _payable_price(promo: str) -> str:
    """Only the *displayed final payable price*, never an amount saved."""
    for match in _EXPLICIT_UNIT_PRICE.finditer(promo):
        before = promo[:match.start()].rstrip().casefold()
        # Save $2 each with Digital Coupon is a saving, NOT $2 payable.
        tail = before.split(';')[-1]
        if re.search(r'\b(?:save|saves|saving|discount|off|cashback|rebate)\b', tail):
            continue
        return price_string(match.group(1))
    match = _EXPLICIT_FOR_PRICE.search(promo)
    if match:
        return price_string(match.group(1))
    return ''


def parse_deals(item: dict) -> dict[str, str]:
    out = {'volume_deals_description': '', 'volume_deals_price': '',
           'digital_deals_description': '', 'digital_deals_price': ''}
    for promo, hint, explicit_payable in _promo_entries(item):
        if _EXCLUDED_INCENTIVES.search(promo + ' ' + hint):
            continue
        if _DIGITAL.search(promo) or ('digital' in hint.casefold() and 'coupon' in hint.casefold()):
            kind = 'digital'
        elif _VOLUME.search(promo) or (('multibuy' in hint.casefold() or 'multi_buy' in hint.casefold()) and _VOLUME.search(promo)):
            kind = 'volume'
        else:
            continue
        dk, pk = kind + '_deals_description', kind + '_deals_price'
        # | distinguishes separate retailer offers. ; retains terms within one.
        out[dk] = ' | '.join([out[dk], promo]) if out[dk] else promo
        payable = explicit_payable or _payable_price(promo)
        if payable and not out[pk]:
            out[pk] = payable
    return out


def regular_sale(item: dict) -> tuple[str, str]:
    pi = item.get('priceInfo') or {}
    current = price_string(pi.get('currentPrice') or item.get('price') or pi.get('linePrice'))
    was = price_string(pi.get('wasPrice') or pi.get('listPrice'))
    if was and current and float(was) > float(current):
        return was, current
    return current, ''


def make_record(item: dict, store: Store, category: Category, crawl_date: str) -> dict:
    record = empty_record()
    record.update(zipcode=store.zipcode, store_name=store.name, store_location=store.location,
                  store_logo=store.logo_url,
                  store_brand=private_label(str(item.get('brand') or nested(item, 'brandInfo', 'name') or '')),
                  category=category.name, sub_category=category.subcategory,
                  product_title=clean_text(item.get('name') or item.get('productName') or ''),
                  weight=get_weight(item), image_url=first_image(item), url=product_url(item),
                  upc=str(item.get('upc') or item.get('gtin12') or '').strip(), ppm=find_ppm(item),
                  crawl_date=crawl_date)
    record['regular_price'], record['sale_price'] = regular_sale(item)
    record.update(parse_deals(item))
    return record


def sponsored(item: dict) -> bool:
    keys = ('isSponsoredFlag', 'isSponsored', 'sponsored', 'isAd', 'ad')
    return any(item.get(k) in (True, 'true', 'True', 1) for k in keys)
