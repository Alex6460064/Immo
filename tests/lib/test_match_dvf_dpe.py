"""Tests for pipeline.lib.match_dvf_dpe -- pure 3-pass DVF x DPE matching logic
(ADR 0003), no I/O, no network.

Written before the implementation (TDD, per CLAUDE.md). Seam: the 3-pass matcher --
`match_mutation` (bare status, issue #11 signature) and the richer `classify_match`
(reference impl). pipeline/04_join.py calls the grid-indexed `classify_match_indexed`
for speed; a differential test here locks it to `classify_match`.

Vocabulary (CONTEXT.md): a mutation ends in exactly one of trouve / non_trouve /
ambigu, never a forced random match.
"""

import pytest

from pipeline.lib.match_dvf_dpe import (
    SURFACE_TOLERANCE_M2,
    build_dpe_index,
    classify_match,
    classify_match_indexed,
    dedup_dpe,
    match_mutation,
)

# A DPE candidate geocoded ~8 m from the reference point below (within the 15 m
# ADR 0003 threshold): 0.0001 deg latitude ~= 11 m, so half that.
_REF_LAT, _REF_LON = 43.4832, -1.5586


def _dpe(
    numero,
    adresse="",
    lat=None,
    lon=None,
    surface=None,
    *,
    etiquette=None,
    ges=None,
    type_batiment=None,
    periode=None,
    date_etablissement=None,
):
    return {
        "numero_dpe": numero,
        "adresse_normalisee": adresse,
        "lat": lat,
        "lon": lon,
        "surface_habitable_logement": surface,
        "etiquette_dpe": etiquette,
        "etiquette_ges": ges,
        "type_batiment": type_batiment,
        "periode_construction": periode,
        "date_etablissement_dpe": date_etablissement,
    }


def _mutation(adresse="", lat=None, lon=None, surface=None):
    return {
        "adresse_normalisee": adresse,
        "lat": lat,
        "lon": lon,
        "surface": surface,
    }


class TestNoCandidates:
    def test_empty_candidate_list_is_non_trouve(self):
        result = classify_match(_mutation("10 RUE DU MOULIN"), [], 15)
        assert result.status == "non_trouve"
        assert result.numero_dpe is None

    def test_match_mutation_returns_bare_status_string(self):
        assert match_mutation(_mutation("10 RUE DU MOULIN"), [], 15) == "non_trouve"


class TestDedupDpe:
    """`dedup_dpe` (brique B, spec §4) collapse les DPE redondants d'une commune :
    meme `adresse_normalisee` exacte + meme signature analytique/bati ->
    un seul garde (le plus recent). Adresse vide : jamais groupee."""

    _SIG = dict(
        surface=44.2, etiquette="D", ges="D", type_batiment="appartement", periode="2013-2021"
    )

    def test_three_identical_dpe_collapse_to_the_most_recent(self):
        cands = [
            _dpe("D1", "5 RUE DES PECHEURS", date_etablissement="2022-03-01", **self._SIG),
            _dpe("D2", "5 RUE DES PECHEURS", date_etablissement="2024-09-15", **self._SIG),
            _dpe("D3", "5 RUE DES PECHEURS", date_etablissement="2023-01-20", **self._SIG),
        ]
        kept = dedup_dpe(cands)
        assert [d["numero_dpe"] for d in kept] == ["D2"]

    def test_different_periode_construction_stays_distinct(self):
        cands = [
            _dpe("D1", "5 RUE DES PECHEURS", date_etablissement="2022-03-01", **self._SIG),
            _dpe(
                "D2",
                "5 RUE DES PECHEURS",
                date_etablissement="2022-03-01",
                surface=44.2,
                etiquette="D",
                ges="D",
                type_batiment="appartement",
                periode="1948-1974",
            ),
        ]
        assert {d["numero_dpe"] for d in dedup_dpe(cands)} == {"D1", "D2"}

    def test_surface_within_rounding_tolerance_is_same_bucket(self):
        # 44.24 and 44.19 both round to 44.2 at 1 decimal.
        sig = dict(etiquette="D", ges="D", type_batiment="appartement", periode="2013-2021")
        cands = [
            _dpe("D1", "5 RUE DES PECHEURS", date_etablissement="2022-03-01", surface=44.24, **sig),
            _dpe("D2", "5 RUE DES PECHEURS", date_etablissement="2024-01-01", surface=44.19, **sig),
        ]
        assert [d["numero_dpe"] for d in dedup_dpe(cands)] == ["D2"]

    def test_empty_address_dpe_are_never_grouped(self):
        cands = [
            _dpe("D1", "", date_etablissement="2022-03-01", **self._SIG),
            _dpe("D2", "", date_etablissement="2024-01-01", **self._SIG),
        ]
        assert {d["numero_dpe"] for d in dedup_dpe(cands)} == {"D1", "D2"}

    def test_date_tie_broken_by_numero_dpe_max(self):
        cands = [
            _dpe("AAA", "5 RUE DES PECHEURS", date_etablissement="2022-03-01", **self._SIG),
            _dpe("ZZZ", "5 RUE DES PECHEURS", date_etablissement="2022-03-01", **self._SIG),
        ]
        assert [d["numero_dpe"] for d in dedup_dpe(cands)] == ["ZZZ"]

    def test_different_addresses_not_merged(self):
        cands = [
            _dpe("D1", "5 RUE DES PECHEURS", date_etablissement="2022-03-01", **self._SIG),
            _dpe("D2", "7 RUE DES PECHEURS", date_etablissement="2022-03-01", **self._SIG),
        ]
        assert {d["numero_dpe"] for d in dedup_dpe(cands)} == {"D1", "D2"}

    def test_empty_input_returns_empty(self):
        assert dedup_dpe([]) == []


