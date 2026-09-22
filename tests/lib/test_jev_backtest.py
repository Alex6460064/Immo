"""Tests for pipeline.lib.jev_backtest -- backtest Jev sur les mutations `trouve`
(#36, spec #33), logique PURE. Aucun reseau : les reponses Jev sont des reponses
normalisees figees, comme dans test_jev_decision.py / test_jev_client.py.
"""

import pytest

from pipeline.lib.jev_backtest import (
    REGIME_ISOLE,
    REGIME_MULTI,
    BacktestCase,
    bucket_by,
    build_cases,
    evaluate_case,
    regime,
    sample,
    stratified_sample,
    summarize,
)
from pipeline.lib.jev_decision import GARDE_KEY, candidate_ref

_REF_LAT, _REF_LON = 43.4832, -1.5586


def _mutation(no_disposition="000001", adresse="10 RUE A", surface=50.0, **extra):
    return {
        "adresse_normalisee": adresse,
        "adresse_brute": adresse,
        "lat": _REF_LAT,
        "lon": _REF_LON,
        "surface": surface,
        "type_local": "Appartement",
        "date_mutation": "2023-04-12",
        "code_insee": "64122",
        "no_disposition": no_disposition,
        "prix": 300000.0,
        "match_status": "trouve",
        **extra,
    }


def _dpe(numero, adresse="10 RUE A", surface=50.0, code_insee="64122", **extra):
    return {
        "numero_dpe": numero,
        "adresse_normalisee": adresse,
        "adresse_brut": adresse,
        "lat": _REF_LAT,
        "lon": _REF_LON,
        "surface_habitable_logement": surface,
        "etiquette_dpe": "C",
        "etiquette_ges": None,
        "type_batiment": "appartement",
        "periode_construction": None,
        "date_etablissement_dpe": "2022-01-01",
        "code_insee_ban": code_insee,
        **extra,
    }


def _answers(scores, *, garde=True, confiance=0.95):
    answers = {
        candidate_ref(i): {"score": s, "confidence": confiance} for i, s in enumerate(scores)
    }
    answers[GARDE_KEY] = {"noul": garde}
    return answers


class TestRegime:
    def test_single_candidate_is_isole(self):
        assert regime([{"numero_dpe": "D1"}]) == REGIME_ISOLE

    def test_multiple_candidates_is_multi(self):
        assert regime([{"numero_dpe": "D1"}, {"numero_dpe": "D2"}]) == REGIME_MULTI

    def test_empty_pool_is_isole(self):
        assert regime([]) == REGIME_ISOLE


class TestBuildCases:
    def test_single_dpe_gives_an_isole_case_with_known_truth(self):
        matched = [_mutation()]
        dpe_rows = [_dpe("D1")]
        cases, incoherences = build_cases(matched, dpe_rows)
        assert incoherences == 0
        assert len(cases) == 1
        assert cases[0].verite_numero_dpe == "D1"
        assert cases[0].regime == REGIME_ISOLE

    def test_surface_tiebreak_gives_a_multi_case(self):
        matched = [_mutation(surface=50.5)]
        dpe_rows = [
            _dpe("IN1", surface=50.0, etiquette="C"),
            _dpe("IN2", surface=95.0, etiquette="F"),
        ]
        cases, incoherences = build_cases(matched, dpe_rows)
        assert incoherences == 0
        assert len(cases) == 1
        assert cases[0].regime == REGIME_MULTI
        assert cases[0].verite_numero_dpe == "IN1"
        assert {d["numero_dpe"] for d in cases[0].candidats} == {"IN1", "IN2"}

    def test_non_trouve_mutations_are_skipped(self):
        matched = [_mutation(match_status="non_trouve")]
        cases, incoherences = build_cases(matched, [_dpe("D1")])
        assert cases == []
        assert incoherences == 0

    def test_ambiguous_rematch_counts_as_incoherence(self):
        """La mutation est marquee `trouve` dans dvf_dpe_matched, mais le rematch
        (dpe_clean plus recent) la reclasse `ambigu` -- signe de desynchronisation
        entre les deux parquets, jamais ignore en silence."""
        matched = [_mutation(surface=200.0)]
        dpe_rows = [
            _dpe("D1", surface=50.0, etiquette="C"),
            _dpe("D2", surface=95.0, etiquette="F"),
        ]
        cases, incoherences = build_cases(matched, dpe_rows)
        assert cases == []
        assert incoherences == 1

    def test_scopes_dpe_by_commune(self):
        matched = [_mutation(code_insee="64122")]
        dpe_rows = [_dpe("OTHER", code_insee="64999")]
        cases, incoherences = build_cases(matched, dpe_rows)
        assert cases == []
        assert incoherences == 1


class TestSample:
    def test_stable_across_runs(self):
        cases = [
            BacktestCase(_mutation(str(i)), [_dpe(f"D{i}")], f"D{i}", REGIME_ISOLE)
            for i in range(10)
        ]
        first = sample(cases, 3)
        second = sample(cases, 3)
        assert [c.mutation["no_disposition"] for c in first] == [
            c.mutation["no_disposition"] for c in second
        ]
        assert len(first) == 3

    def test_zero_or_negative_limit_returns_everything(self):
        cases = [BacktestCase(_mutation(), [_dpe("D1")], "D1", REGIME_ISOLE)]
        assert len(sample(cases, 0)) == 1


