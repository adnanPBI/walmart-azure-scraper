"""The externally specified JSON contract. Order is part of the wire format."""
from __future__ import annotations
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlparse

FIELDS = (
    "zipcode", "store_name", "store_location", "store_logo", "store_brand", "category",
    "sub_category", "product_title", "weight", "regular_price", "sale_price",
    "volume_deals_description", "volume_deals_price", "digital_deals_description",
    "digital_deals_price", "image_url", "url", "upc", "gupc", "ppm", "unit_price", "crawl_date"
)
PRICE_FIELDS = ("regular_price", "sale_price", "volume_deals_price", "digital_deals_price")
_PRIVATE_LABELS = {"great value", "equate", "marketside", "sam's choice", "mainstays", "parent's choice",
                   "ol' roy", "special kitty", "onn.", "onn", "time and tru", "wonder nation",
                   "george", "athletic works", "better homes & gardens", "hometrends", "auto drive",
                   "expert gardener", "pen + gear", "hyper tough", "vibrant life", "our finest"}
_APPROX = re.compile(r"\b(?:approx(?:imately|\.)?|about|estimated|variable\s*(?:wt|weight)|random\s*weight|priced\s*per\s*lb)\b", re.I)
_UPC = re.compile(r"^\d{8,14}$")


def price_string(value: object) -> str:
    """Normalize an explicitly displayed numeric price; never calculate offers."""
    if isinstance(value, dict):
        for name in ("price", "priceString", "displayPrice", "value", "amount"):
            if value.get(name) not in (None, ""):
                return price_string(value[name])
        return ""
    if value is None or isinstance(value, bool):
        return ""
    s = str(value).strip().replace(",", "")
    if not re.fullmatch(r"\$?\d+(?:\.\d{1,2})?", s):
        return ""
    try:
        n = Decimal(s.replace("$", ""))
        if n < 0:
            return ""
        return f"{n:.2f}"
    except (InvalidOperation, ValueError):
        return ""


def valid_web_url(value: str) -> bool:
    try:
        u = urlparse(value)
        return u.scheme in ("http", "https") and (u.hostname or "").lower().removeprefix("www.") == "walmart.com" if u.hostname else False
    except ValueError:
        return False


def private_label(brand: str) -> str:
    return "yes" if brand.casefold().strip() in _PRIVATE_LABELS else "no"


def approximate_weight(weight: str) -> bool:
    return bool(_APPROX.search(weight))


def validate_record(record: dict, strict: bool = True) -> list[str]:
    issues = []
    if tuple(record.keys()) != FIELDS:
        issues.append("wrong_order_or_fields")
    if any(not isinstance(x, str) for x in record.values()):
        issues.append("non_string_values")
    if record.get("gupc") != "" or record.get("unit_price") != "":
        issues.append("downstream_fields_must_be_empty")
    if not record.get("product_title", "").strip():
        issues.append("missing_product_title")
    if not record.get("zipcode", "").strip() or not record.get("store_location", "").strip():
        issues.append("missing_store")
    if not valid_web_url(record.get("url", "")):
        issues.append("invalid_product_url")
    if strict and not record.get("regular_price", ""):
        issues.append("missing_regular_price")
    for k in PRICE_FIELDS:
        if record.get(k) and price_string(record[k]) != record[k]:
            issues.append("invalid_price:" + k)
    if record.get("upc") and not _UPC.fullmatch(record["upc"]):
        issues.append("invalid_upc")
    if approximate_weight(record.get("weight", "")):
        issues.append("approximate_weight")
    if record.get("ppm") and not re.search(r"(?:/|per\s+)\s*[A-Za-z]", record["ppm"], re.I):
        issues.append("ppm_measurement_missing")
    try:
        date.fromisoformat(record.get("crawl_date", ""))
    except (TypeError, ValueError):
        issues.append("invalid_crawl_date")
    return issues


def empty_record() -> dict[str, str]:
    return dict.fromkeys(FIELDS, "")
