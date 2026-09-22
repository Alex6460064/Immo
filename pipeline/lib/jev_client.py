"""Brique Jev : SEULE frontiere reseau (#35, spec #33). Cache + appels + traduction.

Le partage avec `pipeline/lib/jev_decision.py` est strict : toute la politique de
decision est la-bas, pure et testee en CI ; ici on ne fait que parler au modele,
memoriser ce qu'il a repondu, et traduire sa reponse vers la forme normalisee que
le module pur attend.

--- Cache ---
Un parquet, une ligne par cas juge, cle = identite de la mutation + empreinte du
pool + version du modele + version des questions (`jev_decision.cache_key`).
Consequences voulues :

  - rejouer l'etape ne redeclenche aucun appel pour une cle deja connue ;
  - changer `JEV_MODEL` ou `QUESTIONS_VERSION` change la cle, donc l'entree devient
    inatteignable au lieu d'etre reutilisee en silence ;
  - un clone frais SANS cle API regenere agregats, dashboard et PDF a partir des
    verdicts versionnes -- comme la synthese PDF aujourd'hui.

--- Degradation sans cle ---
`make_ask()` rend `None` en l'absence de `TYPESAFE_API_KEY`. `judge_cases(ask=None)`
sert alors ce que le cache contient et laisse les autres mutations dans leur etat
d'entree, motif `sans_cle`. Jamais d'echec dur : le pipeline produit les quatre
etats actuels.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from pipeline.lib.jev_decision import (
    JEV_MODEL,
    QUESTIONS_VERSION,
    JevVerdict,
    build_questions,
    build_state,
    cache_key,
    decide,
    pool_fingerprint,
    select_candidates,
)
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows

# Schema du parquet de verdicts. Il porte de quoi auditer un cas limite sans
# rejouer quoi que ce soit : identite de la mutation, adresse brute soumise,
# empreinte et taille du pool, verdict, score / marge / confiance, et les deux
# versions qui conditionnent la cle.
VERDICT_COLUMNS = {
    "cle": "VARCHAR",
    "date_mutation": "VARCHAR",
    "code_insee": "VARCHAR",
    "no_disposition": "VARCHAR",
    "prix": "DOUBLE",
    "adresse_brute": "VARCHAR",
    "pool_fingerprint": "VARCHAR",
    "pool_taille": "BIGINT",
    "status_entree": "VARCHAR",
    "status": "VARCHAR",
    "numero_dpe": "VARCHAR",
    "motif": "VARCHAR",
    "score": "DOUBLE",
    "marge": "DOUBLE",
    "confiance": "DOUBLE",
    "etiquette_dpe": "VARCHAR",
    "etiquette_ges": "VARCHAR",
    "type_batiment": "VARCHAR",
    "periode_construction": "VARCHAR",
    "modele": "VARCHAR",
    "questions_version": "VARCHAR",
    "input_tokens": "BIGINT",
    # Duree de l'appel qui a produit CE verdict. Persistee parce que le livrable de
    # #35 est un chiffre : sans elle, la duree d'une passe ne vit que dans la sortie
    # console du run et devient irrecuperable des que le cache sert les verdicts.
    "duree_ms": "BIGINT",
}

# Le SDK porte sa propre politique de retry (backoff exponentiel + `Retry-After`,
# sur les codes que la documentation designe comme reessayables). On la parametre
# plutot que d'en reecrire une : une passe complete reste de toute facon loin de la
# limite documentee de 1 200 requetes/minute.
_MAX_RETRIES = 4


class JevRun(NamedTuple):
    """Comptes d'une passe, imprimes par l'etape du pipeline.

    `input_tokens` et `duree_s` ne portent que sur les APPELS reels : c'est ce qui
    permet d'extrapoler le cout et la duree d'une passe complete a partir d'un
    echantillon (livrable central de #35).
    """

    verdicts: list[JevVerdict]
    appels: int
    servis_par_cache: int
    input_tokens: int
    duree_s: float
    status_counts: dict[str, int]
    motif_counts: dict[str, int]


class VerdictCache:
    """Verdicts deja obtenus, indexes par cle. En memoire, persiste en Parquet."""

    def __init__(self, rows: Iterable[dict] = ()):
        self._rows: dict[str, dict] = {row["cle"]: row for row in rows}

    @classmethod
    def load(cls, path: str | Path) -> VerdictCache:
        """Charge le cache. Un fichier absent ou vide donne un cache vide -- c'est le
        cas nominal du premier run, pas une erreur."""
        path = Path(path)
        if not path.exists() or path.stat().st_size == 0:
            return cls()
        return cls(read_parquet_rows(path, list(VERDICT_COLUMNS)))

    def save(self, path: str | Path) -> None:
        """Ecrit le cache, trie par cle -- un parquet reproductible d'un run a l'autre
        se relit dans un diff Git au lieu de bouger a chaque ecriture."""
        rows = [self._rows[cle] for cle in sorted(self._rows)]
        write_parquet_rows(rows, VERDICT_COLUMNS, path)

    def get(self, cle: str) -> dict | None:
        return self._rows.get(cle)

    def put(self, row: dict) -> None:
        self._rows[row["cle"]] = row

    def rows(self) -> list[dict]:
        return [self._rows[cle] for cle in sorted(self._rows)]

    def __len__(self) -> int:
        return len(self._rows)


def _verdict_from_row(row: dict) -> JevVerdict:
    return JevVerdict(
        row["status"],
        row["numero_dpe"],
        row["motif"],
        row["score"],
        row["marge"],
        row["confiance"],
        etiquette_dpe=row["etiquette_dpe"],
        etiquette_ges=row["etiquette_ges"],
        type_batiment=row["type_batiment"],
        periode_construction=row["periode_construction"],
    )


def _field(obj, name, default=None):
    """Lit un champ indifferemment sur un dict (charge utile HTTP) ou sur un objet
    (modeles du SDK). Les deux formes portent les memes noms."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_answer(answer) -> dict | None:
    """Une reponse -> la forme attendue par `jev_decision.decide`.

    On se fie au champ `type` (present des deux cotes : `ScoreAnswer.type == "score"`,
    `NoulAnswer.type == "noul"`) plutot qu'a la presence d'une valeur : un score de
    0.0 et un noul `False` sont des reponses legitimes, pas des absences.
    """
    kind = _field(answer, "type")
    if kind == "score":
        return {"score": _field(answer, "score"), "confidence": _field(answer, "confidence")}
    if kind == "noul":
        return {"noul": _field(answer, "noul")}
    return None


def normalize_response(response, *, expected_model: str | None = None) -> tuple[dict, str, int]:
    """Traduit une reponse en `(answers, modele_resolu, input_tokens)`.

    Accepte les deux formes, qui portent les memes noms de champs : la charge utile
    HTTP (`{"model", "answers", "usage"}`) et le `SystemOneResponse` du SDK
    (`.model` / `.answers` / `.usage`). Le module pur ne voit ni l'une ni l'autre :
    il recoit `{"c0": {"score", "confidence"}, "garde": {"noul"}}`.

    `expected_model` : si le modele resolu differe du modele epingle, on leve. Ecrire
    au cache un verdict rendu par un autre modele sous une cle qui annonce le modele
    epingle serait exactement la reutilisation silencieuse que le spec interdit.
    """
    answers = {}
    for qid, answer in (_field(response, "answers") or {}).items():
        normalized = _normalize_answer(answer)
        if normalized is not None:
            answers[qid] = normalized

    modele = _field(response, "model") or ""
    usage = _field(response, "usage")
    tokens = int(_field(usage, "input_tokens", 0) or 0) if usage is not None else 0

    if expected_model is not None and modele != expected_model:
        raise ValueError(
            f"modele resolu {modele!r} != modele epingle {expected_model!r} : "
            "verdict non mis en cache (la cle annoncerait le mauvais modele)."
        )
    return answers, modele, tokens


def _row(
    *,
    cle: str,
    mutation: dict,
    candidats: list[dict],
    entry_status: str,
    verdict: JevVerdict,
    model: str,
    questions_version: str,
    input_tokens: int,
    duree_ms: int,
) -> dict:
    return {
        "cle": cle,
        "date_mutation": mutation.get("date_mutation"),
        "code_insee": mutation.get("code_insee"),
        "no_disposition": mutation.get("no_disposition"),
        "prix": mutation.get("prix"),
        "adresse_brute": mutation.get("adresse_brute"),
        "pool_fingerprint": pool_fingerprint(candidats),
        "pool_taille": len(candidats),
        "status_entree": entry_status,
        "status": verdict.status,
        "numero_dpe": verdict.numero_dpe,
        "motif": verdict.motif,
        "score": verdict.score,
        "marge": verdict.marge,
        "confiance": verdict.confiance,
        "etiquette_dpe": verdict.etiquette_dpe,
        "etiquette_ges": verdict.etiquette_ges,
        "type_batiment": verdict.type_batiment,
        "periode_construction": verdict.periode_construction,
        "modele": model,
        "questions_version": questions_version,
        "input_tokens": input_tokens,
        "duree_ms": duree_ms,
    }


def judge_cases(
    cases: list[dict],
    *,
    ask: Callable | None,
    cache: VerdictCache,
    model: str = JEV_MODEL,
    questions_version: str = QUESTIONS_VERSION,
    on_progress: Callable[[int, int], None] | None = None,
) -> JevRun:
    """Juge une liste de cas. Un cas : `{mutation, candidats, entry_status}`.

    Idempotent : une cle deja au cache n'entraine aucun appel. Un pool vide n'est
    jamais envoye (rien a juger, et la requete serait payante pour rien). `ask=None`
    (pas de cle API) sert le cache et laisse le reste en l'etat, motif `sans_cle`.

    Sequentiel volontairement : `pipeline/jev_backtest.py` (#36) parallelise ses
    propres appels reseau avec sa propre gestion du cache -- voir sa docstring pour
    pourquoi cette concurrence n'a pas sa place ici (le seul appelant de production,
    `04c_jev_disambiguate.py`, reste sequentiel).
    """
    verdicts: list[JevVerdict] = []
    appels = servis = tokens_total = 0
    duree = 0.0
    statuses: Counter = Counter()
    motifs: Counter = Counter()

    for done, case in enumerate(cases, start=1):
        mutation, entry_status = case["mutation"], case["entry_status"]
        candidats = select_candidates(mutation, case["candidats"])

        if not candidats:
            verdict = decide({}, [], entry_status=entry_status)
        else:
            cle = cache_key(mutation, candidats, model=model, questions_version=questions_version)
            row = cache.get(cle)
            if row is not None:
                verdict = _verdict_from_row(row)
                servis += 1
            elif ask is None:
                verdict = JevVerdict(entry_status, None, "sans_cle", 0.0, 0.0, 0.0)
            else:
                started = time.monotonic()
                response = ask(
                    state=build_state(mutation, candidats),
                    questions=build_questions(candidats),
                    model=model,
                )
                appel_s = time.monotonic() - started
                duree += appel_s
                answers, _modele, tokens = normalize_response(response, expected_model=model)
                appels += 1
                tokens_total += tokens
                verdict = decide(answers, candidats, entry_status=entry_status)
                cache.put(
                    _row(
                        cle=cle,
                        mutation=mutation,
                        candidats=candidats,
                        entry_status=entry_status,
                        verdict=verdict,
                        model=model,
                        questions_version=questions_version,
                        input_tokens=tokens,
                        duree_ms=round(appel_s * 1000),
                    )
                )

        verdicts.append(verdict)
        statuses[verdict.status] += 1
        motifs[verdict.motif] += 1
        if on_progress is not None:
            on_progress(done, len(cases))

    return JevRun(
        verdicts=verdicts,
        appels=appels,
        servis_par_cache=servis,
        input_tokens=tokens_total,
        duree_s=duree,
        status_counts=dict(statuses),
        motif_counts=dict(motifs),
    )


def _to_sdk_questions(questions: dict) -> dict:
    """Traduit les questions (format API) en objets du SDK. Import PARESSEUX :
    `typesafe-sdk` vit dans un groupe de dependances optionnel, absent de la CI et
    du manifeste Streamlit Cloud."""
    from typesafe_sdk import Noul, Score

    built = {}
    for qid, question in questions.items():
        if question["type"] == "score":
            built[qid] = Score(instructions=question["instructions"], criteria=question["criteria"])
        else:
            built[qid] = Noul(instructions=question["instructions"])
    return built


def make_ask(api_key: str | None = None) -> Callable | None:
    """Construit le `ask` reel, ou `None` si aucune cle n'est disponible.

    La cle reste en variable d'environnement cote pipeline : elle ne traverse ni
    l'instantane `data/dashboard/`, ni le parquet de verdicts, ni le depot.
    """
    key = api_key or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        return None

    from typesafe_sdk import RetryPolicy, TypeSafeClient

    client = TypeSafeClient(api_key=key, retry=RetryPolicy(max_retries=_MAX_RETRIES))

    def ask(*, state, questions, model):
        return client.system_one(state=state, questions=_to_sdk_questions(questions), model=model)

    return ask
