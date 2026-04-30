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

_REALTOR_ACTOR = "kawsar~realtor-property-details-cheap"
# brilliant_gum's Zillow scraper is pay-per-event on the free tier
# (~$0.013 per single-property lookup: $0.01 actor-start + $0.003
# search-listing). The previous one-api~zillow-scrape-address-url-zpid
# actor we tried first was a $25/mo flat-rate actor that silently
# returns nothing without a paid subscription.
_ZILLOW_ACTOR = "brilliant_gum~zillow-property-scraper"

_REALTOR_BASE = f"https://api.apify.com/v2/acts/{_REALTOR_ACTOR}/run-sync-get-dataset-items"
_ZILLOW_BASE = f"https://api.apify.com/v2/acts/{_ZILLOW_ACTOR}/run-sync-get-dataset-items"


def is_configured() -> bool:
    return bool(settings.apify_api_token)


class ApifyResult:
    """Detailed diagnostic of an actor call. `items` is None on any
    failure; the other fields surface the why so we can debug without
    Railway log access."""

    def __init__(
        self,
        items: list[dict] | None,
        status: int | None,
        elapsed_s: float,
        error: str | None,
        body_preview: str = "",
    ):
        self.items = items
        self.status = status
        self.elapsed_s = elapsed_s
        self.error = error
        self.body_preview = body_preview

    @property
    def trace_tag(self) -> str:
        """Compact tag for the auto-fill tier_trace string."""
        if self.error:
            return f"err({self.error})"
        if self.status and self.status != 200:
            return f"http_{self.status}"
        if self.items is None:
            return "bad_json"
        return f"items={len(self.items)}"


def _post_actor(url: str, body: dict, timeout: float = 120.0) -> ApifyResult:
    """Shared POST + JSON-parse logic for run-sync-get-dataset-items.
    Returns an ApifyResult with full diagnostic context. Apify actor
    cold starts can hit 30-60s on the free tier, so the timeout is
    deliberately generous."""
    import time as _time

    if not settings.apify_api_token:
        return ApifyResult(None, None, 0.0, "no_token")

    t0 = _time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            r = client.post(
                url,
                params={"token": settings.apify_api_token},
                json=body,
            )
    except httpx.TimeoutException:
        elapsed = _time.monotonic() - t0
        log.warning("apify timed out after %.1fs url=%s", elapsed, url)
        return ApifyResult(None, None, elapsed, "timeout")
    except Exception as e:
        elapsed = _time.monotonic() - t0
        log.exception("apify request failed url=%s", url)
        return ApifyResult(None, None, elapsed, type(e).__name__)
    elapsed = _time.monotonic() - t0
    body_preview = (r.text or "")[:300]

    # Apify returns 201 when run-sync completes synchronously with
    # results created, not 200. Accept any 2xx.
    if r.status_code >= 400:
        log.warning(
            "apify error status=%s elapsed=%.1fs url=%s body=%s",
            r.status_code,
            elapsed,
            url,
            body_preview,
        )
        return ApifyResult(None, r.status_code, elapsed, None, body_preview)

    try:
        items = r.json()
    except Exception:
        log.exception("apify response not JSON url=%s", url)
        return ApifyResult(None, 200, elapsed, "bad_json", body_preview)
    if not isinstance(items, list):
        return ApifyResult(None, 200, elapsed, "non_list_json", body_preview)

    log.info(
        "apify ok url=%s elapsed=%.1fs items=%d",
        url,
        elapsed,
        len(items),
    )
    return ApifyResult(items, 200, elapsed, None, body_preview)


def lookup_property(address: str, timeout: float = 120.0) -> ApifyResult:
    """Realtor.com path. Cheapest ($0.001/result) and cleanest data
    when the property is currently or recently listed. Returns an
    ApifyResult with full diagnostic info — caller picks .items[0]
    if any."""
    if not address.strip():
        return ApifyResult(None, None, 0.0, "empty_address")

    body = {
        "searchQueries": [address.strip()],
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyCountry": "US",
        },
    }
    return _post_actor(_REALTOR_BASE, body, timeout=timeout)


