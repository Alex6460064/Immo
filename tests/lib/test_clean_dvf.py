"""Tests for pipeline.lib.clean_dvf -- pure logic only, no DuckDB/network.

Written before pipeline/02_clean_dvf.py (TDD, per CLAUDE.md).
"""

from pipeline.lib.clean_dvf import (
    EXCLUDED_ZERO_PRICE,
    EXCLUDED_ZERO_SURFACE,
    KEPT,
    build_geocoding_query,
    classify_row,
    compose_address,
    parse_french_decimal,
)


class TestParseFrenchDecimal:
    def test_comma_decimal(self):
        assert parse_french_decimal("273400,00") == 273400.0

    def test_zero_comma_decimal(self):
        assert parse_french_decimal("0,00") == 0.0

    def test_plain_integer_string(self):
        # "Surface reelle bati" style: no comma at all.
        assert parse_french_decimal("51") == 51.0

    def test_zero_integer_string(self):
        assert parse_french_decimal("0") == 0.0

    def test_none_is_none(self):
        assert parse_french_decimal(None) is None

    def test_empty_string_is_none(self):
        assert parse_french_decimal("") is None

    def test_whitespace_only_is_none(self):
        assert parse_french_decimal("   ") is None

    def test_unparseable_string_is_none(self):
        assert parse_french_decimal("abc") is None

    def test_surrounding_whitespace_stripped(self):
        assert parse_french_decimal("  1234,50  ") == 1234.50


class TestComposeAddress:
    def test_all_parts_present(self):
        assert compose_address("21", None, "RUE", "PETRICOT") == "21 RUE PETRICOT"

    def test_btq_present(self):
        assert compose_address("1", "B", "RUE", "DU JAIZQUIBEL") == "1 B RUE DU JAIZQUIBEL"

    def test_missing_no_voie(self):
        # Locality-only address, e.g. "BOURG EST" with no street number.
        assert compose_address(None, None, None, "BOURG EST") == "BOURG EST"

    def test_missing_type_voie(self):
        assert compose_address("5", None, None, "PLACIS") == "5 PLACIS"

    def test_all_none(self):
        assert compose_address(None, None, None, None) == ""

    def test_empty_strings_treated_like_none(self):
        assert compose_address("21", "", "RUE", "PETRICOT") == "21 RUE PETRICOT"

    def test_parts_are_stripped(self):
        assert compose_address(" 21 ", None, " RUE ", " PETRICOT ") == "21 RUE PETRICOT"


class TestClassifyRow:
    def test_kept_when_price_and_surface_positive(self):
        assert classify_row(273400.0, 51.0) == KEPT

    def test_excluded_zero_price_when_price_is_zero(self):
        assert classify_row(0.0, 51.0) == EXCLUDED_ZERO_PRICE

    def test_excluded_zero_price_when_price_is_none(self):
        assert classify_row(None, 51.0) == EXCLUDED_ZERO_PRICE

    def test_excluded_zero_surface_when_surface_is_zero(self):
        assert classify_row(273400.0, 0.0) == EXCLUDED_ZERO_SURFACE

    def test_excluded_zero_surface_when_surface_is_none(self):
        assert classify_row(273400.0, None) == EXCLUDED_ZERO_SURFACE

    def test_both_zero_reports_price_first(self):
        assert classify_row(0.0, 0.0) == EXCLUDED_ZERO_PRICE

    def test_both_none_reports_price_first(self):
        assert classify_row(None, None) == EXCLUDED_ZERO_PRICE


class TestBuildGeocodingQuery:
    def test_composes_address_postcode_commune(self):
        row = {
            "adresse_brute": "21 RUE PETRICOT",
            "code_postal": "64200",
            "commune": "BIARRITZ",
        }
        assert build_geocoding_query(row) == "21 RUE PETRICOT 64200 BIARRITZ"

    def test_missing_postal_code_skipped(self):
        row = {"adresse_brute": "21 RUE PETRICOT", "code_postal": None, "commune": "BIARRITZ"}
        assert build_geocoding_query(row) == "21 RUE PETRICOT BIARRITZ"

    def test_missing_commune_skipped(self):
        row = {"adresse_brute": "21 RUE PETRICOT", "code_postal": "64200", "commune": None}
        assert build_geocoding_query(row) == "21 RUE PETRICOT 64200"

    def test_no_address_returns_none(self):
        row = {"adresse_brute": "", "code_postal": "64200", "commune": "BIARRITZ"}
        assert build_geocoding_query(row) is None

    def test_none_address_returns_none(self):
        row = {"adresse_brute": None, "code_postal": "64200", "commune": "BIARRITZ"}
        assert build_geocoding_query(row) is None

    def test_whitespace_collapsed(self):
        row = {"adresse_brute": "21  RUE   PETRICOT", "code_postal": "64200", "commune": "BIARRITZ"}
        assert build_geocoding_query(row) == "21 RUE PETRICOT 64200 BIARRITZ"
