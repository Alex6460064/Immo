"""Brique Jev : logique PURE de desambiguisation DVF x DPE (#35, spec #33).

Aucun reseau, aucun DuckDB, aucune cle API -- ce module tourne en CI tel quel.
La seule frontiere reseau est `pipeline/lib/jev_client.py`.

--- Frontiere code / modele (decision centrale du spec) ---
Jev 1.13 est documente comme peu fiable sur la comparaison de nombres, le
comptage, l'ordre des dates, et son exactitude chute quand l'entree porte des
details hors sujet. Donc :

  - le CODE garde toute la geometrie, l'arithmetique et la chronologie : seuil de
    distance haversine, tolerance de surface +/- 2 m2, comparaison de dates,
    prix/m2 au niveau mutation (ADR 0006), bande de garde-fou, bornage du pool ;
  - JEV ne recoit que du texte a interpreter : l'adresse brute de la mutation et
    celle de chaque DPE candidat. Rien d'autre. `build_state` est volontairement
    pauvre, et un test verrouille l'absence de surface / prix / date / coordonnees.

--- Forme des questions ---
Une requete par mutation, portant l'etat `{mutation, candidats[]}` et N questions
`Score` INDEPENDANTES -- une par candidat -- plus un `Noul` de garde. Ce decoupage
est prefere a un `Choice` unique sur la liste des candidats, dont l'exactitude se
degrade avec la longueur de liste. Les niveaux du `Score` decrivent des situations
concretes, pas des degres abstraits (guidance de l'API `score`).

--- Politique de decision ---
`decide` ne rend `resolu_jev` que si le meilleur candidat depasse SCORE_MIN, creuse
une marge >= MARGE_MIN sur le suivant, porte une confiance >= CONFIANCE_MIN, et que
le `Noul` de garde ne l'annule pas. Sinon l'etat d'entree est CONSERVE : la brique
ne fabrique jamais un appariement (CONTEXT.md -- jamais de choix force au hasard).
Le garde peut annuler un verdict, jamais en creer un.

Les trois seuils sont calibres par #36 (backtest sur les mutations `trouve`, verite
terrain gratuite) : voir `data/jev/backtest_report.md` et la note au-dessus de
`SCORE_MIN`. Ils sont ici des constantes nommees, au meme titre que
`DISTANCE_THRESHOLD_M` et `SURFACE_TOLERANCE_M2` -- jamais un nombre en dur dans
un appel.
"""

from __future__ import annotations

import hashlib
import json
from typing import NamedTuple

from pipeline.lib.match_distance import haversine_m
from pipeline.lib.mutations import mutation_key

# Modele EPINGLE sur une version concrete, jamais l'alias flottant `jev-latest`.
# La cle de cache integre cette chaine : avec un alias, une montee de version cote
# TypeSafe reutiliserait en silence des verdicts produits par un autre modele, ce
# que le spec interdit explicitement. Monter de version = changer cette constante,
# ce qui invalide mecaniquement tout le cache.
JEV_MODEL = "jev-1.13.0"

# Version de la FORMULATION des questions (instructions + criteria + etat envoye).
# A incrementer des qu'un de ces textes bouge : les verdicts caches deviennent alors
# inutilisables, et le cache le sait.
QUESTIONS_VERSION = "v1"

# Plafond du pool soumis en une requete. Les pools observes sont petits (~5,8 DPE
# par groupe d'adresse ambigu) : c'est un garde-fou contre la zone ou l'exactitude
# se degrade avec la longueur de liste, pas un filtre actif au cas general.
MAX_CANDIDATES = 8

