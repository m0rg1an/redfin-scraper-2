from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Listing:
    mls_listing_id: Optional[str]
    address: Optional[str]
    city: Optional[str]
    price: Optional[int]
    home_sqft: Optional[int]
    lot_sqft: Optional[int]
    zoning: Optional[str]
    url: Optional[str]
    raw: Dict[str, Any]


def _safe_int(val: Any) -> Optional[int]:
    try:
        if val is None:
            return None
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return int(val)
        s = str(val).strip()
        if not s:
            return None
        # handle "$1,234,567" or "1,234" or "1.2M" (rough)
        s = s.replace("$", "").replace(",", "").lower()
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([mk])?", s)
        if m:
            num = float(m.group(1))
            mult = m.group(2)
            if mult == "m":
                num *= 1_000_000
            elif mult == "k":
                num *= 1_000
            return int(num)
        return int(float(s))
    except Exception:
        return None


def _extract_json_blobs_from_scripts(html: str) -> List[Dict[str, Any]]:
    """
    Redfin pages often contain embedded JSON within script tags.
    We try a few common patterns and return parsed JSON objects.
    """
    soup = BeautifulSoup(html, "html.parser")
    blobs: List[Dict[str, Any]] = []

    # 1) application/ld+json: sometimes has basic address/offer data
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (script.string or "").strip()
        if not txt:
            continue
        try:
            obj = json.loads(txt)
            if isinstance(obj, dict):
                blobs.append(obj)
            elif isinstance(obj, list):
                blobs.extend([x for x in obj if isinstance(x, dict)])
        except Exception:
            continue

    # 2) Any script tag that looks like it contains a JSON object with "homeData" / "payload" / "listing"
    # We do a conservative scan for the first {...} block.
    for script in soup.find_all("script"):
        txt = script.string
        if not txt:
            continue
        if "homeData" not in txt and "payload" not in txt and "listings" not in txt and "searchResults" not in txt:
            continue
        # find JSON object literal candidate
        candidates = _find_braced_json_candidates(txt)
        for cand in candidates:
            try:
                obj = json.loads(cand)
                if isinstance(obj, dict):
                    blobs.append(obj)
            except Exception:
                continue

    return blobs


def _find_braced_json_candidates(text: str, *, max_candidates: int = 6) -> List[str]:
    """
    Extract up to N JSON-looking {...} substrings from a larger script string.
    Uses a simple brace-matching scan. Not perfect but works for typical embedded JSON.
    """
    out: List[str] = []
    start_idxs: List[int] = []
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                if depth == 0:
                    start_idxs.append(i)
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_idxs:
                        start = start_idxs.pop()
                        cand = text[start : i + 1].strip()
                        if cand.startswith("{") and cand.endswith("}"):
                            out.append(cand)
                            if len(out) >= max_candidates:
                                return out
    return out


def _walk(obj: Any) -> Iterable[Any]:
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            for v in cur.values():
                stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                stack.append(v)


def _best_effort_extract_listings_from_json(blobs: List[Dict[str, Any]]) -> List[Listing]:
    """
    Attempt to find listing-ish dicts in JSON blobs. We look for dicts that contain
    keys commonly present in Redfin search result payloads.
    """
    listings: List[Listing] = []
    seen_urls: set[str] = set()

    for blob in blobs:
        for node in _walk(blob):
            if not isinstance(node, dict):
                continue
            keys = set(node.keys())
            if not (
                {"price", "url"}.issubset(keys)
                or {"streetLine", "city", "price"}.issubset(keys)
                or {"homeData", "url"}.issubset(keys)
            ):
                continue

            # normalize possible shapes
            url = node.get("url") or node.get("URL") or node.get("listingUrl")
            if isinstance(url, str) and url and url in seen_urls:
                continue

            price = _safe_int(node.get("price") or node.get("listPrice") or node.get("value"))
            street = node.get("streetLine") or node.get("address") or node.get("streetAddress")
            city = node.get("city")
            addr = None
            if isinstance(street, str):
                addr = street
            elif isinstance(street, dict):
                addr = street.get("streetAddress") or street.get("name")

            # sqft fields vary
            home_sqft = _safe_int(
                node.get("sqFt")
                or node.get("sqft")
                or node.get("livingArea")
                or node.get("livingAreaSqFt")
                or node.get("sqftValue")
            )
            lot_sqft = _safe_int(node.get("lotSqFt") or node.get("lotSize") or node.get("lotSizeSqFt"))

            mls_id = node.get("mlsId") or node.get("mlsListingId") or node.get("listingId") or node.get("id")
            if mls_id is not None and not isinstance(mls_id, str):
                mls_id = str(mls_id)

            zoning = node.get("zoning") or node.get("zoningCode") or None
            if zoning is not None and not isinstance(zoning, str):
                zoning = str(zoning)

            if not any([addr, city, price, home_sqft, lot_sqft, url]):
                continue

            if isinstance(url, str) and url:
                seen_urls.add(url)

            listings.append(
                Listing(
                    mls_listing_id=mls_id if isinstance(mls_id, str) else None,
                    address=addr if isinstance(addr, str) else None,
                    city=city if isinstance(city, str) else None,
                    price=price,
                    home_sqft=home_sqft,
                    lot_sqft=lot_sqft,
                    zoning=zoning if isinstance(zoning, str) else None,
                    url=url if isinstance(url, str) else None,
                    raw=node,
                )
            )

    return listings


