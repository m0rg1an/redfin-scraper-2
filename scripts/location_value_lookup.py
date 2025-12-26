from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Dict, Iterable, Optional


def normalize_taxparcelnumber(val: Optional[str]) -> str:
    if not val:
        return ""
    return str(val).strip()


def _iter_csv_files(root_dir: str) -> Iterable[str]:
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.lower().endswith(".csv") and not fn.lower().endswith(".csv.example"):
                yield os.path.join(dirpath, fn)


@dataclass(frozen=True)
class LocationValueLookup:
    # taxparcelnumber -> location_value
    by_parcel: Dict[str, str]

    def find(self, taxparcelnumber: Optional[str]) -> Optional[str]:
        k = normalize_taxparcelnumber(taxparcelnumber)
        if not k:
            return None
        return self.by_parcel.get(k)


def load_location_value_lookup(
    *,
    lookups_dirs: Iterable[str] = ("lookups/location", "lookups/Location"),
) -> LocationValueLookup:
    """
    Loads all CSV files in lookups/location (excluding *.csv.example) and builds:
      taxparcelnumber -> location_value
    """
    mapping: Dict[str, str] = {}

    dirs = [d for d in lookups_dirs if isinstance(d, str) and os.path.isdir(d)]
    if not dirs:
        return LocationValueLookup(by_parcel=mapping)

    paths: list[str] = []
    for d in dirs:
        paths.extend(list(_iter_csv_files(d)))

    for path in sorted(set(paths)):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue

            # Case-insensitive header access
            field_map = {name.lower().strip(): name for name in reader.fieldnames}
            if "taxparcelnumber" not in field_map:
                continue

            # Determine which column contains the location value
            value_col: Optional[str] = None
            for preferred in ("location_value", "value"):
                if preferred in field_map:
                    value_col = field_map[preferred]
                    break

            if value_col is None:
                # If there's exactly one non-tax column, use it.
                non_tax = [n for n in reader.fieldnames if n != field_map["taxparcelnumber"]]
                if len(non_tax) == 1:
                    value_col = non_tax[0]
                else:
                    # Can't infer; ignore this file
                    continue

            for row in reader:
                parcel = normalize_taxparcelnumber(row.get(field_map["taxparcelnumber"]))
                if not parcel:
                    continue
                value = (row.get(value_col) or "").strip()
                if not value:
                    continue
                # First match wins across files (stable filename sort)
                mapping.setdefault(parcel, value)

    return LocationValueLookup(by_parcel=mapping)

