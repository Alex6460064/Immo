"""Tests pour pipeline/lib/download_dvf_historique.py -- logique pure (URL par
millesime, millesimes couverts, alias de colonne), aucun appel reseau reel ici."""

import pytest

from pipeline.lib.download_dvf_historique import (
    HISTORICAL_EDITION_URL,
    alias_historical_columns,
    historical_url_for_year,
    historical_years,
    require_downstream_columns,
    validate_historical_header,
)


def test_historical_years_couvre_2016_a_2020():
    assert historical_years() == [2016, 2017, 2018, 2019, 2020]


def test_historical_url_for_year_construit_l_url_attendue():
    assert historical_url_for_year(2018) == f"{HISTORICAL_EDITION_URL}/valeursfoncieres-2018.txt"


def test_historical_url_for_year_leve_value_error_hors_edition():
    with pytest.raises(ValueError):
        historical_url_for_year(2021)

    with pytest.raises(ValueError):
        historical_url_for_year(2015)


def test_alias_historical_columns_renomme_uniquement_la_colonne_connue():
    columns = ["Code service CH", "Reference document", "Date mutation"]

    assert alias_historical_columns(columns) == [
        "Identifiant de document",
        "Reference document",
        "Date mutation",
    ]


def test_alias_historical_columns_laisse_les_autres_colonnes_inchangees():
    columns = ["Reference document", "Date mutation"]

    assert alias_historical_columns(columns) == columns


def test_alias_historical_columns_refuse_une_collision():
    # Source ET cible presentes : renommer produirait deux "Identifiant de document".
    columns = ["Code service CH", "Identifiant de document", "Date mutation"]

    with pytest.raises(ValueError, match="[Cc]ollision"):
        alias_historical_columns(columns)


# En-tete reel du DVF brut : sous-ensemble suffisant pour les tests (les colonnes
# sentinelles verifiees + du bruit autour).
_VALID_HEADER = (
    "Code service CH|Reference document|Date mutation|Nature mutation|"
    "Valeur fonciere|No voie|Voie|Code postal|Commune|Code departement|"
    "Code commune|Type local|Surface reelle bati"
)


class TestValidateHistoricalHeader:
    def test_en_tete_valide_ne_leve_rien(self):
        validate_historical_header(_VALID_HEADER)

    def test_page_html_derreur_rejetee(self):
        with pytest.raises(ValueError, match="pipe"):
            validate_historical_header("<!DOCTYPE html>")

    def test_corps_sans_pipe_rejete(self):
        with pytest.raises(ValueError, match="pipe"):
            validate_historical_header("503 Service Unavailable")

    def test_colonne_sentinelle_absente_rejetee(self):
        header = _VALID_HEADER.replace("Valeur fonciere|", "")
        with pytest.raises(ValueError, match="Valeur fonciere"):
            validate_historical_header(header)

    def test_espaces_autour_des_noms_toleres(self):
        spaced = _VALID_HEADER.replace("|", " | ")
        validate_historical_header(spaced)


# Colonnes reellement lues par pipeline/02_clean_dvf.py (_RAW_SELECT_QUERY),
# apres alias historique.
_DOWNSTREAM_COLUMNS = [
    "Identifiant de document",
    "No disposition",
    "Date mutation",
    "Nature mutation",
    "Valeur fonciere",
    "No voie",
    "B/T/Q",
    "Type de voie",
    "Voie",
    "Code postal",
    "Commune",
    "Code departement",
    "Code commune",
    "Type local",
    "Nombre pieces principales",
    "Surface reelle bati",
]


class TestRequireDownstreamColumns:
    def test_jeu_complet_ne_leve_rien(self):
        require_downstream_columns([*_DOWNSTREAM_COLUMNS, "colonne en trop"])

    def test_colonne_aval_manquante_rejetee_avec_son_nom(self):
        incomplet = [c for c in _DOWNSTREAM_COLUMNS if c != "Surface reelle bati"]
        with pytest.raises(ValueError, match="Surface reelle bati"):
            require_downstream_columns(incomplet)

    def test_identifiant_document_non_aliase_rejete(self):
        # "Code service CH" pas encore renomme -> la colonne aval manque.
        brut = [
            "Code service CH" if c == "Identifiant de document" else c for c in _DOWNSTREAM_COLUMNS
        ]
        with pytest.raises(ValueError, match="Identifiant de document"):
            require_downstream_columns(brut)
