"""Backtest Jev sur les mutations `trouve` (#36, spec #33) -- logique PURE.

Aucun reseau, aucun DuckDB, aucune cle API : ce module tourne en CI tel quel.
`pipeline/jev_backtest.py` fait le reseau et l'I/O ; tout ce qui est testable vit ici.

--- Principe ---
Une mutation `trouve` porte une identite DPE connue avec certitude -- verite
terrain gratuite. On reconstruit, via `classify_with_backtest_pool`
(`pipeline/lib/match_dvf_dpe.py`), le pool de candidats que Jev verrait si cette
identite etait masquee, puis on compare le candidat que Jev prefere
(`jev_decision.best_candidate`, calcule AVANT tout seuil) a la reponse connue.

--- Deux regimes (note de calibration sur `jev_decision.decide`) ---
Un pool a UN candidat (`texte_exact` / `distance` singuliers) n'a pas de second
score : `marge == score`, seul `SCORE_MIN` peut mordre. Un pool a PLUSIEURS
candidats (departage `*_surface`) a une vraie marge : `SCORE_MIN` ET `MARGE_MIN`
mordent, et c'est la structure exacte d'un cas `ambigu` reel. Les deux regimes ne
partagent pas la meme politique de fait -- une courbe qui les melange induirait en
erreur. `regime(pool)` les distingue ; le rapport les tranche separement.
"""

from __future__ import annotations

from typing import NamedTuple

from pipeline.lib.jev_decision import (
    JEV_MODEL,
    QUESTIONS_VERSION,
    best_candidate,
    cache_key,
    decide,
)
from pipeline.lib.match_distance import DISTANCE_THRESHOLD_M
from pipeline.lib.match_dvf_dpe import build_dpe_index, classify_with_backtest_pool

REGIME_ISOLE = "isole"
REGIME_MULTI = "multi"


class BacktestCase(NamedTuple):
    """Un cas de backtest : une mutation `trouve`, son pool masque, et la reponse
    connue (verite terrain) qu'on ne soumet jamais a Jev."""

    mutation: dict
    candidats: list[dict]
    verite_numero_dpe: str
    regime: str


def regime(candidats: list[dict]) -> str:
    """`isole` (pool a 1 candidat, pas de distractor) ou `multi` (>= 2, une vraie
    marge a departager) -- voir la note de calibration en tete de module."""
    return REGIME_ISOLE if len(candidats) <= 1 else REGIME_MULTI


def build_cases(matched: list[dict], dpe_rows: list[dict]) -> tuple[list[BacktestCase], int]:
    """Reconstruit, pour chaque mutation `trouve`, le pool masque + la reponse
    connue. Retourne `(cas, nb_incoherences)`.

    Une incoherence = une mutation `trouve` que le rematch (`classify_with_backtest_pool`)
    ne reclasse pas `trouve`, ou dont il ne peut identifier aucun candidat (pool vide) --
    signe que `dvf_dpe_matched` et `dpe_clean` ne viennent pas du meme run. Comptee et
    signalee, jamais ignoree (miroir de `pipeline/04c_jev_disambiguate.build_cases`).
    """
    by_commune: dict[str, list[dict]] = {}
    for dpe in dpe_rows:
        code = (dpe.get("code_insee_ban") or "").strip()
        if code:
            by_commune.setdefault(code, []).append(dpe)

    index_by_commune = {
        code: build_dpe_index(rows, DISTANCE_THRESHOLD_M) for code, rows in by_commune.items()
    }
    empty_index = build_dpe_index([], DISTANCE_THRESHOLD_M)

    cases: list[BacktestCase] = []
    incoherences = 0
    for mutation in matched:
        if mutation.get("match_status") != "trouve":
            continue
        code = (mutation.get("code_insee") or "").strip()
        index = index_by_commune.get(code, empty_index)
        result, pool = classify_with_backtest_pool(mutation, index)
        if result.status != "trouve" or not pool:
            incoherences += 1
            continue
        cases.append(
            BacktestCase(
                mutation=mutation,
                candidats=pool,
                verite_numero_dpe=result.numero_dpe,
                regime=regime(pool),
            )
        )
    return cases, incoherences


def sample(cases: list[BacktestCase], limit: int) -> list[BacktestCase]:
    """Echantillon stable : les `limit` cas de plus petite cle de cache (meme
    principe que `04c_jev_disambiguate.sample` -- relancer juge le meme
    echantillon, donc ne repaie aucun appel). `limit <= 0` rend tout."""
    keyed = [
        (
            cache_key(
                case.mutation,
                case.candidats,
                model=JEV_MODEL,
                questions_version=QUESTIONS_VERSION,
            ),
            case,
        )
        for case in cases
    ]
    keyed.sort(key=lambda kc: kc[0])
    return [case for _, case in keyed[:limit]] if limit > 0 else [case for _, case in keyed]


