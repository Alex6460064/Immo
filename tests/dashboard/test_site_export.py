"""Tests de `dashboard/site_export.py` (#44) -- cubes precalcules pour le site
statique. Le site ne recalcule rien : chaque cube doit reproduire EXACTEMENT ce
que renvoient les fonctions du seam `dashboard/data.py` pour la meme selection.
"""

from __future__ import annotations

import pytest

from dashboard.data import (
    impact_dpe_aggregate,
    impact_dpe_breakdown,
    market_trend_global,
)
from dashboard.site_export import (
    commune_matching,
    commune_table,
    cube_start_year,
    global_trend,
    impact_counts_by_year,
    impact_cube,
    label_ladder,
    year_ranges,
)


def _row(commune, date, type_local, etiquette, status, prix, surface, dispo="000001"):
    return {
        "commune": commune,
        "code_insee": "64024" if commune == "ANGLET" else "64122",
        "no_disposition": dispo,
        "nature_mutation": "Vente",
        "date_mutation": date,
        "type_local": type_local,
        "etiquette_dpe": etiquette,
        "match_status": status,
        "prix": prix,
        "surface": surface,
    }


ROWS = [
    _row("ANGLET", "2019-05-01", "Maison", "F", "trouve", 400_000, 100),
    _row("ANGLET", "2021-09-01", "Maison", "D", "trouve", 300_000, 60),
    _row("ANGLET", "2022-03-01", "Maison", "B", "resolu_consensus", 700_000, 70),
    _row("ANGLET", "2023-06-01", "Appartement", "F", "trouve", 250_000, 50),
    _row("ANGLET", "2024-01-15", "Appartement", "E", "ambigu", 200_000, 40),
    _row("BIARRITZ", "2022-02-01", "Appartement", "G", "trouve", 450_000, 45),
    _row("BIARRITZ", "2025-02-01", "Maison", "C", "non_trouve", 900_000, 90),
]
YEARS = [str(y) for y in range(2019, 2026)]


class TestYearRanges:
    def test_all_ordered_pairs(self):
        assert year_ranges(["2020", "2021", "2022"]) == [
            ("2020", "2020"),
            ("2020", "2021"),
            ("2020", "2022"),
            ("2021", "2021"),
            ("2021", "2022"),
            ("2022", "2022"),
        ]


class TestImpactCube:
    def test_matches_seam_for_every_range(self):
        cube = impact_cube(ROWS, ["ANGLET", "BIARRITZ"], YEARS)
        for commune in ("ANGLET", "BIARRITZ"):
            for lo, hi in year_ranges(YEARS):
                expected = impact_dpe_aggregate(
                    ROWS, commune=commune, date_min=f"{lo}-01-01", date_max=f"{hi}-12-31"
                )
                start = cube_start_year(lo)
                got = [
                    {k: r[k] for k in ("groupe", "type_local", "n", "moyenne", "mediane")}
                    for r in cube
                    if r["commune"] == commune and r["annee_min"] == start and r["annee_max"] == hi
                ]
                assert got == expected

    def test_only_post_reform_start_years_exported(self):
        cube = impact_cube(ROWS, ["ANGLET"], YEARS)
        assert cube and all(r["annee_min"] >= "2021" for r in cube)


