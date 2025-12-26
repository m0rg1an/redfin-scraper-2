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