def stratified_sample(cases: list[BacktestCase], limit_par_regime: int) -> list[BacktestCase]:
    """`sample` applique separement a chaque regime, puis reconcatene.

    Sans stratification, un echantillon global serait ecrase par le regime le plus
    frequent (en pratique `isole`, tres majoritaire) et la courbe `multi` -- celle
    qui calibre `MARGE_MIN` -- reposerait sur trop peu de cas.
    """
    par_regime: dict[str, list[BacktestCase]] = {REGIME_ISOLE: [], REGIME_MULTI: []}
    for case in cases:
        par_regime[case.regime].append(case)
    return [
        case
        for r in (REGIME_ISOLE, REGIME_MULTI)
        for case in sample(par_regime[r], limit_par_regime)
    ]


class EvalRecord(NamedTuple):
    """Resultat d'un cas juge, pret pour l'agregation par tranche.

    - `correct_top1` : le candidat prefere par Jev (`best_candidate`, avant seuil)
      est-il le bon -- la mesure INDEPENDANTE de tout seuil.
    - `resolu` / `correct_a_seuil` : ce que `decide`, avec les seuils COURANTS,
      aurait effectivement rendu -- la mesure "au seuil retenu aujourd'hui".
    """

    regime: str
    score: float
    marge: float
    confiance: float
    correct_top1: bool
    resolu: bool
    correct_a_seuil: bool | None


def evaluate_case(
    case: BacktestCase,
    answers: dict,
    *,
    score_min: float,
    marge_min: float,
    confiance_min: float,
) -> EvalRecord:
    """Traduit une reponse Jev (deja normalisee par `jev_client`) en `EvalRecord`,
    en comparant a `case.verite_numero_dpe` -- jamais envoyee au modele."""
    best, score, marge, confiance = best_candidate(answers, case.candidats)
    gagnant = case.candidats[best].get("numero_dpe") if best is not None else None
    correct_top1 = gagnant == case.verite_numero_dpe

    verdict = decide(
        answers,
        case.candidats,
        entry_status="trouve",
        score_min=score_min,
        marge_min=marge_min,
        confiance_min=confiance_min,
    )
    resolu = verdict.status == "resolu_jev"
    correct_a_seuil = (verdict.numero_dpe == case.verite_numero_dpe) if resolu else None

    return EvalRecord(
        regime=case.regime,
        score=score,
        marge=marge,
        confiance=confiance,
        correct_top1=correct_top1,
        resolu=resolu,
        correct_a_seuil=correct_a_seuil,
    )


class Bucket(NamedTuple):
    """Une tranche de la courbe exactitude x confiance (ou x marge) : bornes,
    effectif, et exactitude TOP-1 observee sur la tranche."""

    lo: float
    hi: float
    n: int
    exactitude: float


def _bucket_edges(edges: tuple[float, ...]) -> list[tuple[float, float]]:
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


# Tranches par defaut : le `Score` est dans [0, 2], `confidence` et `marge` dans
# [0, 1] cote confiance mais la marge peut aussi valoir jusqu'a 2 (score plein sur
# un pool isole) -- des tranches fines pres du seuil actuel (0.5) et grossieres
# ailleurs, pour que le rapport lise la zone de decision sans noyer le reste.
DEFAULT_CONFIDENCE_EDGES: tuple[float, ...] = (0.0, 0.25, 0.5, 0.7, 0.85, 0.95, 1.0 + 1e-9)
DEFAULT_MARGIN_EDGES: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0 + 1e-9)


def bucket_by(
    records: list[EvalRecord], key: str, edges: tuple[float, ...] = DEFAULT_CONFIDENCE_EDGES
) -> list[Bucket]:
    """Exactitude TOP-1 par tranche de `key` (`"confiance"` ou `"marge"`), tranches
    demi-ouvertes `[lo, hi)`. Une tranche vide reste dans le rapport a `n=0` --
    un trou dans la courbe est une donnee, pas un absent a masquer."""
    buckets = []
    for lo, hi in _bucket_edges(edges):
        subset = [r for r in records if lo <= getattr(r, key) < hi]
        n = len(subset)
        exactitude = sum(1 for r in subset if r.correct_top1) / n if n else 0.0
        buckets.append(Bucket(lo, hi, n, exactitude))
    return buckets


def summarize(records: list[EvalRecord]) -> dict:
    """Chiffres publiables du backtest (#36) : exactitude TOP-1 par regime,
    exactitude/erreur residuelle au seuil COURANT (celui deja passe a
    `evaluate_case`), et effectifs -- tout ce que le rapport imprime tel quel."""
    out: dict = {}
    for r in (REGIME_ISOLE, REGIME_MULTI):
        subset = [rec for rec in records if rec.regime == r]
        n = len(subset)
        out[r] = {
            "n": n,
            "exactitude_top1": sum(1 for rec in subset if rec.correct_top1) / n if n else 0.0,
        }
        resolus = [rec for rec in subset if rec.resolu]
        out[r]["resolus"] = len(resolus)
        out[r]["exactitude_a_seuil"] = (
            sum(1 for rec in resolus if rec.correct_a_seuil) / len(resolus) if resolus else 0.0
        )
        out[r]["taux_erreur_residuel_a_seuil"] = (
            1.0 - out[r]["exactitude_a_seuil"] if resolus else None
        )
    return out
