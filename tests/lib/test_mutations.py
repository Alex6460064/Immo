"""Tests for pipeline.lib.mutations -- collapsing raw DVF lot-lines to one
price/m2 point per mutation before aggregation (issue #26), no I/O.

Written before the implementation (TDD, per CLAUDE.md). Root cause: DVF's
"Valeur fonciere" is a *mutation* total, repeated verbatim on every lot line;
dividing it by a single lot's surface (the pre-#26 behaviour) inflates block
sales to ~100 000 EUR/m2. These tests pin the corrected rules:

  - mutation key = (date_mutation, code_insee, no_disposition, prix)
  - habitation = Appartement + Maison; price/m2 = prix / sum(habitation surface)
  - rule C : one point only if the mutation is mono-type habitation; Dependance
    lines ignored; a habitation+commercial mix is excluded and counted
  - rule A : nature_mutation whitelist + price/m2 sanity band [200, 30000],
    exclusions counted by reason
"""

import pytest

from pipeline.lib.mutations import (
    NATURES_RETENUES,
    PRIX_M2_MAX,
    PRIX_M2_MIN,
    mutation_key,
    mutation_price_points,
)


def _row(**kw):
    base = {
        "date_mutation": "2019-05-04",
        "code_insee": "64122",
        "no_disposition": "000001",
        "nature_mutation": "Vente",
        "prix": 300_000.0,
        "type_local": "Appartement",
        "surface": 60.0,
        "commune": "BIARRITZ",
        "etiquette_dpe": None,
        "match_status": "non_trouve",
    }
    base.update(kw)
    return base


class TestMutationKey:
    def test_four_part_key(self):
        r = _row()
        assert mutation_key(r) == ("2019-05-04", "64122", "000001", 300_000.0)

    def test_same_price_different_disposition_are_distinct(self):
        a = _row(no_disposition="000001")
        b = _row(no_disposition="000002")
        assert mutation_key(a) != mutation_key(b)

    def test_missing_parts_tolerated(self):
        r = _row(no_disposition=None, code_insee=None)
        assert mutation_key(r) == ("2019-05-04", None, None, 300_000.0)


class TestSingleLotUnchanged:
    def test_one_apartment_line_yields_its_own_price_per_m2(self):
        points, excl = mutation_price_points([_row(prix=300_000.0, surface=60.0)])
        assert len(points) == 1
        assert points[0]["prix_m2"] == 5000.0
        assert points[0]["n_lots"] == 1
        assert excl == {"mixte": 0, "nature": 0, "hors_bande": 0, "sans_habitation": 0}

    def test_annee_is_derived_from_date(self):
        points, _ = mutation_price_points([_row(date_mutation="2023-11-02")])
        assert points[0]["annee"] == "2023"

    def test_passthrough_fields_kept(self):
        points, _ = mutation_price_points([_row(commune="BIARRITZ", type_local="Maison")])
        assert points[0]["commune"] == "BIARRITZ"
        assert points[0]["type_local"] == "Maison"


class TestBlockSaleCollapsed:
    def test_troubadours_like_block_collapses_to_one_realistic_point(self):
        # 65 apartment lots, whole-mutation price repeated on every line
        rows = [
            _row(
                date_mutation="2017-09-25",
                code_insee="40312",
                no_disposition="000001",
                prix=6_587_120.0,
                surface=73.0,  # 65 * 73 = 4745 m2
                type_local="Appartement",
                commune="TARNOS",
            )
            for _ in range(65)
        ]
        points, excl = mutation_price_points(rows)
        assert len(points) == 1
        assert points[0]["prix_m2"] == pytest.approx(6_587_120.0 / (65 * 73.0), rel=1e-6)
        assert 1000 < points[0]["prix_m2"] < 2000
        assert points[0]["n_lots"] == 65
        assert excl == {"mixte": 0, "nature": 0, "hors_bande": 0, "sans_habitation": 0}

    def test_two_apartments_sold_together_use_summed_surface(self):
        rows = [
            _row(prix=600_000.0, surface=50.0),
            _row(prix=600_000.0, surface=50.0),
        ]
        points, _ = mutation_price_points(rows)
        assert len(points) == 1
        assert points[0]["prix_m2"] == 6000.0  # 600k / 100, not 600k / 50

    def test_distinct_mutations_stay_separate(self):
        rows = [
            _row(no_disposition="000001", prix=300_000.0, surface=60.0),
            _row(no_disposition="000002", prix=400_000.0, surface=80.0),
        ]
        points, _ = mutation_price_points(rows)
        assert sorted(p["prix_m2"] for p in points) == [5000.0, 5000.0]
        assert len(points) == 2


class TestRuleCHabitationOnly:
    def test_house_plus_dependance_keeps_house_only_surface(self):
        # classic "maison + garage" : Dependance line ignored, not a mix
        rows = [
            _row(type_local="Maison", surface=100.0, prix=500_000.0),
            _row(type_local="Dépendance", surface=15.0, prix=500_000.0),
        ]
        points, excl = mutation_price_points(rows)
        assert len(points) == 1
        assert points[0]["prix_m2"] == 5000.0  # 500k / 100, garage surface excluded
        assert excl["mixte"] == 0

    def test_habitation_plus_commercial_is_excluded_and_counted(self):
        rows = [
            _row(type_local="Appartement", surface=200.0, prix=1_450_000.0),
            _row(
                type_local="Local industriel. commercial ou assimilé",
                surface=800.0,
                prix=1_450_000.0,
            ),
        ]
        points, excl = mutation_price_points(rows)
        assert points == []
        assert excl["mixte"] == 1

    def test_apartment_and_house_in_one_mutation_is_excluded(self):
        rows = [
            _row(type_local="Appartement", surface=60.0, prix=800_000.0),
            _row(type_local="Maison", surface=120.0, prix=800_000.0),
        ]
        points, excl = mutation_price_points(rows)
        assert points == []
        assert excl["mixte"] == 1

    def test_pure_commercial_mutation_counted_sans_habitation_not_mixte(self):
        rows = [_row(type_local="Local industriel. commercial ou assimilé", surface=300.0)]
        points, excl = mutation_price_points(rows)
        assert points == []
        assert excl == {"mixte": 0, "nature": 0, "hors_bande": 0, "sans_habitation": 1}


