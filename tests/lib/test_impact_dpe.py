"""Tests for pipeline.lib.impact_dpe -- la chaine unique de la vue "Impact DPE"
(repli mutation -> filtre optionnel -> cutoff + comptages), no I/O.

Ecrit avant l'implementation (TDD, CLAUDE.md). Deux seams :

  - `impact_dpe_rows(rows, cutoff)` : sous-ensemble a etiquette certaine ET
    posterieur a la reforme DPE (deplace depuis `aggregate.py`, comportement
    inchange -- `TestImpactDpeRows` est la suite migree telle quelle).
  - `impact_dpe_slice(matched_rows, *, cutoff, keep=None) -> ImpactDpeSlice` :
    la chaine complete, appelee a l'identique par `pipeline/05_aggregate.py`
    (sans `keep`) et `dashboard/data.py` (`keep` = closure sur la selection UI).
    `test_slice_sans_keep_egale_recette_pipeline` est l'invariant qui lie les
    deux -- il n'y a plus qu'une chaine.
"""

from pipeline.lib.aggregate import aggregate_by
from pipeline.lib.impact_dpe import (
    IMPACT_DPE_EXTRA_KEYS,
    ImpactDpeSlice,
    impact_dpe_rows,
    impact_dpe_slice,
)
from pipeline.lib.mutations import mutation_price_points

_CUTOFF = "2021-07-01"


class TestImpactDpeRows:
    """Sous-ensemble de la vue Impact DPE (spec 5, D3) : mutations appariees a une
    etiquette certaine (`trouve` ou `resolu_consensus`) ET posterieures a la reforme
    DPE (le DPE post-reforme n'existe pas avant juillet 2021)."""

    def _row(self, status, date):
        return {"match_status": status, "date_mutation": date, "etiquette_dpe": "D"}

    def test_keeps_trouve_after_cutoff(self):
        rows = [self._row("trouve", "2023-05-01")]
        assert impact_dpe_rows(rows, _CUTOFF) == rows

    def test_keeps_resolu_consensus_after_cutoff(self):
        rows = [self._row("resolu_consensus", "2022-01-15")]
        assert impact_dpe_rows(rows, _CUTOFF) == rows

    def test_drops_ambigu_and_non_trouve(self):
        rows = [self._row("ambigu", "2023-01-01"), self._row("non_trouve", "2024-01-01")]
        assert impact_dpe_rows(rows, _CUTOFF) == []

    def test_drops_matched_mutation_before_cutoff(self):
        rows = [self._row("trouve", "2018-04-01"), self._row("resolu_consensus", "2020-12-31")]
        assert impact_dpe_rows(rows, _CUTOFF) == []

    def test_drops_row_with_missing_date(self):
        assert impact_dpe_rows([self._row("trouve", None)], _CUTOFF) == []

    def test_cutoff_date_itself_is_kept(self):
        rows = [self._row("trouve", "2021-07-01")]
        assert impact_dpe_rows(rows, _CUTOFF) == rows


def _lot(
    *,
    code_insee="64102",
    no_disposition="000001",
    nature="Vente",
    date="2022-01-01",
    prix=300_000.0,
    commune="ANGLET",
    type_local="Appartement",
    surface=60.0,
    status="trouve",
    etiquette="D",
):
    """Une ligne-lot de `dvf_dpe_matched` (schema lu par `05_aggregate` / le
    dashboard). La cle mutation est `(date, code_insee, no_disposition, prix)`."""
    return {
        "code_insee": code_insee,
        "no_disposition": no_disposition,
        "nature_mutation": nature,
        "date_mutation": date,
        "prix": prix,
        "commune": commune,
        "type_local": type_local,
        "surface": surface,
        "match_status": status,
        "etiquette_dpe": etiquette,
    }


