from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")

# Very small normalization map (not exhaustive, just helps common matches)
_ABBREV = {
    "STREET": "ST",
    "ST": "ST",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "ROAD": "RD",
    "RD": "RD",
    "DRIVE": "DR",
    "DR": "DR",
    "LANE": "LN",
    "LN": "LN",
    "COURT": "CT",
    "CT": "CT",
    "PLACE": "PL",
    "PL": "PL",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "PARKWAY": "PKWY",
    "PKWY": "PKWY",
    "NORTH": "N",
    "N": "N",
    "SOUTH": "S",
    "S": "S",
    "EAST": "E",
    "E": "E",
    "WEST": "W",
    "W": "W",
}


def normalize_zip(zipcode: Optional[str]) -> str:
    if not zipcode:
        return ""
    s = str(zipcode).strip()
    m = re.search(r"\b(\d{5})\b", s)
    return m.group(1) if m else ""


def zip_to_int(zipcode: Optional[str]) -> Optional[int]:
    z = normalize_zip(zipcode)
    if not z:
        return None
    try:
        return int(z)
    except Exception:
        return None


def normalize_address(addr: Optional[str]) -> str:
    if not addr:
        return ""
    s = str(addr).strip().upper()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    if not s:
        return ""

    parts = []
    for token in s.split(" "):
        parts.append(_ABBREV.get(token, token))
    return " ".join(parts)


@dataclass(frozen=True)
class ParcelLookup:
    # normalized_address -> list of (zip_int, parcel) in stable order
    by_address: Dict[str, List[Tuple[Optional[int], str]]]

    def find(
        self,
        *,
        zipcode: Optional[str],
        site_address: Optional[str],
        zip_tolerance: int = 4,
    ) -> Optional[str]:
        """
        Match on normalized address, and accept zipcode mismatches within +/- zip_tolerance.
        If multiple parcels match, choose the closest zip; ties keep stable file order.
        """
        a = normalize_address(site_address)
        if not a:
            return None

        candidates = self.by_address.get(a) or []
        if not candidates:
            return None

        z_int = zip_to_int(zipcode)
        if z_int is None:
            # No listing zip => return first candidate (stable order)
            return candidates[0][1]

        best: Optional[Tuple[int, str]] = None  # (distance, parcel)
        for cand_zip, parcel in candidates:
            if cand_zip is None:
                continue
            dist = abs(cand_zip - z_int)
            if dist <= zip_tolerance:
                if best is None or dist < best[0]:
                    best = (dist, parcel)
        if best is not None:
            return best[1]

        # If nothing is within tolerance, don't match.
        return None


def _iter_csv_files(root_dir: str) -> Iterable[str]:
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.lower().endswith(".csv") and not fn.lower().endswith(".csv.example"):
                yield os.path.join(dirpath, fn)


def load_parcel_lookup(*, lookups_dir: str = "lookups/parcel") -> ParcelLookup:
    """
    Loads all CSV files in lookups/parcel (excluding *.csv.example) and builds a mapping:
      normalized_site_address -> [(zipcode_int, taxparcelnumber), ...]
    """
    mapping: Dict[str, List[Tuple[Optional[int], str]]] = {}
    if not os.path.isdir(lookups_dir):
        return ParcelLookup(by_address=mapping)

    for path in sorted(_iter_csv_files(lookups_dir)):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue

            # Case-insensitive header access
            field_map = {name.lower().strip(): name for name in reader.fieldnames}
            need = {"taxparcelnumber", "zipcode", "site_address"}
            if not need.issubset(field_map):
                # Ignore unrelated CSV files in the folder
                continue

            for row in reader:
                parcel = (row.get(field_map["taxparcelnumber"]) or "").strip()
                zipcode = (row.get(field_map["zipcode"]) or "").strip()
                addr = (row.get(field_map["site_address"]) or "").strip()
                if not parcel:
                    continue
                a = normalize_address(addr)
                z = zip_to_int(zipcode)
                if not a:
                    continue
                # Keep stable order by filename and file order; allow multiple zips for same address.
                mapping.setdefault(a, []).append((z, parcel))

    return ParcelLookup(by_address=mapping)

