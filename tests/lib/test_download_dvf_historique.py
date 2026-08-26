"""Tests pour pipeline/lib/download_dvf_historique.py -- logique pure (URL par
millesime, millesimes couverts, alias de colonne), aucun appel reseau reel ici."""

import pytest

from pipeline.lib.download_dvf_historique import (
    HISTORICAL_EDITION_URL,
    alias_historical_columns,
    historical_url_for_year,
    historical_years,
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
