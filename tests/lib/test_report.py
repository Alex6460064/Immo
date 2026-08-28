"""Tests for pipeline.lib.report -- pure logic behind the PDF synthesis
(reports/synthese-pays-basque.pdf), no I/O.

Written before the implementation (TDD, per CLAUDE.md). Two seams:

  - `evolution` : variation du prix/m2 moyen entre une annee de depart et une
    annee de fin, pour plusieurs fenetres (10 / 5 / 1 an). Une fenetre non
    calculable (annee de depart absente, prix de depart nul) est retournee a
    part, jamais inventee -- CLAUDE.md : les zones d'incertitude sont exposees.
  - `decote_dpe` : prix/m2 moyen par (commune, type, etiquette) + ecart % vs la
    classe de reference (D). Consomme les points de `impact_dpe_slice`.
"""

import pytest

from pipeline.lib.report import (
    appariement_par_mutation,
    decote_dpe,
    evolution,
    evolutions_synthese,
)


class TestEvolution:
    def test_windows_computed_from_end_year(self):
        prix = {"2015": 3000.0, "2020": 4000.0, "2024": 4500.0, "2025": 5000.0}
        calculees, sautees = evolution(prix, fin="2025", fenetres=(10, 5, 1))
        assert sautees == []
        assert calculees[0] == {
            "fenetre_ans": 10,
            "annee_debut": "2015",
            "annee_fin": "2025",
            "prix_debut": 3000.0,
            "prix_fin": 5000.0,
            "variation_eur": pytest.approx(2000.0),
            "variation_pct": pytest.approx(66.6667, abs=1e-3),
        }
        assert calculees[2]["fenetre_ans"] == 1
        assert calculees[2]["variation_pct"] == pytest.approx(11.1111, abs=1e-3)

    def test_negative_variation(self):
        prix = {"2024": 6000.0, "2025": 5400.0}
        calculees, _ = evolution(prix, fin="2025", fenetres=(1,))
        assert calculees[0]["variation_pct"] == pytest.approx(-10.0)

    def test_missing_start_year_is_reported_not_computed(self):
        prix = {"2020": 4000.0, "2025": 5000.0}
        calculees, sautees = evolution(prix, fin="2025", fenetres=(10, 5))
        assert [c["fenetre_ans"] for c in calculees] == [5]
        assert sautees == [
            {"fenetre_ans": 10, "annee_debut": "2015", "raison": "annee de depart absente"}
        ]

    def test_missing_end_year_skips_all_windows(self):
        prix = {"2015": 3000.0}
        calculees, sautees = evolution(prix, fin="2025", fenetres=(10,))
        assert calculees == []
        assert sautees == [
            {"fenetre_ans": 10, "annee_debut": "2015", "raison": "annee de fin absente"}
        ]

    def test_zero_start_price_is_reported_not_divided(self):
        prix = {"2024": 0.0, "2025": 5000.0}
        calculees, sautees = evolution(prix, fin="2025", fenetres=(1,))
        assert calculees == []
        assert sautees == [
            {"fenetre_ans": 1, "annee_debut": "2024", "raison": "prix de depart nul"}
        ]

    def test_empty_series_reports_missing_end_year_for_every_window(self):
        assert evolution({}, fin="2025", fenetres=(10, 5, 1)) == (
            [],
            [
                {"fenetre_ans": 10, "annee_debut": "2015", "raison": "annee de fin absente"},
                {"fenetre_ans": 5, "annee_debut": "2020", "raison": "annee de fin absente"},
                {"fenetre_ans": 1, "annee_debut": "2024", "raison": "annee de fin absente"},
            ],
        )


class TestEvolutionsSynthese:
    def test_adds_longest_real_window_from_first_year(self):
        prix = {"2016": 3000.0, "2020": 4000.0, "2024": 4800.0, "2025": 5000.0}
        calculees, sautees = evolutions_synthese(prix, fin="2025", fenetres_courtes=(1, 5))
        assert sautees == []
        assert [c["fenetre_ans"] for c in calculees] == [1, 5, 9]
        assert calculees[2]["annee_debut"] == "2016"
        assert calculees[2]["variation_pct"] == pytest.approx(66.6667, abs=1e-3)

    def test_no_long_window_when_series_shorter_than_max_short_window(self):
        prix = {"2022": 4000.0, "2024": 4800.0, "2025": 5000.0}
        calculees, _ = evolutions_synthese(prix, fin="2025", fenetres_courtes=(1, 5))
        assert [c["fenetre_ans"] for c in calculees] == [1]

    def test_empty_series_returns_only_short_windows_as_skipped(self):
        calculees, sautees = evolutions_synthese({}, fin="2025", fenetres_courtes=(1, 5))
        assert calculees == []
        assert [s["fenetre_ans"] for s in sautees] == [1, 5]


