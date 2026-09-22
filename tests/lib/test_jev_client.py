"""Tests for pipeline.lib.jev_client -- SEULE frontiere reseau de la brique Jev (#35).

Aucun appel reel : le client est teste via un FAUX `ask`, qui rend la charge utile
documentee de l'API HTTP. La CI n'appelle donc jamais Jev, et n'a besoin d'aucune
cle (critere d'acceptation #35).

Ce qui est verrouille ici : le cache sert les cles connues, seules les cles absentes
declenchent un appel, un changement de version de modele ou de questions invalide
l'entree au lieu de la reutiliser, et l'absence de cle API degrade sans lever.
"""

import pytest

from pipeline.lib.jev_client import (
    VERDICT_COLUMNS,
    VerdictCache,
    judge_cases,
    normalize_response,
)
from pipeline.lib.jev_decision import (
    GARDE_KEY,
    JEV_MODEL,
    QUESTIONS_VERSION,
    cache_key,
    candidate_ref,
)

_REF_LAT, _REF_LON = 43.4832, -1.5586


def _dpe(numero, adresse_brut="10 AV DE LA PLAGE", etiquette="C"):
    return {
        "numero_dpe": numero,
        "adresse_brut": adresse_brut,
        "lat": _REF_LAT,
        "lon": _REF_LON,
        "etiquette_dpe": etiquette,
        "etiquette_ges": None,
        "type_batiment": None,
        "periode_construction": None,
    }


def _mutation(no_disposition="000001"):
    return {
        "adresse_brute": "10 AV DE LA PLAGE BAT A",
        "lat": _REF_LAT,
        "lon": _REF_LON,
        "date_mutation": "2023-04-12",
        "code_insee": "64122",
        "no_disposition": no_disposition,
        "prix": 450000.0,
    }


def _case(no_disposition="000001", entry_status="ambigu"):
    return {
        "mutation": _mutation(no_disposition),
        "candidats": [
            _dpe("D1", "10 AV DE LA PLAGE BAT A"),
            _dpe("D2", "10 AV DE LA PLAGE BAT B", "F"),
        ],
        "entry_status": entry_status,
    }


def _payload(scores, *, garde=True, confiance=0.95, model=JEV_MODEL, input_tokens=1500):
    """Charge utile au format documente de l'API HTTP (docs.typesafe.ai/api)."""
    answers = {
        candidate_ref(i): {"type": "score", "score": s, "confidence": confiance}
        for i, s in enumerate(scores)
    }
    answers[GARDE_KEY] = {"type": "noul", "noul": garde}
    return {
        "model": model,
        "answers": answers,
        "usage": {"input_tokens": input_tokens, "output_tokens": 0},
    }


class _FakeAsk:
    """Faux client : compte les appels et rend une reponse figee."""

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else _payload([2.0, 0.1])
        self.calls = []

    def __call__(self, *, state, questions, model):
        self.calls.append({"state": state, "questions": questions, "model": model})
        # L'API echoue le modele effectivement servi : un faux client qui rendrait
        # toujours le modele epingle masquerait le garde de `normalize_response`.
        return {**self.payload, "model": model}


class TestNormalizeResponse:
    """Le module pur attend des reponses normalisees. La traduction vit ici, et
    accepte aussi bien la charge utile HTTP brute qu'un objet SDK."""

    def test_http_payload_is_normalized_to_scores_and_guard(self):
        answers, modele, tokens = normalize_response(_payload([1.8, 0.2], confiance=0.9))
        assert answers[candidate_ref(0)] == {"score": 1.8, "confidence": 0.9}
        assert answers[GARDE_KEY] == {"noul": True}
        assert modele == JEV_MODEL
        assert tokens == 1500

    def test_sdk_object_shape_is_normalized_the_same_way(self):
        """Forme reelle du `SystemOneResponse` du SDK (0.7.1) : `.model`, `.answers`,
        `.usage` -- les memes noms de champs que la charge utile HTTP, portes par des
        objets. La page SDK de la doc decrit des accesseurs `.scores` / `.nouls` qui
        n'existent pas sur cette version : le faux suit le SDK installe."""

        class _Obj:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        response = _Obj(
            model=JEV_MODEL,
            answers={
                candidate_ref(0): _Obj(type="score", score=1.8, confidence=0.9),
                GARDE_KEY: _Obj(type="noul", noul=True),
            },
            usage=_Obj(input_tokens=1500, output_tokens=0),
        )

        answers, modele, tokens = normalize_response(response)
        assert answers[candidate_ref(0)] == {"score": 1.8, "confidence": 0.9}
        assert answers[GARDE_KEY] == {"noul": True}
        assert modele == JEV_MODEL
        assert tokens == 1500

    def test_a_resolved_model_differing_from_the_pinned_one_is_loud_not_silent(self):
        """Reutiliser un verdict rendu par un autre modele que celui epingle serait
        exactement la reutilisation silencieuse que le spec interdit."""
        with pytest.raises(ValueError, match="jev-9.9.9"):
            normalize_response(_payload([2.0], model="jev-9.9.9"), expected_model=JEV_MODEL)


