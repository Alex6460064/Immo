"""Tests for pipeline.lib.clean_dpe -- pure logic (no I/O, no network) for cleaning DPE
ADEME records before geocoding: post-reform date cutoff classification, the address string
submitted to BAN for geocoding, and building the cleaned output record.

Written before the implementation (TDD, per CLAUDE.md).
"""

from pipeline.lib.clean_dpe import (
    POST_REFORM_CUTOFF,
    build_clean_record,
    build_geocoding_query,
    classify_dpe_date,
    is_post_reform,
    process_records,
)


class TestClassifyDpeDate:
    def test_cutoff_constant_is_reform_date(self):
        assert POST_REFORM_CUTOFF == "2021-07-01"

    def test_exact_cutoff_date_is_post_reform(self):
        assert classify_dpe_date("2021-07-01") == "post_reform"

    def test_day_before_cutoff_is_pre_reform(self):
        assert classify_dpe_date("2021-06-30") == "pre_reform"

    def test_day_after_cutoff_is_post_reform(self):
        assert classify_dpe_date("2021-07-02") == "post_reform"

    def test_well_after_cutoff_is_post_reform(self):
        assert classify_dpe_date("2026-01-12") == "post_reform"

    def test_well_before_cutoff_is_pre_reform(self):
        assert classify_dpe_date("2015-03-10") == "pre_reform"

    def test_none_is_missing_date(self):
        assert classify_dpe_date(None) == "missing_date"

    def test_empty_string_is_missing_date(self):
        assert classify_dpe_date("") == "missing_date"

    def test_malformed_separator_is_invalid_date(self):
        assert classify_dpe_date("2021/07/01") == "invalid_date"

    def test_non_date_text_is_invalid_date(self):
        assert classify_dpe_date("not-a-date") == "invalid_date"

    def test_truncated_date_is_invalid_date(self):
        assert classify_dpe_date("2021-07") == "invalid_date"

    def test_impossible_calendar_date_is_invalid_date(self):
        assert classify_dpe_date("2021-13-40") == "invalid_date"


class TestIsPostReform:
    def test_true_on_cutoff(self):
        assert is_post_reform("2021-07-01") is True

    def test_false_before_cutoff(self):
        assert is_post_reform("2021-06-30") is False

    def test_false_on_missing(self):
        assert is_post_reform(None) is False

    def test_false_on_invalid(self):
        assert is_post_reform("bogus") is False


class TestBuildGeocodingQuery:
    def test_combines_street_postal_commune(self):
        record = {
            "adresse_brut": "27 Allée Docteur Robert Lafon",
            "code_postal_brut": 64100,
            "nom_commune_brut": "BAYONNE",
        }
        assert build_geocoding_query(record) == "27 Allée Docteur Robert Lafon 64100 BAYONNE"

    def test_missing_address_returns_none(self):
        record = {"code_postal_brut": 64100, "nom_commune_brut": "BAYONNE"}
        assert build_geocoding_query(record) is None

    def test_blank_address_returns_none(self):
        record = {
            "adresse_brut": "   ",
            "code_postal_brut": 64100,
            "nom_commune_brut": "BAYONNE",
        }
        assert build_geocoding_query(record) is None

    def test_missing_postal_and_commune_falls_back_to_street_only(self):
        record = {"adresse_brut": "12 Rue de la Bidassoa"}
        assert build_geocoding_query(record) == "12 Rue de la Bidassoa"

    def test_uses_brut_fields_not_ban_fields(self):
        """Deliberately ignores adresse_ban / code_postal_ban / nom_commune_ban -- this
        project re-geocodes independently rather than reusing ADEME's own BAN join."""
        record = {
            "adresse_brut": "12 Rue de la Bidassoa",
            "code_postal_brut": 64100,
            "nom_commune_brut": "BAYONNE",
            "adresse_ban": "12 Rue de la Bidassoa 64100 Bayonne",
            "code_postal_ban": "64100",
            "nom_commune_ban": "Bayonne",
        }
        assert build_geocoding_query(record) == "12 Rue de la Bidassoa 64100 BAYONNE"

    def test_newline_in_address_is_collapsed(self):
        record = {
            "adresse_brut": "RESIDENCE KURUTXETA\n6 ALLEE GAU AINARA",
            "code_postal_brut": 64990,
            "nom_commune_brut": "ST PIERRE D'IRUBE",
        }
        query = build_geocoding_query(record)
        assert "\n" not in query
        assert query == "RESIDENCE KURUTXETA 6 ALLEE GAU AINARA 64990 ST PIERRE D'IRUBE"