def _lot(commune="BAYONNE", type_local="Appartement", match_status="trouve", **kw):
    row = {
        "commune": commune,
        "type_local": type_local,
        "match_status": match_status,
        "date_mutation": "2022-05-01",
        "code_insee": "64102",
        "no_disposition": "1",
        "prix": 300000.0,
    }
    row.update(kw)
    return row


class TestAppariementParMutation:
    def test_counts_mutations_not_lots(self):
        # une vente = 3 lots appartement, meme mutation_key -> compte pour 1
        rows = [_lot(no_disposition="7", prix=900000.0) for _ in range(3)]
        assert appariement_par_mutation(rows, ["BAYONNE"]) == {"trouve": 1}

    def test_non_habitation_lots_are_ignored(self):
        rows = [
            _lot(type_local="Dépendance", match_status="non_trouve", no_disposition="1"),
            _lot(type_local="Local industriel", match_status="non_trouve", no_disposition="2"),
        ]
        assert appariement_par_mutation(rows, ["BAYONNE"]) == {}

    def test_best_status_wins_within_a_mutation(self):
        rows = [
            _lot(match_status="ambigu", no_disposition="4", prix=500000.0),
            _lot(match_status="trouve", no_disposition="4", prix=500000.0),
        ]
        assert appariement_par_mutation(rows, ["BAYONNE"]) == {"trouve": 1}

    def test_filters_by_commune(self):
        rows = [
            _lot(commune="BAYONNE", no_disposition="1"),
            _lot(commune="URRUGNE", no_disposition="2"),
        ]
        assert appariement_par_mutation(rows, ["BAYONNE"]) == {"trouve": 1}

    def test_distinct_mutations_tallied_separately(self):
        rows = [
            _lot(match_status="trouve", no_disposition="1", prix=100000.0),
            _lot(match_status="non_trouve", no_disposition="2", prix=200000.0),
            _lot(match_status="resolu_consensus", no_disposition="3", prix=300000.0),
        ]
        assert appariement_par_mutation(rows, ["BAYONNE"]) == {
            "trouve": 1,
            "non_trouve": 1,
            "resolu_consensus": 1,
        }


def _pt(commune, type_local, etiquette, prix_m2):
    return {
        "commune": commune,
        "type_local": type_local,
        "etiquette_dpe": etiquette,
        "prix_m2": prix_m2,
    }


class TestDecoteDpe:
    def test_ecart_pct_vs_reference_class(self):
        points = [
            _pt("BIARRITZ", "Appartement", "D", 10000.0),
            _pt("BIARRITZ", "Appartement", "D", 10000.0),
            _pt("BIARRITZ", "Appartement", "C", 8000.0),
            _pt("BIARRITZ", "Appartement", "F", 12000.0),
        ]
        rows = decote_dpe(points, reference="D")
        by_cls = {r["etiquette_dpe"]: r for r in rows}
        assert by_cls["D"]["ecart_pct"] == pytest.approx(0.0)
        assert by_cls["C"]["pm2_moyen"] == pytest.approx(8000.0)
        assert by_cls["C"]["ecart_pct"] == pytest.approx(-20.0)
        assert by_cls["F"]["ecart_pct"] == pytest.approx(20.0)
        assert by_cls["C"]["n"] == 1

    def test_missing_reference_class_leaves_ecart_none(self):
        points = [
            _pt("BAYONNE", "Maison", "C", 5000.0),
            _pt("BAYONNE", "Maison", "E", 4000.0),
        ]
        rows = decote_dpe(points, reference="D")
        assert all(r["ecart_pct"] is None for r in rows)

    def test_groups_are_split_by_commune_and_type(self):
        points = [
            _pt("BAYONNE", "Appartement", "D", 4000.0),
            _pt("BAYONNE", "Maison", "D", 5000.0),
            _pt("ANGLET", "Appartement", "D", 6000.0),
        ]
        rows = decote_dpe(points)
        keys = {(r["commune"], r["type_local"]) for r in rows}
        assert keys == {
            ("ANGLET", "Appartement"),
            ("BAYONNE", "Appartement"),
            ("BAYONNE", "Maison"),
        }

    def test_rows_sorted_by_commune_type_then_label(self):
        points = [
            _pt("BAYONNE", "Appartement", "F", 4000.0),
            _pt("BAYONNE", "Appartement", "A", 4000.0),
            _pt("ANGLET", "Appartement", "D", 4000.0),
        ]
        rows = decote_dpe(points)
        assert [(r["commune"], r["type_local"], r["etiquette_dpe"]) for r in rows] == [
            ("ANGLET", "Appartement", "D"),
            ("BAYONNE", "Appartement", "A"),
            ("BAYONNE", "Appartement", "F"),
        ]

    def test_empty_points(self):
        assert decote_dpe([]) == []
