from __future__ import annotations

import csv
import datetime as dt
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml
import requests

from http_client import fetch_html
from redfin_scraper import Listing, parse_redfin_search_results


DADU_KEYWORDS = [
    "dadu",
    "adu",
    "accessory dwelling",
    "alley access",
    "large lot",
    "subdivide",
    "build",
    "corner",
]


@dataclass(frozen=True)
class SearchDef:
    search_id: int
    category: str
    city: str
    description: str
    url: str


def load_searches(path: str) -> List[SearchDef]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    searches = data.get("searches") or []
    out: List[SearchDef] = []
    for s in searches:
        out.append(
            SearchDef(
                search_id=int(s["search_id"]),
                category=str(s["category"]),
                city=str(s.get("city", "")),
                description=str(s.get("description", "")),
                url=str(s["url"]),
            )
        )
    # ensure unique IDs
    ids = [s.search_id for s in out]
    if len(ids) != len(set(ids)):
        raise ValueError("search_id values must be unique in config/searches.yaml")
    return out


def _lower_text(*parts: Optional[str]) -> str:
    return " ".join([p for p in (parts or []) if isinstance(p, str)]).lower()


def passes_dadu_keyword_filter(search: SearchDef, listing: Listing) -> bool:
    if search.category != "DADU_play":
        return True
    haystack = _lower_text(search.description, listing.address, listing.city)
    # best-effort: some JSON nodes have remarks/description-like fields
    raw = listing.raw or {}
    for k in ("remarks", "publicRemarks", "description", "listingRemarks", "propertyDescription"):
        v = raw.get(k)
        if isinstance(v, str) and v:
            haystack += " " + v.lower()
    return any(kw in haystack for kw in DADU_KEYWORDS)


def compute_price_per_sqft(price: Optional[int], sqft: Optional[int]) -> Optional[float]:
    if not price or not sqft or sqft <= 0:
        return None
    return round(price / sqft, 2)


def compute_deal_rating(
    *,
    price: Optional[int],
    home_sqft: Optional[int],
    lot_sqft: Optional[int],
    home_ppsf: Optional[float],
    lot_ppsf: Optional[float],
    category: str,
) -> int:
    """
    Heuristic 0–100 deal score:
    - Lower home $/sqft is better
    - Bigger lots are better (esp for DADU/corner/land)
    - Lower price improves score slightly
    """
    score = 50.0

    if home_ppsf is not None:
        # 150 ppsf => very good, 400 => meh
        score += max(-20.0, min(25.0, (300.0 - home_ppsf) / 6.0))
    if lot_sqft:
        # lot size bonus up to ~25
        score += max(0.0, min(25.0, (lot_sqft - 3000) / 800.0))
    if lot_ppsf is not None:
        # cheaper land bonus
        score += max(-10.0, min(10.0, (10.0 - lot_ppsf) * 0.5))
    if price:
        score += max(-10.0, min(10.0, (450_000 - price) / 60_000))

    # category tweaks
    if category in ("DADU_play", "Corner_Lot", "FixerWithLand"):
        if lot_sqft and lot_sqft >= 6000:
            score += 5
    if category == "Fix_n_flip":
        if home_ppsf is not None and home_ppsf <= 250:
            score += 5

    return int(max(0, min(100, round(score))))


def daily_output_dir(root: str = "output", *, date: Optional[dt.date] = None) -> str:
    d = date or dt.date.today()
    return os.path.join(root, f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}")


def write_consolidated_csv(rows: List[Dict[str, Any]], path: str) -> None:
    fieldnames = [
        "mls_listing_id",
        "search_id",
        "search_category",
        "city",
        "address",
        "listing_price",
        "home_sqft",
        "lot_sqft",
        "zoning",
        "home_price_per_sqft",
        "lot_price_per_sqft",
        "deal_rating",
        "listing_url",
        "search_description",
        "search_url",
    ]

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def listing_to_row(search: SearchDef, listing: Listing) -> Dict[str, Any]:
    home_ppsf = compute_price_per_sqft(listing.price, listing.home_sqft)
    lot_ppsf = compute_price_per_sqft(listing.price, listing.lot_sqft)
    return {
        "mls_listing_id": listing.mls_listing_id,
        "search_id": search.search_id,
        "search_category": search.category,
        "city": search.city or listing.city,
        "address": listing.address,
        "listing_price": listing.price,
        "home_sqft": listing.home_sqft,
        "lot_sqft": listing.lot_sqft,
        "zoning": listing.zoning,
        "home_price_per_sqft": home_ppsf,
        "lot_price_per_sqft": lot_ppsf,
        "deal_rating": compute_deal_rating(
            price=listing.price,
            home_sqft=listing.home_sqft,
            lot_sqft=listing.lot_sqft,
            home_ppsf=home_ppsf,
            lot_ppsf=lot_ppsf,
            category=search.category,
        ),
        "listing_url": listing.url,
        "search_description": search.description,
        "search_url": search.url,
    }


def run_all(*, config_path: str = "config/searches.yaml") -> str:
    searches = load_searches(config_path)
    out_dir = daily_output_dir("output")
    out_path = os.path.join(out_dir, "all_listings.csv")

    consolidated: List[Dict[str, Any]] = []
    session = requests.Session()

    for s in searches:
        print(f"\n=== Search {s.search_id} | {s.category} | {s.city} ===")
        # small jitter helps avoid tripping simplistic rate limits (common in Codespaces)
        time.sleep(random.uniform(0.8, 2.5))
        try:
            result = fetch_html(s.url, session=session, max_attempts=8)
        except RuntimeError as exc:
            print(f"Fetch failed; skipping search_id={s.search_id}. {exc}")
            continue
        print(f"Fetched {result.status_code} in {result.elapsed_s:.2f}s")
        if result.status_code != 200:
            print("Skipping due to non-200 response.")
            continue

        listings, meta = parse_redfin_search_results(result.text)
        print(f"Parsed listings: {len(listings)} (meta: {meta})")

        kept = 0
        for l in listings:
            if not passes_dadu_keyword_filter(s, l):
                continue
            consolidated.append(listing_to_row(s, l))
            kept += 1
        print(f"Kept after filters: {kept}")

    write_consolidated_csv(consolidated, out_path)
    print(f"\nWrote {len(consolidated)} rows -> {out_path}")
    return out_path


if __name__ == "__main__":
    run_all()