# --- Seuils de decision (calibres par le backtest #36, data/jev/backtest_report.md) ---
# Le `Score` rend une position sur l'echelle des niveaux, de 0 au niveau le plus
# haut : avec trois niveaux, un score dans [0, 2].
#
# Le backtest (400 mutations `trouve` rejouees reponse masquee) mesure que le regime
# multi-candidats -- la SEULE population qu'`04c_jev_disambiguate.py` soumet
# reellement a Jev, un pool `ambigu` ayant toujours >= 2 candidats -- ne peut pas
# etre resolu de facon fiable a partir du seul texte d'adresse : exactitude top-1
# 30 % (n=200), score/confiance/marge NE discriminent PAS le bon candidat du
# mauvais (score moyen quasi identique sur les cas corrects et faux), et la marge
# reste < 0,25 sur 200/200 cas. Aucune fenetre de seuils ne rend une resolution
# automatique a la fois utile et sure sur cette population -- MARGE_MIN = 0.5
# bloque deja, de fait, toute resolution du regime multi, ce qui est le
# comportement CORRECT au vu de la mesure, pas un defaut a corriger. Ils restent
# donc inchanges : la valeur du backtest est d'avoir remplace une hypothese par une
# mesure, pas d'avoir change les nombres.
SCORE_MIN = 1.5
MARGE_MIN = 0.5
CONFIANCE_MIN = 0.5

GARDE_KEY = "garde"

_SCORE_INSTRUCTIONS = (
    "L'adresse de ce diagnostic designe-t-elle le meme logement que l'adresse de la mutation ?"
)

# Niveaux du Score, du bas vers le haut. Des SITUATIONS, pas des degres.
_SCORE_CRITERIA = [
    "L'adresse du diagnostic designe un autre bien : voie differente, numero different, "
    "ou residence / batiment explicitement differents.",
    "L'adresse du diagnostic designe le meme immeuble ou la meme residence, mais rien "
    "n'indique de quel logement il s'agit : aucun complement distinctif, ou un complement "
    "present d'un seul cote seulement.",
    "L'adresse du diagnostic designe le meme logement : meme voie, meme numero, et les "
    "complements presents des deux cotes (residence, batiment, etage, numero d'appartement) "
    "concordent.",
]

_GARDE_INSTRUCTIONS = (
    "L'adresse de la mutation designe-t-elle un logement identifiable parmi ces candidats ?"
)


class JevVerdict(NamedTuple):
    """Verdict d'une mutation soumise a Jev.

    - `status` : `resolu_jev` si la preuve textuelle suffit, sinon l'etat d'entree
      (`ambigu` pour D1, `non_trouve` pour le repli D2) rendu tel quel.
    - `numero_dpe` et le contexte bati : renseignes seulement sur `resolu_jev`.
    - `score` / `marge` / `confiance` : toujours renseignes -- ce sont eux qui
      rendent un cas limite auditable un par un, y compris quand rien n'est tranche.
    - `motif` : pourquoi la brique n'a pas tranche (`pool_vide`, `score_insuffisant`,
      `marge_insuffisante`, `confiance_insuffisante`, `garde_noul`), ou `resolu`.
    """

    status: str
    numero_dpe: str | None
    motif: str
    score: float
    marge: float
    confiance: float
    etiquette_dpe: str | None = None
    etiquette_ges: str | None = None
    type_batiment: str | None = None
    periode_construction: str | None = None


def candidate_ref(index: int) -> str:
    """Reference d'un candidat DANS la requete : sa position, jamais son `numero_dpe`.

    Un identifiant ADEME est opaque -- du bruit pour le modele, et une limite
    documentee est que l'exactitude chute avec les details hors sujet. Le code
    retrouve le DPE par sa position dans le pool selectionne.
    """
    return f"c{index}"


def _text(value) -> str:
    return (value or "").strip()


def select_candidates(mutation: dict, pool: list[dict], k: int = MAX_CANDIDATES) -> list[dict]:
    """Ordonne le pool par distance croissante a la mutation et le plafonne a `k`.

    Tri fait EN CODE (haversine) : le spec interdit de confier une comparaison de
    nombres au modele. Les candidats non geocodes passent en fin, dans leur ordre
    d'origine ; si la mutation elle-meme n'a pas de coordonnees, l'ordre du pool est
    conserve tel quel -- il n'y a alors rien a trier, et le plafond reste applique.
    """
    lat, lon = mutation.get("lat"), mutation.get("lon")
    if lat is None or lon is None:
        return list(pool[:k])

    def order(item: tuple[int, dict]) -> tuple[int, float, int]:
        i, dpe = item
        d_lat, d_lon = dpe.get("lat"), dpe.get("lon")
        if d_lat is None or d_lon is None:
            return (1, 0.0, i)
        return (0, haversine_m(lat, lon, d_lat, d_lon), i)

    return [dpe for _, dpe in sorted(enumerate(pool), key=order)][:k]


