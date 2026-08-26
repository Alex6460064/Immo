"""Pure logic for cleaning raw DVF (DGFiP) mutations before the DVF x DPE join.

No I/O, no DuckDB connection opened here (see CLAUDE.md architecture convention) --
`pipeline/02_clean_dvf.py` wires these functions to the raw parquet files via DuckDB
Python UDFs and writes the cleaned output.

Design choices (documented per CLAUDE.md -- no silent assumptions):

- Surface field: DVF has two distinct surface concepts -- "Surface reelle bati"
  (the building's real/legal surface, filled for most built-property sales) and
  "Surface Carrez du 1er lot".."5eme lot" (Carrez law surface per co-ownership lot,
  mostly NULL, only relevant for apartments sold in a co-ownership). This module
  uses "Surface reelle bati" as the primary surface field -- it is the field
  conventionally used for DVF price/m2 analysis and is populated far more
  consistently across the targeted communes (checked live against the cached raw
  data in data/raw/ on this ticket: Carrez surface is NULL almost everywhere,
  "Surface reelle bati" is NULL/'0' on a small minority of rows). The I/O script
  reads only this column; Carrez surfaces are not used.

- Row vs. mutation granularity: one DVF mutation can span multiple raw rows (one
  per disposition/lot, sharing the same "No disposition" + date + price). This
  module classifies at row granularity, matching the raw data's own granularity --
  no aggregation/deduplication is performed here (that would be a separate,
  explicitly-scoped decision, not part of this ticket).

- Zero vs. missing: a NULL/empty price or surface is treated the same as a
  literal "0" -- both make the row unusable for price/m2 analysis, and CLAUDE.md
  requires documenting rather than silently dropping edge cases rather than
  silently keeping them as valid. When both price and surface are missing/zero,
  the row is reported as `EXCLUDED_ZERO_PRICE` (price is checked first) -- an
  arbitrary but deterministic and documented ordering.
"""

from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")

KEPT = "kept"
EXCLUDED_ZERO_PRICE = "excluded_zero_price"
EXCLUDED_ZERO_SURFACE = "excluded_zero_surface"


def parse_french_decimal(raw: str | None) -> float | None:
    """Parse a DGFiP numeric field: French decimal comma (e.g. '273400,00').

    Also handles plain integer strings with no comma (e.g. DVF's
    "Surface reelle bati", which uses this same raw text-number convention).
    Returns None for NULL, empty/whitespace-only, or unparseable input -- never
    raises, since raw DVF rows are allowed to have missing numeric fields.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def compose_address(
    no_voie: str | None,
    btq: str | None,
    type_voie: str | None,
    voie: str | None,
) -> str:
    """Compose the DGFiP address columns into one free-form address string.

    DVF splits an address across "No voie" (street number), "B/T/Q"
    (bis/ter/quater, often NULL), "Type de voie" (e.g. 'RUE') and "Voie" (street
    name). Missing/blank parts are skipped rather than inserted as literal
    "None"/empty tokens; the remaining parts are joined with a single space, in
    DGFiP's own column order. The result is meant to be fed to
    `normalize_address` next, not used as a final address on its own.
    """
    parts = [p.strip() for p in (no_voie, btq, type_voie, voie) if p and p.strip()]
    return " ".join(parts)


def classify_row(price: float | None, surface: float | None) -> str:
    """Classify a parsed DVF row: kept / excluded_zero_price / excluded_zero_surface.

    See module docstring for the NULL-as-zero and price-checked-first design
    decisions.
    """
    if price is None or price == 0:
        return EXCLUDED_ZERO_PRICE
    if surface is None or surface == 0:
        return EXCLUDED_ZERO_SURFACE
    return KEPT


def build_geocoding_query(row: dict) -> str | None:
    """Build the address string submitted to the BAN API for geocoding.

    Enriched with postcode + commune (same design decision as DPE's
    `pipeline.lib.clean_dpe.build_geocoding_query`, see that module's docstring):
    the street address alone (`adresse_brute`) is often ambiguous across communes
    (e.g. "Rue de la Paix" exists in several), so the BAN query adds the postal
    code and commune name -- distinct from `adresse_normalisee`, which stays a
    clean street-only key for the DVF x DPE text-match join. Returns None if
    `adresse_brute` is empty -- nothing to geocode for that row.
    """
    adresse_brute = (row.get("adresse_brute") or "").strip()
    if not adresse_brute:
        return None

    parts = [_WHITESPACE_RE.sub(" ", adresse_brute).strip()]

    code_postal = (row.get("code_postal") or "").strip() if row.get("code_postal") else None
    if code_postal:
        parts.append(code_postal)

    commune = (row.get("commune") or "").strip()
    if commune:
        parts.append(commune)

    return " ".join(parts)
