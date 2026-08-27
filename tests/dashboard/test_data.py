"""Tests du seam `dashboard/data.py` -- chargement + filtrage des donnees des vues
"Marche" (#14) et "Impact DPE" (#15), ecrits avant l'implementation (TDD, CLAUDE.md).

Aucune I/O reelle sur `data/processed/` (absent en CI) : les tests de chargement
ecrivent de petits parquets via `pipeline.lib.parquet_io.write_parquet_rows`.
La logique de filtrage / d'agregation est testee pure.
"""

from __future__ import annotations

import json

import pytest

from dashboard.data import (
    DPE_GROUPS,
    MATCH_STATUSES,
    color_range,
    commune_choices,
    commune_from_code_iris,
    dpe_group,
    dvf_commune_name,
    filter_iris,
    filter_marche,
    filter_matched,
    geojson_center,
    impact_dpe_aggregate,
    impact_dpe_breakdown,
    iris_map_values,
    load_agg_iris,
    load_agg_marche,
    load_iris_geojson,
    load_matched,
    load_matching_counts,
    market_trend,
    matching_rate,
)
from pipeline.lib.parquet_io import write_parquet_rows


class TestDpeGroup:
    def test_a_b_c_map_to_first_group(self):
        assert dpe_group("A") == "A-C"
        assert dpe_group("B") == "A-C"
        assert dpe_group("C") == "A-C"

    def test_d_and_e_are_their_own_group(self):
        assert dpe_group("D") == "D"
        assert dpe_group("E") == "E"

    def test_f_and_g_map_to_last_group(self):
        assert dpe_group("F") == "F-G"
        assert dpe_group("G") == "F-G"

    def test_case_insensitive_and_stripped(self):
        assert dpe_group(" d ") == "D"

    def test_none_and_unknown_return_none(self):
        assert dpe_group(None) is None
        assert dpe_group("") is None
        assert dpe_group("Z") is None

    def test_groups_constant_order(self):
        assert DPE_GROUPS == ("A-C", "D", "E", "F-G")


class TestCommuneFromCodeIris:
    def test_prefix_is_the_insee_commune_code(self):
        assert commune_from_code_iris("640240115") == "64024"
        assert commune_from_code_iris("402090000") == "40209"

    def test_empty_is_none(self):
        assert commune_from_code_iris(None) is None
        assert commune_from_code_iris("") is None


class TestCommuneChoices:
    def test_dvf_name_strips_accents_and_apostrophes(self):
        assert dvf_commune_name("Guéthary") == "GUETHARY"
        assert dvf_commune_name("Saint-Pierre-d'Irube") == "SAINT-PIERRE-D IRUBE"
        assert dvf_commune_name("Saint-Jean-de-Luz") == "SAINT-JEAN-DE-LUZ"

    def test_choices_cover_the_16_targeted_communes(self):
        choices = commune_choices()
        assert len(choices) == 16
        for c in choices:
            assert c["nom"] and c["dvf_nom"]
            assert len(c["code_insee"]) == 5


class TestMatchingRate:
    _COUNTS = {"trouve": 20, "resolu_consensus": 10, "non_trouve": 30, "ambigu": 40}

    def test_total_is_sum_of_the_four_states(self):
        assert matching_rate(self._COUNTS)["total"] == 100

    def test_percentages_per_state(self):
        by = {s["status"]: s for s in matching_rate(self._COUNTS)["statuses"]}
        assert by["trouve"]["pct"] == pytest.approx(20.0)
        assert by["ambigu"]["pct"] == pytest.approx(40.0)
        assert by["trouve"]["label"] == "trouvé"

    def test_all_four_states_present_in_canonical_order(self):
        order = [s["status"] for s in matching_rate(self._COUNTS)["statuses"]]
        assert order == list(MATCH_STATUSES)
        assert MATCH_STATUSES == ("trouve", "resolu_consensus", "non_trouve", "ambigu")

    def test_etiquette_certaine_is_trouve_plus_consensus(self):
        cert = matching_rate(self._COUNTS)["etiquette_certaine"]
        assert cert["n"] == 30
        assert cert["pct"] == pytest.approx(30.0)

    def test_empty_counts_do_not_divide_by_zero(self):
        out = matching_rate({})
        assert out["total"] == 0
        assert out["statuses"][0]["pct"] == 0.0
        assert out["etiquette_certaine"]["pct"] == 0.0

    def test_missing_key_treated_as_zero(self):
        out = matching_rate({"trouve": 5})
        assert out["total"] == 5
        assert {s["status"]: s["n"] for s in out["statuses"]}["ambigu"] == 0


