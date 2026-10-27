"""External store/category configuration, carefully validated before requests begin."""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
import csv
import hashlib
import json
import re
import yaml


@dataclass(frozen=True)
class Store:
    id: str
    zipcode: str
    name: str
    address: str
    city: str
    state: str
    session_state: str = ""
    logo_url: str = ""
    canary_item_ids: tuple[str, ...] = ()

    @property
    def location(self) -> str:
        return f"{self.address}, {self.city}, {self.state} {self.zipcode}"


@dataclass(frozen=True)
class Category:
    name: str
    subcategory: str
    url: str
    min_price: str = ""
    max_price: str = ""
    exclusions: tuple[str, ...] = ()
    requires_subcategory_discovery: bool = False

    @property
    def key(self) -> str:
        token = json.dumps([self.name, self.subcategory, self.url, self.min_price, self.max_price, self.exclusions, self.requires_subcategory_discovery], ensure_ascii=False)
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    @property
    def browse_url(self) -> str:
        parts = urlparse(self.url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if self.min_price:
            query['min_price'] = self.min_price
        if self.max_price:
            query['max_price'] = self.max_price
        return urlunparse(parts._replace(query=urlencode(query)))


@dataclass
class Limits:
    min_total_records: int = 500
    min_category_records: int = 1
    min_total_vs_last_good: float = 0.70
    min_category_vs_last_good: float = 0.50
    max_pages_per_category: int = 0  # 0 = no artificial page cap; enforce evidence-based termination
    max_detail_fail_fraction: float = 0.0  # legacy compatibility only; never allows missed required details
    max_scroll_rounds: int = 28
    detail_mode: str = "all"
    page_retries: int = 2
    max_empty_pages: int = 0
    required_fulfillment: str = "PICKUP"
    require_stable_store_proof: bool = True
    require_explicit_local_offer: bool = True
    min_price_shard_yield_ratio: float = 1.0  # legacy compatibility only; never tolerates missing listings


@dataclass
class Config:
    stores: list[Store]
    categories: list[Category]
    limits: Limits = field(default_factory=Limits)

    @property
    def fingerprint(self) -> str:
        # Config versioning protects resume against accidental category/store changes.
        data = {'stores': [x.__dict__ for x in self.stores], 'categories': [x.__dict__ for x in self.categories],
                'limits': self.limits.__dict__}
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=list).encode()).hexdigest()


def _col(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.casefold().lstrip('\ufeff'))


def _first(row: dict, *keys: str) -> str:
    d = {_col(k): v for k, v in row.items() if k is not None}
    for k in keys:
        if d.get(_col(k)) not in ('', None):
            return str(d[_col(k)]).strip()
    return ''