class TestPass1ExactText:
    def test_single_exact_address_is_trouve(self):
        candidates = [
            _dpe("D1", "10 RUE DU MOULIN"),
            _dpe("D2", "12 RUE DU MOULIN"),
        ]
        result = classify_match(_mutation("10 RUE DU MOULIN"), candidates, 15)
        assert result.status == "trouve"
        assert result.numero_dpe == "D1"
        assert result.methode == "texte_exact"

    def test_no_exact_address_and_no_coords_is_non_trouve(self):
        candidates = [_dpe("D1", "99 AVENUE DE LA PLAGE")]
        result = classify_match(_mutation("10 RUE DU MOULIN"), candidates, 15)
        assert result.status == "non_trouve"

    def test_empty_mutation_address_does_not_match_empty_candidate_address(self):
        candidates = [_dpe("D1", "")]
        result = classify_match(_mutation(""), candidates, 15)
        assert result.status == "non_trouve"

    def test_multiple_exact_addresses_resolved_by_surface(self):
        # Collective building: two DPE at the same normalized street address.
        candidates = [
            _dpe("D1", "5 RUE DES PECHEURS", surface=42.0),
            _dpe("D2", "5 RUE DES PECHEURS", surface=88.0),
        ]
        result = classify_match(_mutation("5 RUE DES PECHEURS", surface=87.0), candidates, 15)
        assert result.status == "trouve"
        assert result.numero_dpe == "D2"
        assert result.methode == "texte_exact_surface"

    def test_multiple_exact_addresses_surface_not_discriminant_is_ambigu(self):
        candidates = [
            _dpe("D1", "5 RUE DES PECHEURS", surface=86.0),
            _dpe("D2", "5 RUE DES PECHEURS", surface=88.0),
        ]
        result = classify_match(_mutation("5 RUE DES PECHEURS", surface=87.0), candidates, 15)
        assert result.status == "ambigu"
        assert result.numero_dpe is None

    def test_multiple_exact_addresses_surface_missing_is_ambigu(self):
        candidates = [
            _dpe("D1", "5 RUE DES PECHEURS", surface=42.0),
            _dpe("D2", "5 RUE DES PECHEURS", surface=88.0),
        ]
        result = classify_match(_mutation("5 RUE DES PECHEURS", surface=None), candidates, 15)
        assert result.status == "ambigu"