class TestFilterMarche:
    _ROWS = [
        {"commune": "ANGLET", "annee": "2019", "type_local": "Maison", "n": 5},
        {"commune": "ANGLET", "annee": "2022", "type_local": "Appartement", "n": 8},
        {"commune": "BIARRITZ", "annee": "2022", "type_local": "Maison", "n": 3},
        {"commune": "ANGLET", "annee": "2024", "type_local": "Maison", "n": 2},
    ]

    def test_no_criteria_returns_everything(self):
        assert filter_marche(self._ROWS) == self._ROWS

    def test_commune(self):
        out = filter_marche(self._ROWS, commune="ANGLET")
        assert {r["commune"] for r in out} == {"ANGLET"}
        assert len(out) == 3

    def test_type_local(self):
        out = filter_marche(self._ROWS, type_local="Maison")
        assert {r["type_local"] for r in out} == {"Maison"}

    def test_annee_range_inclusive(self):
        out = filter_marche(self._ROWS, annee_min="2020", annee_max="2023")
        assert [r["annee"] for r in out] == ["2022", "2022"]

    def test_open_ended_range(self):
        assert len(filter_marche(self._ROWS, annee_min="2023")) == 1

    def test_criteria_combine(self):
        out = filter_marche(self._ROWS, commune="ANGLET", type_local="Maison", annee_max="2020")
        assert out == [self._ROWS[0]]


class TestMarketTrend:
    _ROWS = [
        {"commune": "ANGLET", "annee": "2022", "type_local": "Maison", "n": 3, "mediane": 5000.0},
        {"commune": "ANGLET", "annee": "2019", "type_local": "Maison", "n": 5, "mediane": 4000.0},
        {"commune": "BIARRITZ", "annee": "2019", "type_local": "Maison", "n": 5, "mediane": 9000.0},
    ]

    def test_filtered_and_sorted_by_year(self):
        out = market_trend(self._ROWS, commune="ANGLET", type_local="Maison")
        assert [r["annee"] for r in out] == ["2019", "2022"]


class TestFilterIris:
    _ROWS = [
        {"code_iris": "640240115", "nom_iris": "Pontots", "type_local": "Maison",
         "moyenne": 6000.0},
        {"code_iris": "640240116", "nom_iris": "Cinq Cantons", "type_local": "Appartement",
         "moyenne": 7000.0},
        {"code_iris": "641220101", "nom_iris": "Centre", "type_local": "Maison", "moyenne": 9000.0},
        {"code_iris": "402090000", "nom_iris": "Ondres", "type_local": "Maison", "moyenne": 4000.0},
    ]

    def test_filter_by_commune_code_prefix(self):
        out = filter_iris(self._ROWS, code_commune="64024")
        assert {r["code_iris"] for r in out} == {"640240115", "640240116"}

    def test_single_iris_commune_passes_through(self):
        out = filter_iris(self._ROWS, code_commune="40209")
        assert out == [self._ROWS[3]]

    def test_type_local(self):
        out = filter_iris(self._ROWS, type_local="Maison")
        assert {r["code_iris"] for r in out} == {"640240115", "641220101", "402090000"}


class TestIrisMapValues:
    _ROWS = [
        {"code_iris": "640240115", "nom_iris": "Pontots", "type_local": "Maison",
         "n": 10, "moyenne": 9000.0, "mediane": 4000.0},
        {"code_iris": "640240115", "nom_iris": "Pontots", "type_local": "Appartement",
         "n": 30, "moyenne": 8000.0, "mediane": 6500.0},
        {"code_iris": "402090000", "nom_iris": "Ondres", "type_local": "Maison",
         "n": 5, "moyenne": 3000.0, "mediane": 2900.0},
    ]

    def test_returns_median_of_selected_type(self):
        out = {r["code_iris"]: r for r in iris_map_values(self._ROWS, type_local="Maison")}
        assert out["640240115"]["mediane"] == 4000.0
        assert out["640240115"]["n"] == 10
        assert set(out) == {"640240115", "402090000"}

    def test_other_type_selects_other_rows(self):
        out = iris_map_values(self._ROWS, type_local="Appartement")
        assert [r["mediane"] for r in out] == [6500.0]

    def test_single_iris_commune_yields_one_row(self):
        out = iris_map_values(self._ROWS, type_local="Maison", code_commune="40209")
        assert len(out) == 1
        assert out[0]["nom_iris"] == "Ondres"


class TestColorRange:
    def test_caps_zmax_at_upper_percentile(self):
        vals = [*range(1, 20), 9999]  # 20 valeurs, la derniere aberrante
        zmin, zmax = color_range(vals)
        assert zmin == 1
        assert zmax < 9999  # plafonné, l'outlier ne fixe pas le haut

    def test_small_sample_uses_min_max(self):
        assert color_range([100.0, 200.0, 5000.0]) == (100.0, 5000.0)

    def test_ignores_none(self):
        assert color_range([None, 5.0, None, 1.0], min_count=1) == (1.0, 5.0)

    def test_empty_is_none(self):
        assert color_range([]) is None


