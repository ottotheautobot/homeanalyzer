"""Pull bed/bath/sqft/price/photo from a listing the user found
elsewhere. Two entry points:

1. **parse_listing_url(url)** — best-effort scrape. OG tags +
   JSON-LD + Haiku-text-fallback. Reality check: every major US
   real-estate site (Zillow / Redfin / Realtor / Homes / Trulia /
   Apartments) blocks server-side requests with 403/429 to fight
   scraping. URL parsing only works on the rare site that still
   serves OG tags to crawlers (smaller MLS sites, occasionally
   broker pages).

2. **parse_listing_image(image_bytes, mime)** — primary path.
   User screenshots the listing on their phone (where they're a
   real human in a real browser session) and uploads. Haiku Vision
   reads the screenshot and extracts the structured fields. Works
   around every anti-bot system because the request originates from
   the user's device, not our server. Costs ~$0.001 per screenshot.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import anthropic
import httpx

from app.config import settings

log = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.6 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

_MAX_HTML_BYTES = 2 * 1024 * 1024  # 2MB cap so an oversized page can't OOM us
_HAIKU_MODEL = "claude-haiku-4-5-20251001"


class ListingData(dict):
    """Fields any tier may set: address, list_price, price_kind, sqft,
    beds, baths, photo_url, listing_url, source."""


def _fetch_html(url: str, timeout: float = 10.0) -> str | None:
    """Fetch the listing page with a real-browser UA. Returns None on
    network errors / 4xx-5xx / oversized responses. Never raises."""
    try:
        with httpx.Client(
            headers=_BROWSER_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            r = client.get(url)
        if r.status_code >= 400:
            log.info("listing fetch %d for %s", r.status_code, url[:120])
            return None
        text = r.text
        if len(text) > _MAX_HTML_BYTES:
            text = text[:_MAX_HTML_BYTES]
        return text
    except Exception:
        log.info("listing fetch failed for %s", url[:120])
        return None


# OG tag matcher — handles attribute order variation + single/double quotes.
_OG_RE = re.compile(
    r"""<meta\s+(?=[^>]*?\bproperty\s*=\s*["']?(og:[a-z:_-]+)["']?)"""
    r"""[^>]*?\bcontent\s*=\s*["']([^"'>]*)["'][^>]*?/?>""",
    re.IGNORECASE,
)
_TWITTER_RE = re.compile(
    r"""<meta\s+(?=[^>]*?\bname\s*=\s*["']?(twitter:[a-z:_-]+)["']?)"""
    r"""[^>]*?\bcontent\s*=\s*["']([^"'>]*)["'][^>]*?/?>""",
    re.IGNORECASE,
)


def _parse_meta_tags(html: str) -> dict[str, str]:
    """Extract OG + Twitter card meta tags into a flat dict.
    Lowercases keys, normalizes HTML entities (&amp; -> &)."""
    out: dict[str, str] = {}
    for m in _OG_RE.finditer(html):
        key = m.group(1).lower()
        val = m.group(2)
        out.setdefault(key, _decode_entities(val))
    for m in _TWITTER_RE.finditer(html):
        key = m.group(1).lower()
        val = m.group(2)
        out.setdefault(key, _decode_entities(val))
    return out


def _decode_entities(s: str) -> str:
    return (
        s.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
    )


_JSONLD_RE = re.compile(
    r"""<script[^>]*?\btype\s*=\s*["']application/ld\+json["'][^>]*?>(.*?)</script>""",
    re.IGNORECASE | re.DOTALL,
)


def _parse_jsonld(html: str) -> list[dict[str, Any]]:
    """Find JSON-LD blocks and return a flat list of dicts (graphs are
    flattened). Quietly drops anything that doesn't parse."""
    out: list[dict[str, Any]] = []
    for m in _JSONLD_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                out.extend(g for g in graph if isinstance(g, dict))
            else:
                out.append(data)
        elif isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
    return out


# Schema.org @types we care about — listings, products, places.
_LISTING_TYPES = {
    "RealEstateListing",
    "SingleFamilyResidence",
    "House",
    "Apartment",
    "Residence",
    "Accommodation",
    "Place",
    "Product",  # Zillow tags listings as Product sometimes
    "Offer",
}


def _is_listing_node(node: dict) -> bool:
    t = node.get("@type")
    if isinstance(t, list):
        return any(x in _LISTING_TYPES for x in t)
    return isinstance(t, str) and t in _LISTING_TYPES


def _extract_from_jsonld(nodes: list[dict]) -> ListingData:
    out = ListingData()
    for node in nodes:
        if not _is_listing_node(node):
            continue
        # Address — Schema.org address can be a string or PostalAddress dict.
        addr = node.get("address")
        if isinstance(addr, str) and not out.get("address"):
            out["address"] = addr
        elif isinstance(addr, dict) and not out.get("address"):
            parts = [
                addr.get("streetAddress"),
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("postalCode"),
            ]
            joined = ", ".join(p for p in parts if isinstance(p, str) and p)
            if joined:
                out["address"] = joined
        # Bed / bath / sqft
        bed = (
            node.get("numberOfRooms")
            or node.get("numberOfBedrooms")
            or node.get("bedrooms")
        )
        if bed is not None and out.get("beds") is None:
            try:
                out["beds"] = int(float(bed))
            except (TypeError, ValueError):
                pass
        bath = (
            node.get("numberOfBathroomsTotal")
            or node.get("numberOfFullBathrooms")
            or node.get("bathrooms")
        )
        if bath is not None and out.get("baths") is None:
            try:
                out["baths"] = float(bath)
            except (TypeError, ValueError):
                pass
        sqft = node.get("floorSize")
        if isinstance(sqft, dict):
            sqft = sqft.get("value")
        if sqft is not None and out.get("sqft") is None:
            try:
                out["sqft"] = int(float(sqft))
            except (TypeError, ValueError):
                pass
        # Price — Offer / Product / Listing all use slightly different keys.
        price_node = node.get("offers") or node
        if isinstance(price_node, dict):
            price = price_node.get("price") or price_node.get("priceSpecification")
            if isinstance(price, dict):
                price = price.get("price")
            if price is not None and out.get("list_price") is None:
                try:
                    out["list_price"] = int(float(str(price).replace(",", "").replace("$", "")))
                except (TypeError, ValueError):
                    pass
        # Photo
        img = node.get("image")
        if isinstance(img, list) and img:
            img = img[0]
        if isinstance(img, dict):
            img = img.get("url") or img.get("contentUrl")
        if isinstance(img, str) and not out.get("photo_url"):
            out["photo_url"] = img
    return out


# Heuristic regex for "3 bd · 2 ba · 1500 sqft" patterns in OG description
# (very common — Zillow / Redfin / Realtor.com all do this).
_BEDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bd|bed|beds|bedroom)s?\b", re.I)
_BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ba|bath|baths|bathroom)s?\b", re.I)
_SQFT_RE = re.compile(
    r"([\d,]+)\s*(?:sq\s*ft|sqft|square\s*feet|square\s*foot)\b", re.I
)
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")


