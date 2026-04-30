"""Apify thin client — fetches structured listing data for a US address
via the kawsar/realtor-property-details-cheap actor.

Why Realtor and not Zillow: Realtor.com has materially weaker anti-bot
than Zillow's PerimeterX + Cloudflare combo, and Apify maintains the
actor as the site evolves. Cost: $0.001 per lookup, $5/mo free credits
on the Apify free plan ≈ 5,000 free lookups/month — essentially free
for our discovery-phase volume.

API: hit run-sync-get-dataset-items so the request returns the actor's
output inline (vs the async run-then-poll dance). Single-address calls
typically resolve in 5-15 seconds."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_ACTOR = "kawsar~realtor-property-details-cheap"
_BASE = f"https://api.apify.com/v2/acts/{_ACTOR}/run-sync-get-dataset-items"


def is_configured() -> bool:
    return bool(settings.apify_api_token)


def lookup_property(address: str, timeout: float = 60.0) -> dict[str, Any] | None:
    """Look up a single address via the Realtor actor. Returns the
    first dataset item (a dict with beds, baths, sqft, listPrice, etc.)
    or None on any failure."""
    if not settings.apify_api_token:
        log.info("apify: not configured, skipping lookup")
        return None
    if not address.strip():
        return None

    body = {
        "searchQueries": [address.strip()],
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyCountry": "US",
        },
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            r = client.post(
                _BASE,
                params={"token": settings.apify_api_token},
                json=body,
            )
    except Exception:
        log.exception("apify lookup request failed for %s", address[:80])
        return None

    if r.status_code != 200:
        log.warning(
            "apify non-200 status=%s body=%s for %s",
            r.status_code,
            r.text[:200],
            address[:80],
        )
        return None

    try:
        items = r.json()
    except Exception:
        log.exception("apify response not JSON for %s", address[:80])
        return None

    if not isinstance(items, list) or not items:
        log.info("apify returned no items for %s", address[:80])
        return None

    first = items[0]
    if not isinstance(first, dict):
        return None
    log.info(
        "apify lookup ok address=%s beds=%s baths=%s sqft=%s price=%s",
        address[:60],
        first.get("beds"),
        first.get("baths"),
        first.get("sqft"),
        first.get("listPrice"),
    )
    return first


def to_listing_shape(item: dict[str, Any]) -> dict[str, Any]:
    """Map a Realtor actor result to our internal ListingData shape so
    /houses/auto-fill returns the same fields the screenshot path does."""
    out: dict[str, Any] = {}

    # Address — actor returns separate parts; assemble.
    parts = [
        item.get("address"),
        item.get("city"),
        item.get("state"),
        item.get("postalCode"),
    ]
    addr_str = ", ".join(p for p in parts if isinstance(p, str) and p)
    if addr_str:
        out["address"] = addr_str

    # Numeric fields — coerce defensively, the actor occasionally
    # returns strings or null.
    def _intish(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    def _floatish(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    price = _intish(item.get("listPrice"))
    if price is not None:
        out["list_price"] = price

    beds = _intish(item.get("beds"))
    if beds is not None:
        out["beds"] = beds

    baths = _floatish(item.get("baths"))
    if baths is not None:
        out["baths"] = baths

    sqft = _intish(item.get("sqft"))
    if sqft is not None:
        out["sqft"] = sqft

    # price_kind — Realtor's status field tells us. "for_sale",
    # "for_rent", "sold", etc. We only differentiate sale vs rent.
    status = item.get("status")
    if isinstance(status, str):
        s = status.lower()
        if "rent" in s:
            out["price_kind"] = "rent"
        elif s in ("for_sale", "active", "for sale", "pending"):
            out["price_kind"] = "sale"

    href = item.get("href")
    if isinstance(href, str) and href:
        out["listing_url"] = href

    return out