class TestFilterMatched:
    _ROWS = [
        {"commune": "ANGLET", "date_mutation": "2018-03-01", "type_local": "Maison",
         "etiquette_dpe": "D", "match_status": "trouve"},
        {"commune": "ANGLET", "date_mutation": "2022-06-01", "type_local": "Appartement",
         "etiquette_dpe": "F", "match_status": "trouve"},
        {"commune": "BIARRITZ", "date_mutation": "2023-01-01", "type_local": "Maison",
         "etiquette_dpe": "D", "match_status": "resolu_consensus"},
    ]

    def test_commune(self):
        assert len(filter_matched(self._ROWS, commune="ANGLET")) == 2

    def test_date_range_inclusive(self):
        out = filter_matched(self._ROWS, date_min="2021-01-01", date_max="2022-12-31")
        assert [r["date_mutation"] for r in out] == ["2022-06-01"]

    def test_type_local_and_groupe(self):
        # groupe "F-G" garde la ligne etiquette F, pas la D
        out = filter_matched(self._ROWS, type_local="Appartement", groupe="F-G")
        assert [r["etiquette_dpe"] for r in out] == ["F"]

    def test_groupe_d(self):
        out = filter_matched(self._ROWS, groupe="D")
        assert len(out) == 2


class TestImpactDpeAggregate:
    """Re-agregation live de la vue Impact DPE a partir des lignes brutes
    d'appariement : mêmes fonctions pures que `pipeline/05_aggregate.py`
    (`impact_dpe_rows` + `aggregate_by`), groupees par regroupement d'etiquette
    (`DPE_GROUPS`, #15), pour rendre les filtres commune / periode fonctionnels
    sur cette vue."""

    def _row(self, commune, date, typ, etiq, status, prix, surface):
        return {
            "commune": commune, "date_mutation": date, "type_local": typ,
            "etiquette_dpe": etiq, "match_status": status, "prix": prix, "surface": surface,
        }

    def test_groups_by_dpe_group_and_type(self):
        rows = [
            self._row("ANGLET", "2022-01-01", "Maison", "D", "trouve", 300_000, 60),
            self._row("ANGLET", "2023-01-01", "Maison", "D", "trouve", 500_000, 100),
            self._row("BIARRITZ", "2022-01-01", "Maison", "B", "resolu_consensus", 600_000, 60),
            self._row("ANGLET", "2022-03-01", "Maison", "C", "trouve", 700_000, 100),
        ]
        out = impact_dpe_aggregate(rows)
        by = {(r["groupe"], r["type_local"]): r for r in out}
        assert by[("D", "Maison")]["n"] == 2
        assert by[("D", "Maison")]["mediane"] == pytest.approx(5000.0)
        # B (10000) et C (7000) fusionnes dans le groupe A-C
        assert by[("A-C", "Maison")]["n"] == 2
        assert by[("A-C", "Maison")]["mediane"] == pytest.approx(8500.0)

    def test_excludes_pre_reform_and_unmatched(self):
        rows = [
            self._row("ANGLET", "2018-01-01", "Maison", "D", "trouve", 300_000, 60),
            self._row("ANGLET", "2022-01-01", "Maison", "E", "ambigu", 300_000, 60),
            self._row("ANGLET", "2022-01-01", "Maison", "F", "non_trouve", 300_000, 60),
        ]
        assert impact_dpe_aggregate(rows) == []

    def test_commune_filter_applies(self):
        rows = [
            self._row("ANGLET", "2022-01-01", "Maison", "D", "trouve", 300_000, 60),
            self._row("BIARRITZ", "2022-01-01", "Maison", "D", "trouve", 900_000, 90),
        ]
        out = impact_dpe_aggregate(rows, commune="ANGLET")
        assert len(out) == 1
        assert out[0]["mediane"] == pytest.approx(5000.0)

    def test_periode_filter_applies(self):
        rows = [
            self._row("ANGLET", "2021-08-01", "Maison", "D", "trouve", 300_000, 60),
            self._row("ANGLET", "2024-01-01", "Maison", "D", "trouve", 900_000, 90),
        ]
        out = impact_dpe_aggregate(rows, date_min="2023-01-01")
        assert out[0]["n"] == 1
        assert out[0]["mediane"] == pytest.approx(10000.0)

    def test_groupe_filter_applies(self):
        rows = [
            self._row("ANGLET", "2022-01-01", "Maison", "C", "trouve", 300_000, 60),
            self._row("ANGLET", "2022-02-01", "Maison", "F", "trouve", 900_000, 90),
        ]
        out = impact_dpe_aggregate(rows, groupe="F-G")
        assert [r["groupe"] for r in out] == ["F-G"]
        assert out[0]["n"] == 1