class TestStratifiedSample:
    def test_keeps_both_regimes_even_when_one_dominates(self):
        isoles = [
            BacktestCase(_mutation(str(i)), [_dpe(f"I{i}")], f"I{i}", REGIME_ISOLE)
            for i in range(20)
        ]
        multi = [
            BacktestCase(
                _mutation(f"m{i}"), [_dpe(f"M{i}a"), _dpe(f"M{i}b")], f"M{i}a", REGIME_MULTI
            )
            for i in range(2)
        ]
        retenus = stratified_sample(isoles + multi, 5)
        assert sum(1 for c in retenus if c.regime == REGIME_MULTI) == 2
        assert sum(1 for c in retenus if c.regime == REGIME_ISOLE) == 5


class TestEvaluateCase:
    def _case(self, regime_=REGIME_MULTI):
        return BacktestCase(_mutation(), [_dpe("D1"), _dpe("D2")], "D1", regime_)

    def test_correct_top1_true_even_when_undecided(self):
        """Le meilleur candidat est le bon, mais le score est trop bas pour `decide` --
        `correct_top1` doit rester vrai (c'est le point du backtest : mesurer la
        courbe independamment du seuil actuel)."""
        record = evaluate_case(
            self._case(), _answers([0.4, 0.1]), score_min=1.5, marge_min=0.5, confiance_min=0.5
        )
        assert record.correct_top1 is True
        assert record.resolu is False
        assert record.correct_a_seuil is None

    def test_correct_top1_false_when_the_wrong_candidate_wins(self):
        record = evaluate_case(
            self._case(), _answers([0.1, 0.4]), score_min=0.0, marge_min=0.0, confiance_min=0.0
        )
        assert record.correct_top1 is False

    def test_resolved_and_correct_at_threshold(self):
        record = evaluate_case(
            self._case(), _answers([2.0, 0.1]), score_min=1.5, marge_min=0.5, confiance_min=0.5
        )
        assert record.resolu is True
        assert record.correct_a_seuil is True
        assert record.correct_top1 is True

    def test_resolved_but_wrong_at_threshold_is_the_dangerous_case(self):
        """Le cas que le backtest existe pour detecter : `decide` tranche, et se
        trompe. `correct_top1` et `correct_a_seuil` doivent tous deux etre faux."""
        record = evaluate_case(
            self._case(), _answers([0.1, 2.0]), score_min=1.5, marge_min=0.5, confiance_min=0.5
        )
        assert record.resolu is True
        assert record.correct_a_seuil is False
        assert record.correct_top1 is False


class TestBucketBy:
    def test_accuracy_computed_per_bucket(self):
        base = evaluate_case(
            BacktestCase(_mutation(), [_dpe("D1"), _dpe("D2")], "D1", REGIME_MULTI),
            _answers([2.0, 0.1]),
            score_min=0.0,
            marge_min=0.0,
            confiance_min=0.0,
        )
        wrong = evaluate_case(
            BacktestCase(_mutation("2"), [_dpe("D1"), _dpe("D2")], "D2", REGIME_MULTI),
            _answers([2.0, 0.1]),
            score_min=0.0,
            marge_min=0.0,
            confiance_min=0.0,
        )
        buckets = bucket_by([base, wrong], "confiance", edges=(0.0, 0.5, 1.0 + 1e-9))
        top_bucket = [b for b in buckets if b.lo == 0.5][0]
        assert top_bucket.n == 2
        assert top_bucket.exactitude == pytest.approx(0.5)

    def test_empty_bucket_has_zero_count_not_omitted(self):
        buckets = bucket_by([], "confiance", edges=(0.0, 0.5, 1.0 + 1e-9))
        assert all(b.n == 0 for b in buckets)
        assert len(buckets) == 2


class TestSummarize:
    def test_splits_by_regime_and_reports_residual_error(self):
        correct = evaluate_case(
            BacktestCase(_mutation(), [_dpe("D1"), _dpe("D2")], "D1", REGIME_MULTI),
            _answers([2.0, 0.1]),
            score_min=1.5,
            marge_min=0.5,
            confiance_min=0.5,
        )
        wrong = evaluate_case(
            BacktestCase(_mutation("2"), [_dpe("D1"), _dpe("D2")], "D2", REGIME_MULTI),
            _answers([2.0, 0.1]),
            score_min=1.5,
            marge_min=0.5,
            confiance_min=0.5,
        )
        out = summarize([correct, wrong])
        assert out[REGIME_MULTI]["n"] == 2
        assert out[REGIME_MULTI]["resolus"] == 2
        assert out[REGIME_MULTI]["exactitude_a_seuil"] == pytest.approx(0.5)
        assert out[REGIME_MULTI]["taux_erreur_residuel_a_seuil"] == pytest.approx(0.5)
        assert out[REGIME_ISOLE]["n"] == 0
        assert out[REGIME_ISOLE]["taux_erreur_residuel_a_seuil"] is None