def _extract_from_meta(meta: dict[str, str]) -> ListingData:
    out = ListingData()
    if meta.get("og:image"):
        out["photo_url"] = meta["og:image"]
    elif meta.get("twitter:image"):
        out["photo_url"] = meta["twitter:image"]

    # Try to parse the description / title for bd/ba/sqft/price.
    blob = " ".join(
        v
        for k, v in meta.items()
        if k in ("og:title", "og:description", "twitter:description")
    )
    if not blob:
        return out

    if (m := _BEDS_RE.search(blob)) and out.get("beds") is None:
        try:
            out["beds"] = int(float(m.group(1)))
        except ValueError:
            pass
    if (m := _BATHS_RE.search(blob)) and out.get("baths") is None:
        try:
            out["baths"] = float(m.group(1))
        except ValueError:
            pass
    if (m := _SQFT_RE.search(blob)) and out.get("sqft") is None:
        try:
            out["sqft"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    if (m := _PRICE_RE.search(blob)) and out.get("list_price") is None:
        try:
            out["list_price"] = int(float(m.group(1).replace(",", "")))
        except ValueError:
            pass

    # Address often appears in og:title verbatim ("123 Main St,
    # Plantation FL | Zillow"). Take the part before the first " | ".
    title = meta.get("og:title") or ""
    if title and out.get("address") is None:
        head = title.split(" | ")[0].split(" - ")[0].strip()
        # Heuristic: looks like an address if it has digits + a comma.
        if any(c.isdigit() for c in head) and "," in head:
            out["address"] = head

    return out


_HAIKU_TOOL = {
    "name": "record_listing",
    "description": "Record the structured fields extracted from a real-estate listing page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "address": {"type": ["string", "null"]},
            "list_price": {
                "type": ["integer", "null"],
                "description": "USD, integer dollars. Strip $ and commas.",
            },
            "price_kind": {
                "type": ["string", "null"],
                "enum": ["sale", "rent", None],
                "description": "Whether this is a for-sale price or a monthly rent.",
            },
            "sqft": {"type": ["integer", "null"]},
            "beds": {"type": ["integer", "null"]},
            "baths": {
                "type": ["number", "null"],
                "description": "May be a half-bath like 2.5",
            },
        },
        "required": [
            "address",
            "list_price",
            "price_kind",
            "sqft",
            "beds",
            "baths",
        ],
    },
}


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str, max_chars: int = 12000) -> str:
    # Drop scripts + styles entirely, then strip remaining tags. Cap
    # the result to keep token cost predictable on bloated pages.
    cleaned = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = _TAG_RE.sub(" ", cleaned)
    text = _decode_entities(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


def _extract_with_haiku(html: str) -> ListingData:
    if not settings.anthropic_api_key:
        return ListingData()
    text = _strip_html(html)
    if len(text) < 50:
        return ListingData()
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=512,
            tools=[_HAIKU_TOOL],
            tool_choice={"type": "tool", "name": "record_listing"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract listing fields from this real-estate page. "
                        "If a field isn't visible or you're unsure, return null.\n\n"
                        + text
                    ),
                }
            ],
        )
        for block in resp.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and block.name == "record_listing"
            ):
                data = block.input or {}
                out = ListingData()
                for k in ("address", "price_kind"):
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        out[k] = v.strip()
                for k in ("list_price", "sqft", "beds"):
                    v = data.get(k)
                    if isinstance(v, (int, float)) and v >= 0:
                        out[k] = int(v)
                if isinstance(data.get("baths"), (int, float)) and data["baths"] >= 0:
                    out["baths"] = float(data["baths"])
                return out
    except Exception:
        log.exception("Haiku listing extraction failed")
    return ListingData()


