"""Tests for pipeline.lib.jev_decision -- module PUR de la brique Jev (#35, spec #33).

Aucun reseau, aucun DuckDB, aucune cle API : la CI execute ce fichier tel quel.

Le seam est volontairement etroit : le module ne connait ni le SDK TypeSafe, ni le
format de reponse HTTP. Il construit l'etat et les questions (dicts au format de
l'API), et tranche a partir de reponses NORMALISEES par le client :

    {"c0": {"score": 1.9, "confidence": 0.93}, ..., "garde": {"noul": True}}

Un test verifie donc un comportement observable -- pour un etat et des reponses
donnes, quel verdict sort -- jamais la forme interne des dicts envoyes.
"""

import pytest

from pipeline.lib.jev_decision import (
    GARDE_KEY,
    JEV_MODEL,
    MARGE_MIN,
    MAX_CANDIDATES,
    QUESTIONS_VERSION,
    SCORE_MIN,
    build_questions,
    build_state,
    cache_key,
    candidate_ref,
    decide,
    pool_fingerprint,
    select_candidates,
)

_REF_LAT, _REF_LON = 43.4832, -1.5586


def _dpe(numero, adresse_brut="", lat=None, lon=None, etiquette=None, **extra):
    return {
        "numero_dpe": numero,
        "adresse_brut": adresse_brut,
        "lat": lat,
        "lon": lon,
        "etiquette_dpe": etiquette,
        "etiquette_ges": None,
        "type_batiment": None,
        "periode_construction": None,
        **extra,
    }


def _mutation(adresse_brute="10 AVENUE DE LA PLAGE", lat=_REF_LAT, lon=_REF_LON, **extra):
    return {
        "adresse_brute": adresse_brute,
        "lat": lat,
        "lon": lon,
        "date_mutation": "2023-04-12",
        "code_insee": "64122",
        "no_disposition": "000001",
        "prix": 450000.0,
        **extra,
    }


def _answers(scores, *, garde=True, confiance=0.95):
    """Reponses normalisees : un score par candidat (dans l'ordre du pool) + le garde."""
    answers = {
        candidate_ref(i): {"score": s, "confidence": confiance} for i, s in enumerate(scores)
    }
    answers[GARDE_KEY] = {"noul": garde}
    return answers


class TestSelectCandidates:
    """Le bornage du pool est fait EN CODE, par distance croissante (spec #33) :
    Jev ne compare jamais deux nombres, et la liste ne doit pas entrer dans la zone
    ou l'exactitude se degrade avec sa longueur."""

    def test_candidates_are_ordered_by_increasing_distance(self):
        loin = _dpe("LOIN", lat=_REF_LAT + 0.001, lon=_REF_LON)
        pres = _dpe("PRES", lat=_REF_LAT + 0.00001, lon=_REF_LON)
        moyen = _dpe("MOYEN", lat=_REF_LAT + 0.0001, lon=_REF_LON)
        selected = select_candidates(_mutation(), [loin, pres, moyen])
        assert [d["numero_dpe"] for d in selected] == ["PRES", "MOYEN", "LOIN"]

    def test_pool_is_capped_at_max_candidates(self):
        pool = [_dpe(f"D{i}", lat=_REF_LAT + i * 0.0001, lon=_REF_LON) for i in range(20)]
        selected = select_candidates(_mutation(), pool)
        assert len(selected) == MAX_CANDIDATES
        assert [d["numero_dpe"] for d in selected] == [f"D{i}" for i in range(MAX_CANDIDATES)]

    def test_candidates_without_coordinates_come_last_in_stable_order(self):
        sans_a, sans_b = _dpe("SANS_A"), _dpe("SANS_B")
        avec = _dpe("AVEC", lat=_REF_LAT + 0.0001, lon=_REF_LON)
        selected = select_candidates(_mutation(), [sans_a, sans_b, avec])
        assert [d["numero_dpe"] for d in selected] == ["AVEC", "SANS_A", "SANS_B"]

    def test_mutation_without_coordinates_keeps_the_pool_order(self):
        pool = [_dpe("A", lat=_REF_LAT, lon=_REF_LON), _dpe("B", lat=_REF_LAT, lon=_REF_LON)]
        selected = select_candidates(_mutation(lat=None, lon=None), pool)
        assert [d["numero_dpe"] for d in selected] == ["A", "B"]

    def test_empty_pool_selects_nothing(self):
        assert select_candidates(_mutation(), []) == []


