"""Tests for pipeline.lib.aggregate -- pure aggregation logic for the dashboard
tables (issue #13), no I/O.

Written before the implementation (TDD, per CLAUDE.md). Seams: `price_per_m2`
(one mutation's price / m2) and `aggregate_by` (group rows, emit moyenne / mediane
/ n per group). CLAUDE.md / user story #29: no average is emitted without its
observation count `n`.
"""

import pytest

from pipeline.lib.aggregate import aggregate_by, impact_dpe_rows, price_per_m2


class TestImpactDpeRows:
    """Sous-ensemble de la vue Impact DPE (spec §5, D3) : mutations appariees a une
    etiquette certaine (`trouve` ou `resolu_consensus`) ET posterieures a la reforme
    DPE (le DPE post-reforme n'existe pas avant juillet 2021)."""

    _CUTOFF = "2021-07-01"

    def _row(self, status, date):
        return {"match_status": status, "date_mutation": date, "etiquette_dpe": "D"}

    def test_keeps_trouve_after_cutoff(self):
        rows = [self._row("trouve", "2023-05-01")]
        assert impact_dpe_rows(rows, self._CUTOFF) == rows

    def test_keeps_resolu_consensus_after_cutoff(self):
        rows = [self._row("resolu_consensus", "2022-01-15")]
        assert impact_dpe_rows(rows, self._CUTOFF) == rows

    def test_drops_ambigu_and_non_trouve(self):
        rows = [self._row("ambigu", "2023-01-01"), self._row("non_trouve", "2024-01-01")]
        assert impact_dpe_rows(rows, self._CUTOFF) == []

    def test_drops_matched_mutation_before_cutoff(self):
        rows = [self._row("trouve", "2018-04-01"), self._row("resolu_consensus", "2020-12-31")]
        assert impact_dpe_rows(rows, self._CUTOFF) == []

    def test_drops_row_with_missing_date(self):
        assert impact_dpe_rows([self._row("trouve", None)], self._CUTOFF) == []

    def test_cutoff_date_itself_is_kept(self):
        rows = [self._row("trouve", "2021-07-01")]
        assert impact_dpe_rows(rows, self._CUTOFF) == rows


class TestPricePerM2:
    def test_plain_division(self):
        assert price_per_m2(300_000, 60) == 5000.0

    def test_zero_surface_is_none(self):
        assert price_per_m2(300_000, 0) is None

    def test_missing_price_is_none(self):
        assert price_per_m2(None, 60) is None

    def test_missing_surface_is_none(self):
        assert price_per_m2(300_000, None) is None

    def test_non_positive_price_is_none(self):
        assert price_per_m2(0, 60) is None
        assert price_per_m2(-10, 60) is None


class TestAggregateBy:
    def test_single_group_moyenne_mediane_n(self):
        rows = [
            {"commune": "Biarritz", "prix_m2": 4000.0},
            {"commune": "Biarritz", "prix_m2": 6000.0},
            {"commune": "Biarritz", "prix_m2": 8000.0},
        ]
        result = aggregate_by(rows, ["commune"])
        assert result == [{"commune": "Biarritz", "n": 3, "moyenne": 6000.0, "mediane": 6000.0}]

    def test_even_count_median_is_mean_of_two_middle_values(self):
        rows = [{"c": "X", "prix_m2": v} for v in (10.0, 20.0, 30.0, 100.0)]
        result = aggregate_by(rows, ["c"])
        assert result[0]["mediane"] == 25.0
        assert result[0]["moyenne"] == pytest.approx(40.0)

    def test_multiple_groups_sorted_by_key(self):
        rows = [
            {"annee": "2022", "prix_m2": 5000.0},
            {"annee": "2021", "prix_m2": 4000.0},
            {"annee": "2022", "prix_m2": 7000.0},
        ]
        result = aggregate_by(rows, ["annee"])
        assert [r["annee"] for r in result] == ["2021", "2022"]
        assert result[1] == {"annee": "2022", "n": 2, "moyenne": 6000.0, "mediane": 6000.0}

    def test_composite_group_key(self):
        rows = [
            {"commune": "Anglet", "annee": "2021", "prix_m2": 3000.0},
            {"commune": "Anglet", "annee": "2021", "prix_m2": 5000.0},
            {"commune": "Anglet", "annee": "2022", "prix_m2": 9000.0},
        ]
        result = aggregate_by(rows, ["commune", "annee"])
        assert len(result) == 2
        assert result[0] == {
            "commune": "Anglet",
            "annee": "2021",
            "n": 2,
            "moyenne": 4000.0,
            "mediane": 4000.0,
        }

    def test_rows_with_no_value_are_excluded_from_stats_and_n(self):
        rows = [
            {"c": "X", "prix_m2": 5000.0},
            {"c": "X", "prix_m2": None},
            {"c": "X"},
        ]
        result = aggregate_by(rows, ["c"])
        assert result[0]["n"] == 1
        assert result[0]["moyenne"] == 5000.0

    def test_group_with_no_usable_rows_is_dropped(self):
        rows = [{"c": "X", "prix_m2": None}, {"c": "Y", "prix_m2": 4200.0}]
        result = aggregate_by(rows, ["c"])
        assert [r["c"] for r in result] == ["Y"]

    def test_empty_input_is_empty_output(self):
        assert aggregate_by([], ["commune"]) == []

    def test_custom_value_field(self):
        rows = [{"c": "X", "prix": 100.0}, {"c": "X", "prix": 200.0}]
        result = aggregate_by(rows, ["c"], value_field="prix")
        assert result[0] == {"c": "X", "n": 2, "moyenne": 150.0, "mediane": 150.0}

    def test_none_group_key_value_kept_as_its_own_group_and_sorts_last(self):
        rows = [
            {"etiquette": None, "prix_m2": 3000.0},
            {"etiquette": "D", "prix_m2": 5000.0},
            {"etiquette": "A", "prix_m2": 6000.0},
        ]
        result = aggregate_by(rows, ["etiquette"])
        assert [r["etiquette"] for r in result] == ["A", "D", None]