class TestJudgeCases:
    def test_every_case_is_asked_once_and_gets_a_verdict(self):
        ask = _FakeAsk()
        run = judge_cases([_case("000001"), _case("000002")], ask=ask, cache=VerdictCache())
        assert len(ask.calls) == 2
        assert run.appels == 2
        assert [v.status for v in run.verdicts] == ["resolu_jev", "resolu_jev"]

    def test_the_state_sent_carries_no_numero_dpe(self):
        ask = _FakeAsk()
        judge_cases([_case()], ask=ask, cache=VerdictCache())
        assert "D1" not in repr(ask.calls[0]["state"])

    def test_the_pinned_model_is_the_one_requested(self):
        ask = _FakeAsk()
        judge_cases([_case()], ask=ask, cache=VerdictCache())
        assert ask.calls[0]["model"] == JEV_MODEL

    def test_a_cached_key_triggers_no_call(self):
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case()], ask=ask, cache=cache)
        run = judge_cases([_case()], ask=ask, cache=cache)
        assert len(ask.calls) == 1
        assert run.appels == 0
        assert run.servis_par_cache == 1
        assert run.verdicts[0].status == "resolu_jev"

    def test_only_the_missing_keys_are_called(self):
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case("000001")], ask=ask, cache=cache)
        judge_cases([_case("000001"), _case("000002")], ask=ask, cache=cache)
        assert len(ask.calls) == 2

    def test_a_model_version_change_invalidates_the_cached_entry(self):
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case()], ask=ask, cache=cache)
        judge_cases([_case()], ask=ask, cache=cache, model="jev-9.9.9")
        assert len(ask.calls) == 2

    def test_a_questions_version_change_invalidates_the_cached_entry(self):
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case()], ask=ask, cache=cache)
        judge_cases([_case()], ask=ask, cache=cache, questions_version="v999")
        assert len(ask.calls) == 2

    def test_an_empty_pool_is_never_sent_to_the_model(self):
        ask = _FakeAsk()
        case = {"mutation": _mutation(), "candidats": [], "entry_status": "ambigu"}
        run = judge_cases([case], ask=ask, cache=VerdictCache())
        assert ask.calls == []
        assert run.verdicts[0].status == "ambigu"
        assert run.verdicts[0].motif == "pool_vide"

    def test_usage_is_accumulated_for_the_cost_measurement(self):
        ask = _FakeAsk(_payload([2.0, 0.1], input_tokens=1200))
        run = judge_cases([_case("000001"), _case("000002")], ask=ask, cache=VerdictCache())
        assert run.input_tokens == 2400

    def test_cached_cases_do_not_inflate_the_token_count(self):
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case()], ask=ask, cache=cache)
        run = judge_cases([_case()], ask=ask, cache=cache)
        assert run.input_tokens == 0


class TestDegradationWithoutApiKey:
    """Sans cle, l'etape journalise et passe : le pipeline produit les quatre etats
    actuels. Jamais d'echec dur (critere d'acceptation #35)."""

    def test_no_client_keeps_every_entry_status_without_raising(self):
        run = judge_cases([_case(), _case("000002")], ask=None, cache=VerdictCache())
        assert [v.status for v in run.verdicts] == ["ambigu", "ambigu"]
        assert all(v.motif == "sans_cle" for v in run.verdicts)
        assert run.appels == 0

    def test_no_client_still_serves_what_the_cache_already_holds(self):
        """Un clone frais sans cle doit reproduire les verdicts deja versionnes."""
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case()], ask=ask, cache=cache)
        run = judge_cases([_case()], ask=None, cache=cache)
        assert run.verdicts[0].status == "resolu_jev"
        assert run.servis_par_cache == 1


class TestVerdictCachePersistence:
    def test_a_saved_cache_reloads_identical_verdicts(self, tmp_path):
        ask = _FakeAsk()
        cache = VerdictCache()
        judge_cases([_case()], ask=ask, cache=cache)
        path = tmp_path / "jev_verdicts.parquet"
        cache.save(path)

        run = judge_cases([_case()], ask=_FakeAsk(), cache=VerdictCache.load(path))
        assert run.appels == 0
        assert run.verdicts[0].status == "resolu_jev"
        assert run.verdicts[0].numero_dpe == "D1"

    def test_loading_a_missing_file_gives_an_empty_cache(self, tmp_path):
        assert len(VerdictCache.load(tmp_path / "absent.parquet")) == 0

    def test_persisted_rows_carry_the_resolved_model_for_audit(self, tmp_path):
        cache = VerdictCache()
        judge_cases([_case()], ask=_FakeAsk(), cache=cache)
        path = tmp_path / "jev_verdicts.parquet"
        cache.save(path)
        rows = list(VerdictCache.load(path).rows())
        assert rows[0]["modele"] == JEV_MODEL
        assert rows[0]["questions_version"] == QUESTIONS_VERSION
        assert set(VERDICT_COLUMNS) <= set(rows[0])

    def test_the_cache_key_is_the_one_the_pure_module_computes(self):
        cache = VerdictCache()
        case = _case()
        judge_cases([case], ask=_FakeAsk(), cache=cache)
        expected = cache_key(
            case["mutation"],
            case["candidats"],
            model=JEV_MODEL,
            questions_version=QUESTIONS_VERSION,
        )
        assert cache.get(expected) is not None