class TestBuildState:
    """L'etat envoye a Jev se limite au texte que le code ne sait pas lire : les
    adresses brutes. Tout le reste -- surface, distance, dates, type -- est traite
    en code (frontiere code/modele, spec #33). Une limite documentee du modele est
    que l'exactitude chute quand l'entree porte des details hors sujet."""

    def test_state_carries_the_raw_addresses_of_the_mutation_and_the_candidates(self):
        state = build_state(
            _mutation("10 AV DE LA PLAGE RESIDENCE OCEANIC BAT A"),
            [_dpe("D1", "10 AV DE LA PLAGE BAT A"), _dpe("D2", "10 AV DE LA PLAGE BAT B")],
        )
        assert state["mutation"] == "10 AV DE LA PLAGE RESIDENCE OCEANIC BAT A"
        assert [c["adresse"] for c in state["candidats"]] == [
            "10 AV DE LA PLAGE BAT A",
            "10 AV DE LA PLAGE BAT B",
        ]

    def test_candidates_are_referenced_by_position_never_by_numero_dpe(self):
        """Le `numero_dpe` est un identifiant opaque : c'est du bruit pour le modele,
        et le code retrouve le DPE par sa position."""
        state = build_state(_mutation(), [_dpe("2364E1234567X", "10 AV DE LA PLAGE")])
        assert "2364E1234567X" not in repr(state)
        assert state["candidats"][0]["ref"] == candidate_ref(0)

    @pytest.mark.parametrize("champ", ["surface", "prix", "date_mutation", "lat", "lon"])
    def test_state_never_carries_what_the_code_compares_itself(self, champ):
        state = build_state(_mutation(surface=72.0), [_dpe("D1", "10 AV", surface=71.0)])
        assert champ not in repr(state)

    def test_missing_raw_address_becomes_an_empty_string_not_none(self):
        state = build_state(_mutation(adresse_brute=None), [_dpe("D1", None)])
        assert state["mutation"] == ""
        assert state["candidats"][0]["adresse"] == ""


class TestBuildQuestions:
    """Forme arretee au spec : N questions `Score` independantes, une par candidat,
    plus un `Noul` de garde. Pas de `Choice` sur liste longue (exactitude degradee
    avec la longueur), pas de comparaison de nombres ni de dates."""

    def test_one_score_question_per_candidate_plus_the_guard(self):
        questions = build_questions([_dpe("D1"), _dpe("D2"), _dpe("D3")])
        assert set(questions) == {candidate_ref(0), candidate_ref(1), candidate_ref(2), GARDE_KEY}
        assert all(questions[candidate_ref(i)]["type"] == "score" for i in range(3))
        assert questions[GARDE_KEY]["type"] == "noul"

    def test_score_criteria_describe_three_concrete_situations_from_low_to_high(self):
        questions = build_questions([_dpe("D1")])
        criteria = questions[candidate_ref(0)]["criteria"]
        assert len(criteria) == 3
        assert all(isinstance(c, str) and c for c in criteria)

    def test_empty_pool_asks_nothing(self):
        assert build_questions([]) == {}