class TestImpactDpeBreakdown:
    def _row(self, date, status, prix=300_000, surface=60):
        return {
            "commune": "ANGLET", "date_mutation": date, "type_local": "Maison",
            "etiquette_dpe": "D", "match_status": status, "prix": prix, "surface": surface,
        }

    def test_counts_trouve_and_consensus_after_cutoff(self):
        rows = [
            self._row("2022-01-01", "trouve"),
            self._row("2023-01-01", "resolu_consensus"),
            self._row("2023-06-01", "resolu_consensus"),
        ]
        out = impact_dpe_breakdown(rows)
        assert out == {"retenues": 3, "resolu_consensus": 2, "pre_reforme_exclus": 0}

    def test_pre_reform_matched_rows_counted_separately_not_in_retenues(self):
        rows = [self._row("2019-01-01", "trouve"), self._row("2022-01-01", "trouve")]
        out = impact_dpe_breakdown(rows)
        assert out["retenues"] == 1
        assert out["pre_reforme_exclus"] == 1

    def test_unusable_price_excluded(self):
        rows = [self._row("2022-01-01", "trouve", prix=0), self._row("2022-02-01", "trouve")]
        assert impact_dpe_breakdown(rows)["retenues"] == 1


# --- chargement (fixtures parquet ecrites a la volee) ---


def _write(path, rows, types):
    write_parquet_rows(rows, types, path)


class TestLoaders:
    def test_load_agg_marche(self, tmp_path):
        p = tmp_path / "agg_marche.parquet"
        _write(
            p,
            [{"commune": "ANGLET", "annee": "2022", "type_local": "Maison",
              "n": 3, "moyenne": 5000.0, "mediane": 4800.0}],
            {"commune": "VARCHAR", "annee": "VARCHAR", "type_local": "VARCHAR",
             "n": "BIGINT", "moyenne": "DOUBLE", "mediane": "DOUBLE"},
        )
        rows = load_agg_marche(p)
        assert rows == [{"commune": "ANGLET", "annee": "2022", "type_local": "Maison",
                         "n": 3, "moyenne": 5000.0, "mediane": 4800.0}]

    def test_load_agg_iris(self, tmp_path):
        p = tmp_path / "agg_iris.parquet"
        _write(
            p,
            [{"code_iris": "402090000", "nom_iris": "Ondres", "type_local": "Maison",
              "n": 10, "moyenne": 4000.0, "mediane": 3800.0}],
            {"code_iris": "VARCHAR", "nom_iris": "VARCHAR", "type_local": "VARCHAR",
             "n": "BIGINT", "moyenne": "DOUBLE", "mediane": "DOUBLE"},
        )
        assert load_agg_iris(p)[0]["nom_iris"] == "Ondres"

    def test_load_matched_and_counts(self, tmp_path):
        p = tmp_path / "dvf_dpe_matched.parquet"
        rows = [
            {"commune": "ANGLET", "date_mutation": "2022-01-01", "type_local": "Maison",
             "surface": 60.0, "prix": 300000.0, "match_status": "trouve", "etiquette_dpe": "D"},
            {"commune": "ANGLET", "date_mutation": "2022-02-01", "type_local": "Maison",
             "surface": 50.0, "prix": 200000.0, "match_status": "ambigu", "etiquette_dpe": None},
        ]
        _write(
            p, rows,
            {"commune": "VARCHAR", "date_mutation": "VARCHAR", "type_local": "VARCHAR",
             "surface": "DOUBLE", "prix": "DOUBLE", "match_status": "VARCHAR",
             "etiquette_dpe": "VARCHAR"},
        )
        assert len(load_matched(p)) == 2
        assert load_matching_counts(p) == {"trouve": 1, "ambigu": 1}

    def test_load_iris_geojson(self, tmp_path):
        p = tmp_path / "iris.geojson"
        p.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
        assert load_iris_geojson(p)["type"] == "FeatureCollection"


class TestGeojsonCenter:
    _GEO = {
        "features": [
            {
                "properties": {"code_iris": "640240115"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-1.5, 43.4], [-1.5, 43.6], [-1.3, 43.6], [-1.3, 43.4]]],
                },
            },
            {
                "properties": {"code_iris": "402090000"},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[-1.9, 43.5], [-1.9, 43.7], [-1.7, 43.7], [-1.7, 43.5]]]],
                },
            },
        ]
    }

    def test_center_of_a_single_selected_commune(self):
        c = geojson_center(self._GEO, {"402090000"})
        assert c["lat"] == pytest.approx(43.6)
        assert c["lon"] == pytest.approx(-1.8)

    def test_center_of_all_features_when_codes_none(self):
        c = geojson_center(self._GEO)
        assert c["lat"] == pytest.approx(43.55)
        assert c["lon"] == pytest.approx(-1.6)

    def test_none_when_no_feature_matches(self):
        assert geojson_center(self._GEO, {"999999999"}) is None
