"""Tests for pipeline.lib.clean_dvf -- pure logic only, no DuckDB/network.

Written before pipeline/02_clean_dvf.py (TDD, per CLAUDE.md).
"""

from pipeline.lib.clean_dvf import (
    EXCLUDED_ZERO_PRICE,
    EXCLUDED_ZERO_SURFACE,
    KEPT,
    ExclusionStats,
    build_geocoding_query,
    classify_row,
    compose_address,
    parse_french_decimal,
    process_rows,
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


def _raw_row(**overrides):
    """Une ligne DVF brute (dict, colonnes nommees par load_raw_rows) valide par defaut."""
    base = {
        "identifiant_document": "doc1",
        "no_disposition": "1",
        "date_mutation": "2022-05-01",
        "nature_mutation": "Vente",
        "valeur_fonciere": "273400,00",
        "no_voie": "21",
        "btq": None,
        "type_voie": "RUE",
        "voie": "PETRICOT",
        "code_postal": "64200",
        "commune": "BIARRITZ",
        "code_insee": "64122",
        "type_local": "Appartement",
        "nombre_pieces_principales": "3",
        "surface_reelle_bati": "51",
    }
    base.update(overrides)
    return base


class TestProcessRows:
    """process_rows : boucle de nettoyage DVF (miroir de clean_dpe.process_records).
    Parse prix/surface, classe, compose+normalise l'adresse des lignes retenues.
    Lignes exclues comptees, jamais retournees (CLAUDE.md)."""

    def test_kept_row_has_output_schema(self):
        rows, stats = process_rows([_raw_row()])

        assert stats == ExclusionStats(excluded_zero_price=0, excluded_zero_surface=0)
        assert len(rows) == 1
        assert rows[0] == {
            "identifiant_document": "doc1",
            "no_disposition": "1",
            "date_mutation": "2022-05-01",
            "nature_mutation": "Vente",
            "code_insee": "64122",
            "commune": "BIARRITZ",
            "code_postal": "64200",
            "adresse_brute": "21 RUE PETRICOT",
            "adresse_normalisee": "21 RUE PETRICOT",
            "type_local": "Appartement",
            "nombre_pieces_principales": "3",
            "surface": 51.0,
            "prix": 273400.0,
        }

    def test_excluded_zero_price_counted_not_returned(self):
        rows, stats = process_rows([_raw_row(valeur_fonciere="0,00")])
        assert rows == []
        assert stats == ExclusionStats(excluded_zero_price=1, excluded_zero_surface=0)

    def test_excluded_zero_surface_counted_not_returned(self):
        rows, stats = process_rows([_raw_row(surface_reelle_bati="0")])
        assert rows == []
        assert stats == ExclusionStats(excluded_zero_price=0, excluded_zero_surface=1)

    def test_missing_price_and_surface_reports_price_first(self):
        rows, stats = process_rows([_raw_row(valeur_fonciere=None, surface_reelle_bati=None)])
        assert rows == []
        assert stats == ExclusionStats(excluded_zero_price=1, excluded_zero_surface=0)

    def test_address_composed_and_normalized(self):
        rows, _ = process_rows(
            [_raw_row(no_voie="1", btq="B", type_voie="allée", voie="docteur robert lafon")]
        )
        assert rows[0]["adresse_brute"] == "1 B allée docteur robert lafon"
        assert rows[0]["adresse_normalisee"] == "1 B ALLEE DOCTEUR ROBERT LAFON"

    def test_empty_input(self):
        rows, stats = process_rows([])
        assert rows == []
        assert stats == ExclusionStats(excluded_zero_price=0, excluded_zero_surface=0)

    def test_mixed_batch_kept_count_is_output_length(self):
        rows, stats = process_rows(
            [
                _raw_row(identifiant_document="a"),
                _raw_row(identifiant_document="b", valeur_fonciere="0"),
                _raw_row(identifiant_document="c"),
                _raw_row(identifiant_document="d", surface_reelle_bati=None),
            ]
        )
        assert [r["identifiant_document"] for r in rows] == ["a", "c"]
        assert stats == ExclusionStats(excluded_zero_price=1, excluded_zero_surface=1)