def build_state(mutation: dict, candidats: list[dict]) -> dict:
    """Etat envoye a Jev : uniquement les adresses brutes.

    Le texte brut est precisement ce que l'etape de normalisation detruit -- les
    compléments du type `RESIDENCE OCEANIC`, `BAT A`, numero d'appartement -- et
    donc la seule information que le code ne sait pas exploiter. Surface, prix,
    dates et coordonnees sont deliberement absents : le code les compare lui-meme,
    et les joindre ne ferait que diluer le signal.
    """
    return {
        "mutation": _text(mutation.get("adresse_brute")),
        "candidats": [
            {"ref": candidate_ref(i), "adresse": _text(d.get("adresse_brut"))}
            for i, d in enumerate(candidats)
        ],
    }


def build_questions(candidats: list[dict]) -> dict:
    """N questions `Score` independantes (une par candidat) + le `Noul` de garde.

    Format de l'API HTTP (`type` / `instructions` / `criteria`) : le module pur ne
    connait pas le SDK, c'est `jev_client` qui traduit. Un pool vide ne pose aucune
    question -- il n'y a rien a juger, et une requete sans candidat serait payante
    pour rien.
    """
    if not candidats:
        return {}
    questions = {
        candidate_ref(i): {
            "type": "score",
            "instructions": _SCORE_INSTRUCTIONS,
            "criteria": list(_SCORE_CRITERIA),
        }
        for i in range(len(candidats))
    }
    questions[GARDE_KEY] = {"type": "noul", "instructions": _GARDE_INSTRUCTIONS}
    return questions


def pool_fingerprint(candidats: list[dict]) -> str:
    """Empreinte d'un pool de candidats, independante de leur ordre.

    Porte l'identite ET l'adresse brute de chaque candidat. L'identite seule ne
    suffirait pas : c'est l'adresse brute qui est SOUMISE au modele, et un re-run de
    `03_clean_dpe` qui la corrige poserait une question differente sous une cle
    inchangee -- exactement la reutilisation silencieuse que le spec interdit. La
    cle est ainsi symetrique des deux cotes : `cache_key` porte deja l'adresse brute
    de la mutation.

    L'ORDRE, lui, reste hors de l'empreinte : il depend du tri par distance, donc du
    geocodage, et le faire entrer invaliderait le cache a chaque regeneration sans
    que la question posee ait change.
    """
    soumis = sorted((_text(d.get("numero_dpe")), _text(d.get("adresse_brut"))) for d in candidats)
    return hashlib.sha256(json.dumps(soumis, ensure_ascii=False).encode("utf-8")).hexdigest()


