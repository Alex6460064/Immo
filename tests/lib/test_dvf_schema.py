"""Tests pour pipeline.lib.dvf_schema -- schema partage des parquets DVF (#22).

Verrouille l'ordre et le contenu des colonnes : ces listes etaient copiees a
l'identique dans 02b_geocode_ban / 04_join / 04b_join_iris.
"""

from pipeline.lib.dvf_schema import DVF_CLEAN_COLUMN_NAMES, DVF_GEOCODED_COLUMNS


def test_geocoded_is_clean_plus_latlon():
    assert list(DVF_GEOCODED_COLUMNS)[-2:] == ["lat", "lon"]
    assert tuple(DVF_GEOCODED_COLUMNS)[:-2] == DVF_CLEAN_COLUMN_NAMES


def test_clean_names_exclude_latlon():
    assert "lat" not in DVF_CLEAN_COLUMN_NAMES
    assert "lon" not in DVF_CLEAN_COLUMN_NAMES


def test_geocoded_column_types():
    assert DVF_GEOCODED_COLUMNS["surface"] == "DOUBLE"
    assert DVF_GEOCODED_COLUMNS["prix"] == "DOUBLE"
    assert DVF_GEOCODED_COLUMNS["lat"] == "DOUBLE"
    assert DVF_GEOCODED_COLUMNS["lon"] == "DOUBLE"
    assert DVF_GEOCODED_COLUMNS["nombre_pieces_principales"] == "VARCHAR"
    assert DVF_GEOCODED_COLUMNS["date_mutation"] == "VARCHAR"


def test_expected_column_set():
    assert set(DVF_GEOCODED_COLUMNS) == {
        "identifiant_document",
        "no_disposition",
        "date_mutation",
        "nature_mutation",
        "code_insee",
        "commune",
        "code_postal",
        "adresse_brute",
        "adresse_normalisee",
        "type_local",
        "nombre_pieces_principales",
        "surface",
        "prix",
        "lat",
        "lon",
    }