def _extract_listings_from_html_cards(html: str, base_url: str) -> List[Listing]:
    """
    Fallback: scrape visible cards. This is less reliable (Redfin HTML changes),
    but can still capture address/price/link in many cases.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: List[Listing] = []

    # Try a few generic patterns
    # 1) anchor tags to /WA/... or /[state]/[city]/.../home/... patterns
    anchors = soup.find_all("a", href=True)
    for a in anchors:
        href = a.get("href")
        if not href or not isinstance(href, str):
            continue
        if "/home/" not in href and "/property/" not in href:
            continue
        full = urljoin(base_url, href)

        text = " ".join(a.get_text(" ", strip=True).split())
        if not text:
            continue
        # Attempt to locate surrounding price/address content
        parent = a.parent
        parent_text = ""
        if parent is not None:
            parent_text = " ".join(parent.get_text(" ", strip=True).split())
        blob = parent_text or text

        price = None
        m = re.search(r"\$(\d[\d,\.]*)([MK])?", blob)
        if m:
            price = _safe_int(m.group(0))

        addr = None
        # Address-like: starts with number and street name
        m2 = re.search(r"\b(\d{1,6}\s+[^,]{3,60})\b", blob)
        if m2:
            addr = m2.group(1).strip()

        listings.append(
            Listing(
                mls_listing_id=None,
                address=addr,
                city=None,
                price=price,
                home_sqft=None,
                lot_sqft=None,
                zoning=None,
                url=full,
                raw={"card_text": blob},
            )
        )

    # De-dupe by URL
    dedup: Dict[str, Listing] = {}
    for lst in listings:
        if lst.url:
            dedup.setdefault(lst.url, lst)
    return list(dedup.values())


def parse_redfin_search_results(html: str, *, base_url: str = "https://www.redfin.com") -> Tuple[List[Listing], Dict[str, Any]]:
    """
    Parse Redfin search HTML and return a list of Listing records.
    Strategy:
    - parse embedded JSON blobs in scripts (best)
    - fallback to simple HTML card scraping (worst)
    """
    blobs = _extract_json_blobs_from_scripts(html)
    listings = _best_effort_extract_listings_from_json(blobs)
    meta: Dict[str, Any] = {"json_blobs_found": len(blobs), "listings_from_json": len(listings)}

    if not listings:
        listings = _extract_listings_from_html_cards(html, base_url=base_url)
        meta["listings_from_html"] = len(listings)

    # Normalize URLs
    normalized: List[Listing] = []
    for l in listings:
        url = l.url
        if isinstance(url, str) and url.startswith("/"):
            url = urljoin(base_url, url)
        normalized.append(
            Listing(
                mls_listing_id=l.mls_listing_id,
                address=l.address,
                city=l.city,
                price=l.price,
                home_sqft=l.home_sqft,
                lot_sqft=l.lot_sqft,
                zoning=l.zoning,
                url=url,
                raw=l.raw,
            )
        )
    return normalized, meta