class TestPass2Distance:
    def test_single_dpe_within_threshold_is_trouve(self):
        near = _dpe("D1", "AUTRE LIBELLE", lat=_REF_LAT + 0.00005, lon=_REF_LON, surface=50.0)
        result = classify_match(
            _mutation("10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=50.0), [near], 15
        )
        assert result.status == "trouve"
        assert result.numero_dpe == "D1"
        assert result.methode == "distance"

    def test_dpe_beyond_threshold_is_non_trouve(self):
        far = _dpe("D1", "AUTRE LIBELLE", lat=_REF_LAT + 0.01, lon=_REF_LON)
        result = classify_match(
            _mutation("10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON), [far], 15
        )
        assert result.status == "non_trouve"

    def test_mutation_without_coords_cannot_use_distance_pass(self):
        near = _dpe("D1", "AUTRE LIBELLE", lat=_REF_LAT, lon=_REF_LON)
        result = classify_match(_mutation("10 RUE DU MOULIN", lat=None, lon=None), [near], 15)
        assert result.status == "non_trouve"

    def test_multiple_dpe_within_threshold_resolved_by_surface(self):
        candidates = [
            _dpe("D1", "", lat=_REF_LAT, lon=_REF_LON, surface=40.0),
            _dpe("D2", "", lat=_REF_LAT + 0.00003, lon=_REF_LON, surface=75.0),
        ]
        result = classify_match(
            _mutation("10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=74.0),
            candidates,
            15,
        )
        assert result.status == "trouve"
        assert result.numero_dpe == "D2"
        assert result.methode == "distance_surface"

    def test_multiple_dpe_within_threshold_equal_surface_is_ambigu(self):
        candidates = [
            _dpe("D1", "", lat=_REF_LAT, lon=_REF_LON, surface=74.0),
            _dpe("D2", "", lat=_REF_LAT + 0.00003, lon=_REF_LON, surface=75.0),
        ]
        result = classify_match(
            _mutation("10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=74.5),
            candidates,
            15,
        )
        assert result.status == "ambigu"

    def test_threshold_is_a_parameter_not_hardcoded(self):
        # ~8 m apart: inside a 15 m threshold, outside a 3 m one.
        near = _dpe("D1", "", lat=_REF_LAT + 0.00005, lon=_REF_LON, surface=50.0)
        mutation = _mutation("10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=50.0)
        assert classify_match(mutation, [near], 15).status == "trouve"
        assert classify_match(mutation, [near], 3).status == "non_trouve"


class TestSurfaceTolerance:
    def test_tolerance_constant_is_two_square_meters(self):
        assert SURFACE_TOLERANCE_M2 == 2.0

    def test_surface_exactly_on_tolerance_edge_counts_as_match(self):
        candidates = [
            _dpe("D1", "5 RUE DES PECHEURS", surface=40.0),
            _dpe("D2", "5 RUE DES PECHEURS", surface=100.0),
        ]
        result = classify_match(_mutation("5 RUE DES PECHEURS", surface=42.0), candidates, 15)
        assert result.status == "trouve"
        assert result.numero_dpe == "D1"


class TestEveryMutationEndsInExactlyOneState:
    @pytest.mark.parametrize(
        "mutation, candidates",
        [
            (_mutation("10 RUE A"), []),
            (_mutation("10 RUE A"), [_dpe("D1", "10 RUE A")]),
            (
                _mutation("10 RUE A", lat=_REF_LAT, lon=_REF_LON, surface=50.0),
                [
                    _dpe("D1", "", lat=_REF_LAT, lon=_REF_LON, surface=50.0),
                    _dpe("D2", "", lat=_REF_LAT, lon=_REF_LON, surface=50.0),
                ],
            ),
        ],
    )
    def test_status_always_in_the_three_state_vocabulary(self, mutation, candidates):
        assert match_mutation(mutation, candidates, 15) in {"trouve", "non_trouve", "ambigu"}


class TestIndexedMatchesReferenceImplementation:
    """`classify_match_indexed` (grille spatiale, utilise par 04_join.py sur les
    grosses communes) doit rendre EXACTEMENT le meme resultat que la reference
    `classify_match` -- l'index n'est qu'une optimisation."""

    # DPE geocodes autour de _REF (~0.0001 deg = 11 m de pas) + variantes texte/surface.
    _CANDIDATES = [
        _dpe("A", "10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=50.0),
        _dpe("B", "10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=95.0),
        _dpe("C", "12 RUE DU MOULIN", lat=_REF_LAT + 0.00004, lon=_REF_LON, surface=64.0),
        _dpe("D", "", lat=_REF_LAT + 0.0005, lon=_REF_LON + 0.0005, surface=30.0),
        _dpe("E", "3 QUAI DES CORSAIRES", lat=None, lon=None, surface=70.0),
        _dpe("F", "12 RUE DU MOULIN", lat=_REF_LAT - 0.00003, lon=_REF_LON, surface=200.0),
    ]

    _MUTATIONS = [
        _mutation("10 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=94.0),
        _mutation("12 RUE DU MOULIN", lat=_REF_LAT, lon=_REF_LON, surface=64.5),
        _mutation("INCONNUE", lat=_REF_LAT, lon=_REF_LON, surface=64.5),
        _mutation("3 QUAI DES CORSAIRES", lat=None, lon=None, surface=70.0),
        _mutation("", lat=_REF_LAT + 0.0005, lon=_REF_LON + 0.0005, surface=30.0),
        _mutation("LOIN", lat=_REF_LAT + 1.0, lon=_REF_LON + 1.0, surface=30.0),
    ]

    @pytest.mark.parametrize("seuil", [3, 15, 30])
    def test_same_result_as_reference_on_every_mutation(self, seuil):
        index = build_dpe_index(self._CANDIDATES, seuil)
        for mutation in self._MUTATIONS:
            assert classify_match_indexed(mutation, index) == classify_match(
                mutation, self._CANDIDATES, seuil
            )

    def test_empty_index_is_non_trouve(self):
        index = build_dpe_index([], 15)
        assert classify_match_indexed(_mutation("10 RUE A"), index).status == "non_trouve"