class TestImpactCountsByYear:
    @pytest.mark.parametrize("type_local", [None, "Maison", "Appartement"])
    @pytest.mark.parametrize("groupe", [None, "A-C", "D", "F-G"])
    def test_summed_years_equal_seam_breakdown(self, type_local, groupe):
        counts = impact_counts_by_year(ROWS, ["ANGLET", "BIARRITZ"], YEARS)
        for commune in ("ANGLET", "BIARRITZ"):
            for lo, hi in year_ranges(YEARS):
                expected = impact_dpe_breakdown(
                    ROWS,
                    commune=commune,
                    type_local=type_local,
                    groupe=groupe,
                    date_min=f"{lo}-01-01",
                    date_max=f"{hi}-12-31",
                )
                sel = [
                    r
                    for r in counts
                    if r["commune"] == commune
                    and r["type_local"] == type_local
                    and r["groupe"] == groupe
                    and lo <= r["annee"] <= hi
                ]
                got = {
                    k: sum(r[k] for r in sel)
                    for k in ("retenues", "resolu_consensus", "pre_reforme_exclus")
                }
                assert got == expected

    def test_all_zero_cells_are_omitted(self):
        counts = impact_counts_by_year(ROWS, ["ANGLET"], YEARS)
        assert all(
            r["retenues"] or r["resolu_consensus"] or r["pre_reforme_exclus"] for r in counts
        )


class TestGlobalTrend:
    def test_matches_seam_per_type(self):
        out = global_trend(ROWS, ["Appartement", "Maison"])
        for typ in ("Appartement", "Maison"):
            expected = market_trend_global(ROWS, type_local=typ)
            got = [
                {k: r[k] for k in ("annee", "n", "moyenne", "mediane")}
                for r in out
                if r["type_local"] == typ
            ]
            assert got == expected


class TestLabelLadder:
    def test_exact_labels_post_reform_certain_only(self):
        out = label_ladder(ROWS)
        tous = {(r["etiquette_dpe"], r["type_local"]): r for r in out if r["commune"] is None}
        # 2019 (pre-reforme), ambigu et non_trouve exclus
        assert set(tous) == {
            ("D", "Maison"),
            ("B", "Maison"),
            ("F", "Appartement"),
            ("G", "Appartement"),
        }
        assert tous[("B", "Maison")]["mediane"] == pytest.approx(10_000.0)

    def test_per_commune_rows_present(self):
        out = label_ladder(ROWS)
        biarritz = [r for r in out if r["commune"] == "BIARRITZ"]
        assert [(r["etiquette_dpe"], r["n"]) for r in biarritz] == [("G", 1)]


class TestCommuneMatching:
    def test_counts_rows_per_commune_and_status(self):
        out = commune_matching(ROWS)
        by = {(r["commune"], r["match_status"]): r["n"] for r in out}
        assert by[("ANGLET", "trouve")] == 3
        assert by[("BIARRITZ", "non_trouve")] == 1
        assert sum(r["n"] for r in out) == len(ROWS)


class TestCommuneTable:
    MARCHE = [
        {
            "commune": "ANGLET",
            "annee": "2020",
            "type_local": "Maison",
            "n": 40,
            "moyenne": 5000.0,
            "mediane": 4800.0,
        },
        {
            "commune": "ANGLET",
            "annee": "2025",
            "type_local": "Maison",
            "n": 50,
            "moyenne": 6200.0,
            "mediane": 6000.0,
        },
        {
            "commune": "ANGLET",
            "annee": "2025",
            "type_local": "Appartement",
            "n": 90,
            "moyenne": 5600.0,
            "mediane": 5500.0,
        },
    ]

    def test_latest_year_and_five_year_evolution(self):
        out = commune_table(self.MARCHE, ["ANGLET"], latest="2025")
        maison = next(r for r in out if r["type_local"] == "Maison")
        assert maison["mediane"] == 6000.0
        assert maison["n"] == 50
        assert maison["evolution"] == pytest.approx(0.25)
        assert (maison["annee_base"], maison["n_base"]) == ("2020", 40)

    def test_missing_base_year_gives_none(self):
        out = commune_table(self.MARCHE, ["ANGLET"], latest="2025")
        appart = next(r for r in out if r["type_local"] == "Appartement")
        assert appart["evolution"] is None

    def test_commune_without_latest_year_is_kept_with_none(self):
        out = commune_table(self.MARCHE, ["ANGLET", "BIARRITZ"], latest="2025")
        biarritz = [r for r in out if r["commune"] == "BIARRITZ"]
        assert biarritz and all(r["mediane"] is None for r in biarritz)