def lookup_zillow(address: str, timeout: float = 180.0) -> ApifyResult:
    """Zillow path via brilliant_gum's pay-per-event actor.
    `mode: combined` gets both a search hit + the full detail block
    in one run; `maxListings: 1` keeps cost predictable. Single
    lookup costs ~$0.013 on the free tier ($0.01 actor-start +
    $0.003 search-listing event)."""
    if not address.strip():
        return ApifyResult(None, None, 0.0, "empty_address")

    # listingType enum: for_sale | for_rent | recently_sold. "ALL"
    # was invalid (returned 400). Default to for_sale; if a sale
    # listing isn't found and Realtor missed too, downstream tiers
    # take over. Could chain for_rent / recently_sold here in a
    # follow-up if discovery shows it matters.
    body = {
        "mode": "combined",
        "searchLocation": address.strip(),
        "listingType": "for_sale",
        "maxListings": 1,
        "useApifyProxy": True,
        "proxyCountry": "US",
        # Disable the heavier extras — we only need the headline
        # fields. Also keeps each lookup faster.
        "computeMetrics": False,
        "includeSchools": False,
        "includeHistory": False,
        "includeNearby": False,
    }
    return _post_actor(_ZILLOW_BASE, body, timeout=timeout)


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


def to_listing_shape_zillow(item: dict[str, Any]) -> dict[str, Any]:
    """Map a Zillow actor result to our internal ListingData shape.
    Zillow's field names differ from Realtor's — beds vs bedrooms,
    sqft vs livingArea, etc. Prefer the asking price; fall back to
    Zestimate when no asking price (off-market homes)."""
    out: dict[str, Any] = {}

    # Address — assemble from parts.
    parts = [
        item.get("streetAddress") or item.get("address"),
        item.get("city") or item.get("addressCity"),
        item.get("state") or item.get("addressState"),
        item.get("zipcode") or item.get("addressZipcode"),
    ]
    addr_str = ", ".join(p for p in parts if isinstance(p, str) and p)
    if addr_str:
        out["address"] = addr_str

    # Beds / baths / sqft — try multiple field names.
    beds = _intish(item.get("bedrooms") or item.get("beds"))
    if beds is not None:
        out["beds"] = beds
    baths = _floatish(item.get("bathrooms") or item.get("baths"))
    if baths is not None:
        out["baths"] = baths
    sqft = _intish(
        item.get("livingArea") or item.get("area") or item.get("sqft")
    )
    if sqft is not None:
        out["sqft"] = sqft

    # Price — prefer asking, fall back to Zestimate. Strip $ and commas
    # if it came through as a string.
    raw_price = (
        item.get("price")
        or item.get("listPrice")
        or item.get("unformattedPrice")
        or item.get("zestimate")
    )
    if isinstance(raw_price, str):
        raw_price = raw_price.replace("$", "").replace(",", "").strip()
    price = _intish(raw_price)
    if price is not None:
        out["list_price"] = price

    # price_kind — Zillow's homeStatus tells us. Common values:
    # FOR_SALE, FOR_RENT, SOLD, OFF_MARKET, COMING_SOON, PENDING.
    status = item.get("homeStatus") or item.get("status")
    if isinstance(status, str):
        s = status.upper()
        if "RENT" in s:
            out["price_kind"] = "rent"
        else:
            # Default to "sale" for SOLD / OFF_MARKET / FOR_SALE / etc.
            # — Zestimate is a sale estimate, not a rent estimate.
            out["price_kind"] = "sale"

    # Listing URL — useful as a back-link.
    href = item.get("detailUrl") or item.get("hdpUrl") or item.get("url")
    if isinstance(href, str) and href:
        if href.startswith("/"):
            href = f"https://www.zillow.com{href}"
        out["listing_url"] = href

    # Photo — actor sometimes returns a CDN URL we can use as the
    # curb-appeal photo placeholder.
    photo = item.get("imgSrc") or item.get("hiResImageLink")
    if isinstance(photo, str) and photo:
        out["photo_url"] = photo

    return out


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
    # returns strings or null. Helpers shared with the Zillow mapper
    # at module level.
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