class TestDecide:
    """Agregation des reponses en verdict : code pur, seuils nommes, jamais de
    nombre magique. Un verdict `resolu_jev` n'est rendu que si le meilleur candidat
    depasse le seuil ET creuse une marge suffisante sur le suivant."""

    def test_clear_winner_above_threshold_resolves_to_resolu_jev(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([2.0, 0.1]), pool, entry_status="ambigu")
        assert verdict.status == "resolu_jev"
        assert verdict.numero_dpe == "D1"
        assert verdict.etiquette_dpe == "C"

    def test_two_close_candidates_keep_the_entry_status(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([1.9, 1.85]), pool, entry_status="ambigu")
        assert verdict.status == "ambigu"
        assert verdict.numero_dpe is None
        assert verdict.motif == "marge_insuffisante"

    def test_best_score_below_threshold_keeps_the_entry_status(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([1.0, 0.1]), pool, entry_status="ambigu")
        assert verdict.status == "ambigu"
        assert verdict.motif == "score_insuffisant"

    def test_low_confidence_keeps_the_entry_status(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([2.0, 0.1], confiance=0.10), pool, entry_status="ambigu")
        assert verdict.status == "ambigu"
        assert verdict.motif == "confiance_insuffisante"

    def test_guard_noul_cancels_a_verdict(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([2.0, 0.1], garde=False), pool, entry_status="ambigu")
        assert verdict.status == "ambigu"
        assert verdict.motif == "garde_noul"

    def test_guard_noul_never_creates_a_verdict(self):
        """Le garde peut annuler, jamais promouvoir : un pool sans gagnant net reste
        indecis meme si le garde dit oui."""
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([1.9, 1.85], garde=True), pool, entry_status="ambigu")
        assert verdict.status == "ambigu"

    def test_single_candidate_needs_no_margin(self):
        verdict = decide(_answers([2.0]), [_dpe("D1", etiquette="C")], entry_status="ambigu")
        assert verdict.status == "resolu_jev"
        assert verdict.numero_dpe == "D1"

    def test_empty_pool_keeps_the_entry_status(self):
        verdict = decide(_answers([]), [], entry_status="ambigu")
        assert verdict.status == "ambigu"
        assert verdict.motif == "pool_vide"

    def test_entry_status_non_trouve_is_preserved_when_undecided(self):
        """La meme machinerie sert au repli D2 (#40) : jamais de fabrication
        d'appariement, l'etat d'entree revient tel quel."""
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([1.0, 0.9]), pool, entry_status="non_trouve")
        assert verdict.status == "non_trouve"

    def test_missing_answer_for_a_candidate_is_treated_as_no_evidence(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        answers = _answers([2.0, 0.1])
        del answers[candidate_ref(1)]
        verdict = decide(answers, pool, entry_status="ambigu")
        assert verdict.status == "resolu_jev"
        assert verdict.numero_dpe == "D1"

    def test_missing_guard_answer_does_not_cancel(self):
        pool = [_dpe("D1", etiquette="C")]
        answers = _answers([2.0])
        del answers[GARDE_KEY]
        assert decide(answers, pool, entry_status="ambigu").status == "resolu_jev"

    def test_verdict_carries_the_score_margin_and_confidence_for_audit(self):
        pool = [_dpe("D1", etiquette="C"), _dpe("D2", etiquette="F")]
        verdict = decide(_answers([2.0, 0.5], confiance=0.88), pool, entry_status="ambigu")
        assert verdict.score == pytest.approx(2.0)
        assert verdict.marge == pytest.approx(1.5)
        assert verdict.confiance == pytest.approx(0.88)

    def test_verdict_carries_the_full_dpe_context_of_the_winner(self):
        pool = [
            _dpe("D1", etiquette="C", etiquette_ges="B", type_batiment="appartement"),
            _dpe("D2", etiquette="F"),
        ]
        verdict = decide(_answers([2.0, 0.1]), pool, entry_status="ambigu")
        assert verdict.etiquette_ges == "B"
        assert verdict.type_batiment == "appartement"

    def test_thresholds_are_named_constants_not_magic_numbers(self):
        assert 0 < SCORE_MIN <= 2
        assert 0 < MARGE_MIN <= 2


class TestCacheKey:
    """Cle = identite de la mutation + empreinte du pool + version du modele +
    version des questions (spec #33). Un changement de l'un quelconque des quatre
    doit invalider l'entree, jamais la reutiliser en silence."""

    def _key(self, mutation=None, pool=None, model=JEV_MODEL, questions=QUESTIONS_VERSION):
        mutation = mutation if mutation is not None else _mutation()
        pool = pool if pool is not None else [_dpe("D1"), _dpe("D2")]
        return cache_key(mutation, pool, model=model, questions_version=questions)

    def test_same_inputs_give_the_same_key(self):
        assert self._key() == self._key()

    def test_a_different_mutation_gives_a_different_key(self):
        assert self._key() != self._key(mutation=_mutation(no_disposition="000002"))

    def test_a_different_pool_gives_a_different_key(self):
        assert self._key() != self._key(pool=[_dpe("D1"), _dpe("D3")])

    def test_a_model_version_change_invalidates_the_key(self):
        assert self._key() != self._key(model="jev-9.9.9")

    def test_a_questions_version_change_invalidates_the_key(self):
        assert self._key() != self._key(questions="v999")

    def test_pool_fingerprint_ignores_candidate_order(self):
        assert pool_fingerprint([_dpe("D1"), _dpe("D2")]) == pool_fingerprint(
            [_dpe("D2"), _dpe("D1")]
        )

    def test_pool_fingerprint_separates_different_pools(self):
        assert pool_fingerprint([_dpe("D1")]) != pool_fingerprint([_dpe("D1"), _dpe("D2")])

    def test_a_changed_candidate_raw_address_invalidates_the_key(self):
        """L'adresse brute du candidat est ce qui est SOUMIS au modele : si un re-run
        de `03_clean_dpe` la corrige, la question change et le verdict cache ne vaut
        plus. L'identite seule du DPE ne suffit donc pas a la cle."""
        assert self._key(pool=[_dpe("D1", "10 AV DE LA PLAGE BAT A")]) != self._key(
            pool=[_dpe("D1", "10 AV DE LA PLAGE BAT B")]
        )

    def test_the_pinned_model_is_a_concrete_version_never_a_floating_alias(self):
        """`jev-latest` derive sans prevenir : la cle de cache ne pourrait plus
        garantir qu'un changement de modele invalide les verdicts (spec #33)."""
        assert JEV_MODEL[-1].isdigit()
        assert "latest" not in JEV_MODEL