def _looks_complete(d: dict) -> bool:
    # We have enough to skip the LLM fallback if at least beds AND
    # baths AND list_price came through — the most-asked-for fields.
    return all(d.get(k) is not None for k in ("beds", "baths", "list_price"))


def parse_listing_image(
    image_bytes: bytes,
    mime: str,
    target_address: str | None = None,
) -> ListingData:
    """Read a listing screenshot/photo via Haiku Vision. Primary path
    because URL scraping is broadly blocked. The user screenshots the
    listing on their phone and uploads — the request originates from
    their device, so anti-bot rules don't apply.

    target_address (optional) is passed into the prompt so Haiku knows
    WHICH listing to focus on when the screenshot is a search-results
    page with multiple cards. Without it Haiku may guess wrong.

    Returns the same shape as parse_listing_url. `source` will be
    `"image"` on success, `"image_failed"` on any error so the caller
    can show a helpful message rather than a generic 500."""
    out = ListingData()
    out["source"] = "image_failed"

    if not settings.anthropic_api_key:
        return out
    if not image_bytes:
        return out

    # Anthropic vision accepts image/jpeg, image/png, image/gif, image/webp.
    safe_mime = mime if mime in ("image/jpeg", "image/png", "image/gif", "image/webp") else "image/jpeg"

    target_clause = (
        f"\n\nIMPORTANT: We're looking for the property at {target_address}. "
        "If the page is a search-results list with multiple cards, find the "
        "one whose address best matches that address and extract from it. "
        "Ignore other cards."
        if target_address
        else ""
    )
    prompt_text = (
        "This is a screenshot of a real-estate page. It might be a single "
        "listing detail page, a search-results list with one or more cards, "
        "or a captcha / login / 'no results' page. "
        "If listing data is visible, extract the property fields. "
        "If a field isn't visible or you're unsure, return null. "
        "The address should be the property's full address "
        "(street, city, state, zip if visible). For price_kind: 'sale' "
        "if this is a for-sale listing, 'rent' if it's a monthly rent."
        + target_clause
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=512,
            tools=[_HAIKU_TOOL],
            tool_choice={"type": "tool", "name": "record_listing"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": safe_mime,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
        )
    except Exception:
        log.exception("vision listing extraction failed")
        return out

    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and block.name == "record_listing"
        ):
            data = block.input or {}
            log.info("vision raw extracted: %s", data)
            for k in ("address", "price_kind"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    out[k] = v.strip()
            for k in ("list_price", "sqft", "beds"):
                v = data.get(k)
                if isinstance(v, (int, float)) and v >= 0:
                    out[k] = int(v)
            if isinstance(data.get("baths"), (int, float)) and data["baths"] >= 0:
                out["baths"] = float(data["baths"])
            if any(out.get(k) is not None for k in ("address", "list_price", "beds", "baths", "sqft")):
                out["source"] = "image"
            break

    return out


def parse_listing_url(url: str) -> ListingData:
    """Top-level entry. Returns whatever we could extract; missing
    fields just stay absent. Caller pre-fills the form with what's
    there and the user fills in the rest."""
    out = ListingData()
    out["listing_url"] = url
    out["source"] = "fetch_failed"

    html = _fetch_html(url)
    if not html:
        return out

    # Tier 1: JSON-LD (most reliable when present).
    nodes = _parse_jsonld(html)
    jsonld = _extract_from_jsonld(nodes)
    out.update({k: v for k, v in jsonld.items() if v is not None})
    if jsonld:
        out["source"] = "jsonld"

    # Tier 2: OG / Twitter meta tags (fills in what JSON-LD missed).
    meta = _parse_meta_tags(html)
    meta_out = _extract_from_meta(meta)
    for k, v in meta_out.items():
        if out.get(k) is None and v is not None:
            out[k] = v
    if meta_out and out["source"] == "fetch_failed":
        out["source"] = "meta"

    if _looks_complete(out):
        return out

    # Tier 3: Haiku over cleaned page text. Catches sites that don't
    # use OG/JSON-LD or hide fields behind JS.
    haiku_out = _extract_with_haiku(html)
    for k, v in haiku_out.items():
        if out.get(k) is None and v is not None:
            out[k] = v
    if haiku_out:
        out["source"] = "haiku"

    return out