# Fixture : 6 mutations produisant un point prix/m2 (toutes a 5000 EUR/m2), plus
# 2 mutations ecartees par les garde-fous.
#   M1 trouve            post-cutoff  D            -> points
#   M2 resolu_consensus  post-cutoff  E  BIARRITZ  -> points + resolu_consensus
#   M3 trouve            PRE-cutoff   C            -> certaine + pre_reforme (hors points)
#   M4 ambigu            post-cutoff  F            -> n_points seulement
#   M5 non_trouve        post-cutoff  (sans etiq.) -> n_points seulement
#   M6 trouve (bloc x3)  post-cutoff  D            -> 1 point (repli)
#   M7 mixte (appart + local commercial)           -> exclusions["mixte"]
#   M8 prix/m2 = 200 000 EUR/m2                     -> exclusions["hors_bande"]
_MATCHED = [
    _lot(date="2022-01-01", prix=300_000.0, surface=60.0, status="trouve", etiquette="D"),
    _lot(
        date="2022-02-01",
        prix=400_000.0,
        surface=80.0,
        status="resolu_consensus",
        etiquette="E",
        commune="BIARRITZ",
    ),
    _lot(date="2019-01-01", prix=250_000.0, surface=50.0, status="trouve", etiquette="C"),
    _lot(date="2022-04-01", prix=500_000.0, surface=100.0, status="ambigu", etiquette="F"),
    _lot(date="2022-05-01", prix=280_000.0, surface=56.0, status="non_trouve", etiquette=None),
    *[
        _lot(
            date="2022-03-01",
            no_disposition="000002",
            prix=900_000.0,
            surface=60.0,
            status="trouve",
            etiquette="D",
        )
        for _ in range(3)
    ],
    _lot(date="2022-06-01", no_disposition="000003", prix=600_000.0, surface=50.0),
    _lot(
        date="2022-06-01",
        no_disposition="000003",
        prix=600_000.0,
        surface=50.0,
        type_local="Local industriel. commercial ou assimile",
    ),
    _lot(date="2022-07-01", no_disposition="000004", prix=10_000_000.0, surface=50.0),
]


class TestImpactDpeSlice:
    def test_slice_sans_keep_egale_recette_pipeline(self):
        """L'invariant du refactor : la nouvelle chaine, sans `keep`, agrege
        exactement les memes mutations que l'ancienne chaine ecrite a la main
        dans `pipeline/05_aggregate.py` (`agg_dpe.parquet`)."""
        sl = impact_dpe_slice(_MATCHED, cutoff=_CUTOFF)
        got = aggregate_by(sl.points, ["etiquette_dpe", "type_local"])

        ref_pts, _ = mutation_price_points(_MATCHED, extra_keys=("etiquette_dpe", "match_status"))
        ref = aggregate_by(impact_dpe_rows(ref_pts, _CUTOFF), ["etiquette_dpe", "type_local"])

        assert got == ref
        assert got != []

    def test_champs_sans_keep(self):
        sl = impact_dpe_slice(_MATCHED, cutoff=_CUTOFF)
        assert isinstance(sl, ImpactDpeSlice)
        assert sl.n_points == 6  # M1 M2 M3 M4 M5 M6
        assert sl.etiquette_certaine == 4  # M1 M2 M3 M6
        assert len(sl.points) == 3  # M1 M2 M6 (M3 pre-cutoff)
        assert sl.resolu_consensus == 1  # M2
        assert sl.pre_reforme == 1  # M3
        assert sl.exclusions == {"mixte": 1, "nature": 0, "hors_bande": 1, "sans_habitation": 0}

    def test_keep_filtre_points_pas_n_points_ni_exclusions(self):
        """`keep` (predicat post-repli, pre-cutoff) restreint `points` /
        `etiquette_certaine` / `resolu_consensus` / `pre_reforme` ; `n_points` et
        `exclusions` portent toujours sur l'entree entiere (le repli est
        independant de `keep`)."""
        sl = impact_dpe_slice(_MATCHED, cutoff=_CUTOFF, keep=lambda p: p.get("commune") == "ANGLET")
        # M2 (BIARRITZ) exclu ; restent M1 et M6, tous deux etiquette D
        assert [r["etiquette_dpe"] for r in sl.points] == ["D", "D"]
        assert sl.resolu_consensus == 0
        assert sl.etiquette_certaine == 3  # M1 M3 M6
        assert sl.pre_reforme == 1  # M3
        assert sl.n_points == 6
        assert sl.exclusions == {"mixte": 1, "nature": 0, "hors_bande": 1, "sans_habitation": 0}

    def test_keep_none_equivaut_a_predicat_toujours_vrai(self):
        a = impact_dpe_slice(_MATCHED, cutoff=_CUTOFF)
        b = impact_dpe_slice(_MATCHED, cutoff=_CUTOFF, keep=lambda _p: True)
        assert a == b

    def test_extra_keys_expose_le_litteral(self):
        assert IMPACT_DPE_EXTRA_KEYS == ("etiquette_dpe", "match_status")
