# redfin-searches

Scrape multiple Redfin search result pages and produce **one consolidated CSV per day**.

## Repo structure

- `config/searches.yaml`: editable list of searches (add rows; no code changes)
- `scripts/run_all_searches.py`: runs all searches and writes daily output
- `scripts/redfin_scraper.py`: HTML scraper + embedded JSON parser (requests + BeautifulSoup)
- `scripts/http_client.py`: retries/backoff + rotating user agents
- `output/YYYY/MM/DD/all_listings.csv`: consolidated output

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python scripts/run_all_searches.py
```

## Add or edit searches

1. Open `config/searches.yaml`
2. Add a new entry under `searches:` with:
   - `search_id` (must be unique)
   - `category` (e.g. `DADU_play`, `Fix_n_flip`, `CheapLargeHomes`, `FixerWithLand`, `Corner_Lot`)
   - `city`
   - `description`
   - `url`
3. Re-run `python scripts/run_all_searches.py`

## Output columns

The consolidated CSV includes (when available from Redfin HTML):

- `mls_listing_id`
- `search_id`
- `search_category`
- `city`
- `address`
- `listing_price`
- `home_sqft`
- `lot_sqft`
- `zoning`
- `home_price_per_sqft`
- `lot_price_per_sqft`
- `deal_rating` (0–100 heuristic score)
- `listing_url`

## Notes on bot detection

Redfin may rate-limit or block scraping. This project:

- Rotates user agents
- Retries with exponential backoff on 403/429/5xx
- Parses listings from embedded JSON in HTML when present

If you still get blocked, reduce frequency, add longer delays, and run from a stable IP.

## About missing fields

Some fields you want (like **MLS listing id** and **zoning**) are not always present on Redfin search result pages. This scraper fills them when they appear in the embedded page JSON, otherwise leaves them blank.

## Codespaces note

If you run this from GitHub Codespaces and immediately see HTTP 403/405/429 errors, Redfin is likely blocking the Codespaces IP range. Use a proxy (via `HTTPS_PROXY` / `HTTP_PROXY`) or run from a non-GitHub-hosted environment.