class TestRuleAGuards:
    def test_nature_echange_excluded_and_counted(self):
        points, excl = mutation_price_points([_row(nature_mutation="Echange")])
        assert points == []
        assert excl["nature"] == 1

    def test_whitelisted_natures_kept(self):
        for nat in NATURES_RETENUES:
            points, _ = mutation_price_points([_row(nature_mutation=nat)])
            assert len(points) == 1, nat

    def test_symbolic_one_euro_sale_below_band_excluded(self):
        points, excl = mutation_price_points([_row(prix=1.0, surface=80.0)])
        assert points == []
        assert excl["hors_bande"] == 1

    def test_surface_underdeclared_above_band_excluded(self):
        points, excl = mutation_price_points([_row(prix=3_400_000.0, surface=30.0)])
        assert points == []
        assert excl["hors_bande"] == 1

    def test_band_edges_are_inclusive(self):
        lo = mutation_price_points([_row(prix=PRIX_M2_MIN * 50.0, surface=50.0)])[0]
        hi = mutation_price_points([_row(prix=PRIX_M2_MAX * 50.0, surface=50.0)])[0]
        assert len(lo) == 1 and len(hi) == 1

    def test_exclusion_precedence_mix_before_nature(self):
        rows = [
            _row(nature_mutation="Echange", type_local="Appartement", surface=60.0),
            _row(
                nature_mutation="Echange",
                type_local="Local industriel. commercial ou assimilé",
                surface=200.0,
            ),
        ]
        _, excl = mutation_price_points(rows)
        assert excl["mixte"] == 1
        assert excl["nature"] == 0


class TestExtraKeys:
    def test_no_extra_keys_gives_one_point_per_mutation(self):
        rows = [
            _row(surface=60.0, etiquette_dpe="D", prix=900_000.0),
            _row(surface=60.0, etiquette_dpe="F", prix=900_000.0),
            _row(surface=60.0, etiquette_dpe="F", prix=900_000.0),
        ]
        points, _ = mutation_price_points(rows)
        assert len(points) == 1
        assert points[0]["prix_m2"] == pytest.approx(900_000.0 / 180.0)

    def test_split_on_etiquette_shares_mutation_price(self):
        rows = [
            _row(surface=60.0, etiquette_dpe="D", match_status="trouve", prix=900_000.0),
            _row(surface=60.0, etiquette_dpe="F", match_status="trouve", prix=900_000.0),
            _row(surface=60.0, etiquette_dpe="F", match_status="trouve", prix=900_000.0),
        ]
        points, _ = mutation_price_points(rows, extra_keys=("etiquette_dpe", "match_status"))
        by_etq = {p["etiquette_dpe"]: p for p in points}
        assert set(by_etq) == {"D", "F"}
        # every emitted point carries the SAME mutation-level price/m2
        assert by_etq["D"]["prix_m2"] == pytest.approx(900_000.0 / 180.0)
        assert by_etq["F"]["prix_m2"] == pytest.approx(900_000.0 / 180.0)

    def test_denominator_is_all_habitation_surface_not_the_subgroup(self):
        # 1 matched lot + 9 unmatched lots, one price : matched point still uses
        # the full 10-lot surface as denominator
        rows = [_row(surface=50.0, match_status="trouve", etiquette_dpe="E", prix=2_000_000.0)]
        rows += [
            _row(surface=50.0, match_status="non_trouve", etiquette_dpe=None, prix=2_000_000.0)
            for _ in range(9)
        ]
        points, _ = mutation_price_points(rows, extra_keys=("etiquette_dpe", "match_status"))
        trouve = [p for p in points if p["match_status"] == "trouve"][0]
        assert trouve["prix_m2"] == pytest.approx(2_000_000.0 / 500.0)  # /500, not /50


class TestReconciliation:
    def test_points_plus_exclusions_equal_distinct_mutations(self):
        rows = [
            _row(no_disposition="1", prix=300_000.0, surface=60.0),  # ok
            _row(no_disposition="2", prix=1.0, surface=60.0),  # hors_bande
            _row(no_disposition="3", nature_mutation="Echange"),  # nature
            _row(no_disposition="4", type_local="Appartement", surface=60.0, prix=9e5),
            _row(
                no_disposition="4",
                type_local="Local industriel. commercial ou assimilé",
                surface=200.0,
                prix=9e5,
            ),  # mixte (1 mutation)
            _row(no_disposition="5", type_local="Dépendance", surface=10.0),  # sans_habitation
        ]
        points, excl = mutation_price_points(rows)
        assert len(points) + sum(excl.values()) == 5
        assert excl == {"mixte": 1, "nature": 1, "hors_bande": 1, "sans_habitation": 1}


class TestEmptyInput:
    def test_empty(self):
        assert mutation_price_points([]) == (
            [],
            {"mixte": 0, "nature": 0, "hors_bande": 0, "sans_habitation": 0},
        )