def load_categories(path: str) -> list[Category]:
    """Handles common column aliases from vendor category CSVs; preserves original URLs."""
    with open(path, encoding='utf-8-sig', newline='') as file:
        head = file.readline()
        file.seek(0)
        # Semicolon-delimited list supported when comma absent in the header.
        reader = csv.DictReader(file, delimiter=';' if ';' in head and ',' not in head else ',')
        result = []
        for index, row in enumerate(reader, start=2):
            retailer = _first(row, 'retailer')
            if retailer and retailer.casefold() != 'walmart':
                raise ValueError(f'Category CSV row {index} is for {retailer}, not Walmart')
            name = _first(row, 'category', 'category (auto)', 'department', 'main_category', 'category_name')
            sub = _first(row, 'sub_category', 'subcategory', 'subcat', 'subcategoryname', 'sub_category_name')
            url = _first(row, 'url', 'category_url', 'subcategory_url', 'link', 'walmart_url')
            if not url:
                # A common layout has Category + URL and no Subcategory.
                raise ValueError(f'Category CSV row {index} missing category URL; columns: {reader.fieldnames}')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in ('www.walmart.com', 'walmart.com'):
                raise ValueError(f'Invalid Walmart URL at row {index}: {url!r}')
            if not (name or sub):
                raise ValueError(f'Category CSV row {index} needs a category or subcategory name')
            min_price = _first(row, 'min_price', 'price_min')
            max_price = _first(row, 'max_price', 'price_max')
            for value in (min_price, max_price):
                if value:
                    if Decimal(value) < 0:
                        raise ValueError(f'Negative price shard in row {index}')
            if min_price and max_price and Decimal(min_price) >= Decimal(max_price):
                raise ValueError(f'Invalid price shard interval in row {index}')
            notes = _first(row, 'notes', 'instructions')
            scope = _first(row, 'scope')
            # Explicitly retain the retailer's exclusions rather than silently
            # dropping the Notes column on the supplied parent-category CSV.
            exclusions = tuple(re.findall(r"['\"]([^'\"]+)['\"]", notes)) if re.search(r'\bexclude\b', notes, re.I) else ()
            if re.search(r'\bexclude\b', notes, re.I) and not exclusions:
                raise ValueError(f'Unparsed exclusion notes at row {index}: {notes!r}')
            requires_discovery = bool(re.search(r'all\s+subcategor(?:y|ies)', scope, re.I)) and not sub
            result.append(Category(name or sub, sub, url, min_price, max_price,
                                   exclusions, requires_discovery))
    if not result:
        raise ValueError('No category rows: refuse empty crawl')
    excluded_by_parent = {}
    for c in result:
        if c.exclusions:
            excluded_by_parent.setdefault(c.name, set()).update(x.casefold() for x in c.exclusions)
    for c in result:
        if c.subcategory and c.subcategory.casefold() in excluded_by_parent.get(c.name, set()):
            raise ValueError(f'Forbidden subcategory {c.subcategory!r} for {c.name!r}')
    if len({x.key for x in result}) != len(result):
        raise ValueError('Duplicate category URL/price-range entries; remove duplicates')
    return result


def load_config(categories_csv: str, stores_yaml: str) -> Config:
    categories = load_categories(categories_csv)
    raw = yaml.safe_load(Path(stores_yaml).read_text(encoding='utf-8')) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get('stores'), list) or not raw['stores']:
        raise ValueError('stores.yaml requires nonempty stores list')
    stores: list[Store] = []
    for s in raw['stores']:
        try:
            item = Store(id=str(s['id']).strip(), zipcode=str(s['zipcode']).strip(),
                         name=str(s['name']).strip(), address=str(s['address']).strip(),
                         city=str(s['city']).strip(), state=str(s['state']).strip(),
                         session_state=str(s.get('session_state') or ''),
                         logo_url=str(s.get('logo_url') or ''),
                         canary_item_ids=tuple(map(str, s.get('canary_item_ids') or [])))
        except (TypeError, KeyError) as exc:
            raise ValueError(f'Store missing field: {exc}') from exc
        if not re.fullmatch(r'\d{1,6}', item.id) or not re.fullmatch(r'\d{5}(?:-\d{4})?', item.zipcode):
            raise ValueError('A real numeric store ID and US ZIP are required; sample placeholders cannot run')
        if any(not v or 'REPLACE' in v.upper() for v in (item.address, item.name, item.city, item.state)):
            raise ValueError('Store address/name not configured')
        stores.append(item)
    if len({s.id for s in stores}) != len(stores):
        raise ValueError('Duplicate store IDs')
    unknown = set((raw.get('limits') or {})) - set(Limits.__dataclass_fields__)
    if unknown:
        raise ValueError(f'Unknown limits: {sorted(unknown)}')
    limits = Limits(**(raw.get('limits') or {}))
    if limits.detail_mode not in ('all', 'missing_local_and_price'):
        raise ValueError('detail_mode must be all or missing_local_and_price')
    if limits.required_fulfillment != 'PICKUP':
        raise ValueError('This release only supports verified local PICKUP')
    if not (0 <= limits.max_detail_fail_fraction < 1):
        raise ValueError('Invalid max_detail_fail_fraction')
    if limits.max_pages_per_category < 0 or limits.max_scroll_rounds < 1:
        raise ValueError('max_pages_per_category must be 0 (unlimited) or positive; max_scroll_rounds >= 1')
    return Config(stores, categories, limits)
