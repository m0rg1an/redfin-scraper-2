# Lookups

Drop supplemental lookup files here (CSV) to enrich the daily output.

## Parcel lookup

To add `tax_parcel_number` to scraped listings, add one or more CSV files under:

- `lookups/parcel/`

Each CSV should include these headers (case-insensitive):

- `taxparcelnumber`
- `zipcode`
- `site_address`

Example file: `lookups/parcel/parcel_lookup.csv`:

```csv
taxparcelnumber,zipcode,site_address
1234567890,98404,1216 E 70th St
9876543210,98444,1627 Hume St S
```

Matching is done by `(zipcode, normalized site_address)`. If you add multiple files,
they are merged; matches are primarily by **normalized address**, with zipcode allowed to differ by **±4** (closest zip wins).

## Location value lookup

If you have a separate “location value” file keyed by tax parcel number, add one or more CSV files under:

- `lookups/location/`
- `lookups/Location/` (also supported)

Each CSV should include:

- `taxparcelnumber`
- a value column:
  - preferred: `location_value`
  - fallback: `value`
  - or (if the file only has one non-tax column) that column is used as the value

The runner will write `location_value` into the daily output CSV when a parcel match is found.