def cache_key(mutation: dict, candidats: list[dict], *, model: str, questions_version: str) -> str:
    """Cle de cache d'un cas juge : identite de la mutation + empreinte du pool +
    version du modele + version des questions (spec #33).

    L'identite de la mutation reprend `mutations.mutation_key` -- definition unique
    dans le projet -- completee de l'adresse brute : deux lignes-lots d'une meme
    mutation peuvent porter des adresses differentes, donc poser deux questions
    differentes, et ne doivent jamais partager un verdict.
    """
    payload = {
        "mutation": [str(part) for part in mutation_key(mutation)],
        "adresse": _text(mutation.get("adresse_brute")),
        "pool": pool_fingerprint(candidats),
        "model": model,
        "questions": questions_version,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _score_of(answers: dict, index: int) -> float:
    """Score d'un candidat. Une reponse absente vaut 0 -- pas de preuve, pas de
    verdict : mieux vaut laisser la mutation indecise que supposer."""
    answer = answers.get(candidate_ref(index)) or {}
    score = answer.get("score")
    return float(score) if score is not None else 0.0


def _confidence_of(answers: dict, index: int) -> float:
    answer = answers.get(candidate_ref(index)) or {}
    confidence = answer.get("confidence")
    return float(confidence) if confidence is not None else 0.0


def _undecided(entry_status: str, motif: str, score: float, marge: float, conf: float):
    return JevVerdict(entry_status, None, motif, score, marge, conf)


def best_candidate(answers: dict, candidats: list[dict]) -> tuple[int | None, float, float, float]:
    """Meilleur candidat + (score, marge, confiance), AVANT tout seuil de decision.

    Factorise hors de `decide` pour le backtest (#36) : la courbe exactitude x
    confiance a besoin de savoir, pour CHAQUE cas, quel candidat Jev prefere et avec
    quelle marge/confiance -- y compris quand aucun seuil n'est encore choisi. `decide`
    applique les trois garde-fous par-dessus ce meme calcul ; les deux ne peuvent pas
    diverger puisque `decide` appelle cette fonction.

    Rend `(None, 0.0, 0.0, 0.0)` sur un pool vide -- rien a departager.
    """
    if not candidats:
        return None, 0.0, 0.0, 0.0
    scores = [_score_of(answers, i) for i in range(len(candidats))]
    best = max(range(len(scores)), key=lambda i: scores[i])
    others = [s for i, s in enumerate(scores) if i != best]
    score = scores[best]
    marge = score - (max(others) if others else 0.0)
    confiance = _confidence_of(answers, best)
    return best, score, marge, confiance


def decide(
    answers: dict,
    candidats: list[dict],
    *,
    entry_status: str,
    score_min: float = SCORE_MIN,
    marge_min: float = MARGE_MIN,
    confiance_min: float = CONFIANCE_MIN,
) -> JevVerdict:
    """Agrege les reponses en un verdict. Code pur, seuils nommes et parametrables.

    `answers` est deja NORMALISE par `jev_client` :
    `{"c0": {"score": float, "confidence": float}, ..., "garde": {"noul": bool}}`.
    Le module pur ne connait ainsi ni le SDK ni le format HTTP, et la politique de
    decision se teste sur des reponses figees.

    `entry_status` est rendu tel quel des que la preuve est insuffisante : `ambigu`
    pour la desambiguisation (D1), `non_trouve` pour le repli (D2, #40).

    ATTENTION pour la calibration (#36) : sur un pool d'UN SEUL candidat, il n'y a pas
    de second score, donc `marge == score` et le garde-fou de marge ne peut pas
    mordre -- seul `score_min` decide. C'est voulu (il n'y a rien a departager), mais
    les deux populations n'ont pas la meme politique de fait et doivent etre calibrees
    separement, sans quoi la courbe melange deux regimes.
    """
    if not candidats:
        return _undecided(entry_status, "pool_vide", 0.0, 0.0, 0.0)

    best, score, marge, confiance = best_candidate(answers, candidats)

    if score < score_min:
        return _undecided(entry_status, "score_insuffisant", score, marge, confiance)
    if marge < marge_min:
        return _undecided(entry_status, "marge_insuffisante", score, marge, confiance)
    if confiance < confiance_min:
        return _undecided(entry_status, "confiance_insuffisante", score, marge, confiance)

    # Garde de sortie : il peut ANNULER un verdict, jamais en creer un -- il n'est
    # consulte qu'une fois les trois seuils franchis.
    garde = answers.get(GARDE_KEY) or {}
    if garde.get("noul") is False:
        return _undecided(entry_status, "garde_noul", score, marge, confiance)

    gagnant = candidats[best]
    return JevVerdict(
        "resolu_jev",
        gagnant.get("numero_dpe"),
        "resolu",
        score,
        marge,
        confiance,
        etiquette_dpe=gagnant.get("etiquette_dpe"),
        etiquette_ges=gagnant.get("etiquette_ges"),
        type_batiment=gagnant.get("type_batiment"),
        periode_construction=gagnant.get("periode_construction"),
    )