class TestBuildCleanRecord:
    def test_normalizes_address_same_as_normalize_address(self):
        record = {"adresse_brut": "27 allée docteur robert lafon", "numero_dpe": "X1"}
        clean = build_clean_record(record)
        assert clean["adresse_normalisee"] == "27 ALLEE DOCTEUR ROBERT LAFON"

    def test_preserves_raw_address(self):
        record = {"adresse_brut": "27 Allée Docteur Robert Lafon"}
        clean = build_clean_record(record)
        assert clean["adresse_brut"] == "27 Allée Docteur Robert Lafon"

    def test_copies_expected_fields(self):
        record = {
            "numero_dpe": "2664E0073818V",
            "date_etablissement_dpe": "2026-01-12",
            "etiquette_dpe": "B",
            "etiquette_ges": "B",
            "type_batiment": "appartement",
            "periode_construction": "2013-2021",
            "surface_habitable_logement": 63.1,
            "adresse_brut": "27 Allée Docteur Robert Lafon",
            "code_postal_brut": 64100,
            "nom_commune_brut": "BAYONNE",
            "code_insee_ban": "64102",
            "nom_commune_ban": "Bayonne",
            "code_postal_ban": "64100",
        }
        clean = build_clean_record(record)
        assert clean["numero_dpe"] == "2664E0073818V"
        assert clean["date_etablissement_dpe"] == "2026-01-12"
        assert clean["etiquette_dpe"] == "B"
        assert clean["etiquette_ges"] == "B"
        assert clean["type_batiment"] == "appartement"
        assert clean["periode_construction"] == "2013-2021"
        assert clean["surface_habitable_logement"] == 63.1
        assert clean["code_insee_ban"] == "64102"
        assert clean["nom_commune_ban"] == "Bayonne"
        assert clean["code_postal_ban"] == "64100"

    def test_missing_fields_default_to_none(self):
        clean = build_clean_record({})
        assert clean["numero_dpe"] is None
        assert clean["surface_habitable_logement"] is None
        assert clean["periode_construction"] is None
        assert clean["adresse_brut"] == ""
        assert clean["adresse_normalisee"] == ""

    def test_includes_geocoding_query(self):
        record = {
            "adresse_brut": "27 Allée Docteur Robert Lafon",
            "code_postal_brut": 64100,
            "nom_commune_brut": "BAYONNE",
        }
        clean = build_clean_record(record)
        assert clean["adresse_geocodage"] == "27 Allée Docteur Robert Lafon 64100 BAYONNE"

    def test_geocoding_query_none_when_no_address(self):
        clean = build_clean_record({})
        assert clean["adresse_geocodage"] is None


class TestProcessRecords:
    def test_splits_post_and_pre_reform(self):
        records = [
            {"numero_dpe": "A", "date_etablissement_dpe": "2022-01-01", "adresse_brut": "1 Rue A"},
            {"numero_dpe": "B", "date_etablissement_dpe": "2020-01-01", "adresse_brut": "2 Rue B"},
        ]
        clean_rows, exclusions = process_records(records)

        assert len(clean_rows) == 1
        assert clean_rows[0]["numero_dpe"] == "A"
        assert exclusions == {"pre_reform": 1, "missing_date": 0, "invalid_date": 0}

    def test_counts_missing_and_invalid_dates_separately(self):
        records = [
            {"numero_dpe": "A", "date_etablissement_dpe": None},
            {"numero_dpe": "B", "date_etablissement_dpe": ""},
            {"numero_dpe": "C", "date_etablissement_dpe": "not-a-date"},
            {"numero_dpe": "D", "date_etablissement_dpe": "2022-01-01"},
        ]
        clean_rows, exclusions = process_records(records)

        assert len(clean_rows) == 1
        assert exclusions == {"pre_reform": 0, "missing_date": 2, "invalid_date": 1}

    def test_empty_input_returns_empty_output(self):
        clean_rows, exclusions = process_records([])
        assert clean_rows == []
        assert exclusions == {"pre_reform": 0, "missing_date": 0, "invalid_date": 0}

    def test_no_network_calls_are_made(self):
        """Sanity check that this stays pure: a huge batch runs instantly, no sockets."""
        records = [
            {"numero_dpe": str(i), "date_etablissement_dpe": "2022-01-01", "adresse_brut": "x"}
            for i in range(500)
        ]
        clean_rows, exclusions = process_records(records)
        assert len(clean_rows) == 500
        assert exclusions == {"pre_reform": 0, "missing_date": 0, "invalid_date": 0}
