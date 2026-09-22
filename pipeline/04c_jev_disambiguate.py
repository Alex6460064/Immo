"""Desambiguisation Jev des mutations `ambigu` (#35, spec #33) -- socle sur echantillon.

Lit data/processed/dvf_dpe_matched.parquet (04_join) et data/processed/dpe_clean.parquet
(03_clean_dpe), reconstruit pour chaque mutation `ambigu` le pool de candidats sur
lequel la passe 4 est restee indecise (`match_dvf_dpe.classify_with_pool`), soumet ce
pool a Jev, et ecrit les verdicts dans data/jev/verdicts.parquet.

Ce que cette etape NE fait PAS, volontairement : elle ne reecrit pas
`dvf_dpe_matched.parquet` et n'introduit pas le 5e etat `resolu_jev` dans le pipeline.
C'est #37. Ici on valide le socle -- module pur, client, cache -- et surtout on MESURE
le cout et la duree reels d'une passe, avant tout engagement sur la passe complete.

--- Idempotence ---
Le cache (data/jev/verdicts.parquet) est la memoire de l'etape : relancer ne rappelle
que les cles absentes. Changer `JEV_MODEL` ou `QUESTIONS_VERSION` dans
`pipeline/lib/jev_decision.py` change la cle, donc invalide les entrees concernees --
jamais de reutilisation silencieuse.

--- Sans cle API ---
`TYPESAFE_API_KEY` absente : l'etape journalise, sert ce que le cache contient deja et
sort sans erreur. Le pipeline produit les quatre etats actuels.

--- Echantillon ---
`--limit N` (defaut 50) : les N mutations `ambigu` dont la cle de cache est la plus
petite. Le tri par cle est un hash, donc un echantillon reparti sur tout le perimetre
(communes, annees, tailles de pool) et surtout STABLE d'un run a l'autre : relancer
juge le meme echantillon, donc ne repaie rien. `--limit 0` traite tout (#37).

Usage :
    python pipeline/04c_jev_disambiguate.py [--limit 50] [--no-detail]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.jev_client import (  # noqa: E402
    VerdictCache,
    judge_cases,
    make_ask,
)
from pipeline.lib.jev_decision import (  # noqa: E402
    JEV_MODEL,
    MAX_CANDIDATES,
    QUESTIONS_VERSION,
    cache_key,
    select_candidates,
)
from pipeline.lib.join_dvf_dpe import DPE_FIELDS, PASSTHROUGH_DVF_FIELDS  # noqa: E402
from pipeline.lib.match_distance import DISTANCE_THRESHOLD_M  # noqa: E402
from pipeline.lib.match_dvf_dpe import build_dpe_index, classify_with_pool  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCHED_PATH = ROOT / "data" / "processed" / "dvf_dpe_matched.parquet"
DPE_PATH = ROOT / "data" / "processed" / "dpe_clean.parquet"
VERDICTS_PATH = ROOT / "data" / "jev" / "verdicts.parquet"

# `adresse_brut` est le seul champ que 04_join ne lit pas : l'appariement travaille
# sur l'adresse normalisee, Jev sur le texte brut -- c'est precisement ce que la
# normalisation detruit (spec #33).
JEV_DPE_FIELDS = [*DPE_FIELDS, "adresse_brut"]

# Tarif documente (docs.typesafe.ai/models) : 0,042 $ / M tokens d'entree, sortie
# gratuite. Sert uniquement a chiffrer le run et son extrapolation.
COUT_PAR_M_TOKENS_USD = 0.042


def _read_inputs() -> tuple[list[dict], list[dict]]:
    for path, producer in ((MATCHED_PATH, "04_join.py"), (DPE_PATH, "03_clean_dpe.py")):
        if not path.exists():
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print(f"  Lancer d'abord : python pipeline/{producer}", file=sys.stderr)
            sys.exit(1)

    print(f"[04c_jev] Lecture de {MATCHED_PATH}")
    matched = read_parquet_rows(MATCHED_PATH, [*PASSTHROUGH_DVF_FIELDS, "match_status"])
    print(f"[04c_jev] Lecture de {DPE_PATH}")
    dpe_rows = read_parquet_rows(DPE_PATH, JEV_DPE_FIELDS)
    return matched, dpe_rows


def build_cases(matched: list[dict], dpe_rows: list[dict]) -> tuple[list[dict], int]:
    """Reconstruit, pour chaque mutation `ambigu`, le pool de candidats indecis.

    Le pool porte par chaque cas est DEJA passe par `select_candidates` (tri par
    distance + plafond) : c'est exactement la liste qui sera soumise, celle qui entre
    dans la cle de cache, et celle qu'affiche l'inspection manuelle. La resoudre une
    seule fois ici evite que ces trois vues divergent.

    Retourne (cas, nb_incoherences). Une incoherence = une mutation marquee `ambigu`
    dans `dvf_dpe_matched` que le rematch ne reclasse pas `ambigu` : signe que les
    deux parquets ne viennent pas du meme run. Comptee et signalee, jamais ignoree.
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

    cases: list[dict] = []
    incoherences = 0
    for mutation in matched:
        if mutation.get("match_status") != "ambigu":
            continue
        code = (mutation.get("code_insee") or "").strip()
        result, pool = classify_with_pool(mutation, index_by_commune.get(code, empty_index))
        if result.status != "ambigu":
            incoherences += 1
            continue
        cases.append(
            {
                "mutation": mutation,
                "candidats": select_candidates(mutation, pool),
                "entry_status": "ambigu",
            }
        )
    return cases, incoherences


def sample(cases: list[dict], limit: int) -> list[dict]:
    """Echantillon stable : les `limit` cas de plus petite cle de cache.

    La cle est un sha256, donc l'ordre est uniforme sur le perimetre et ne depend ni
    de l'ordre physique du parquet ni de la commune. Stable = relancer juge le meme
    echantillon, donc ne repaie aucun appel.
    """
    keyed = [
        (
            cache_key(
                case["mutation"],
                case["candidats"],
                model=JEV_MODEL,
                questions_version=QUESTIONS_VERSION,
            ),
            case,
        )
        for case in cases
    ]
    keyed.sort(key=lambda kc: kc[0])
    return [case for _, case in keyed[:limit]] if limit else [case for _, case in keyed]


def _print_detail(cases: list[dict], verdicts: list) -> None:
    """Les verdicts un par un -- l'inspection manuelle est un critere d'acceptation,
    pas un confort : elle doit etre possible depuis la sortie du run."""
    print("\n=== Verdicts (inspection manuelle) ===")
    for case, verdict in zip(cases, verdicts, strict=True):
        mutation, pool = case["mutation"], case["candidats"]
        marque = "OK " if verdict.status == "resolu_jev" else "-- "
        print(
            f"{marque}{verdict.status:<14} score={verdict.score:>4.2f} "
            f"marge={verdict.marge:>5.2f} conf={verdict.confiance:>4.2f} "
            f"pool={len(pool)} motif={verdict.motif}"
        )
        print(f"     mutation : {mutation.get('adresse_brute')}")
        for i, dpe in enumerate(pool):
            gagnant = ">" if dpe.get("numero_dpe") == verdict.numero_dpe else " "
            print(
                f"    {gagnant}c{i} [{dpe.get('etiquette_dpe') or '?'}] {dpe.get('adresse_brut')}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="0 = toutes les mutations ambigues")
    parser.add_argument("--no-detail", action="store_true", help="masque le detail des verdicts")
    args = parser.parse_args()

    matched, dpe_rows = _read_inputs()
    cases, incoherences = build_cases(matched, dpe_rows)
    total_ambigu = len(cases)
    print(f"[04c_jev] {total_ambigu} mutations ambigues avec pool reconstruit")
    if incoherences:
        print(
            f"ATTENTION : {incoherences} mutations `ambigu` non reclassees `ambigu` par le "
            "rematch -- dvf_dpe_matched et dpe_clean ne viennent probablement pas du meme run.",
            file=sys.stderr,
        )
    if not cases:
        print("[04c_jev] Rien a juger.")
        return

    retenus = sample(cases, args.limit)
    tailles = [len(c["candidats"]) for c in retenus]
    print(
        f"[04c_jev] Echantillon : {len(retenus)} cas, pool moyen "
        f"{sum(tailles) / len(tailles):.1f} candidats (plafond {MAX_CANDIDATES})"
    )

    ask = make_ask()
    if ask is None:
        print(
            "[04c_jev] TYPESAFE_API_KEY absente -- aucun appel. Les verdicts deja en "
            "cache sont servis, les autres mutations restent `ambigu`."
        )

    cache = VerdictCache.load(VERDICTS_PATH)
    print(f"[04c_jev] Cache : {len(cache)} verdicts deja connus ({VERDICTS_PATH})")
    print(f"[04c_jev] Modele {JEV_MODEL}, questions {QUESTIONS_VERSION}")

    connus = len(cache)
    try:
        run = judge_cases(retenus, ask=ask, cache=cache, on_progress=_progress)
    finally:
        # Un verdict est PAYE des qu'il est rendu : une exception en cours de passe
        # (modele resolu inattendu, retries epuises) ne doit pas les jeter tous.
        if len(cache) > connus:
            cache.save(VERDICTS_PATH)
            print(f"\n[04c_jev] Ecriture de {VERDICTS_PATH} ({len(cache)} verdicts)")
    print()

    if not args.no_detail:
        _print_detail(retenus, run.verdicts)

    _print_report(run, total_ambigu)


def _progress(done: int, total: int) -> None:
    if done % 10 == 0 or done == total:
        print(f"[04c_jev] {done}/{total} cas traites", flush=True)


def _print_report(run, total_ambigu: int) -> None:
    n = len(run.verdicts)
    resolus = run.status_counts.get("resolu_jev", 0)

    print("\n=== Rapport de desambiguisation Jev (#35, socle sur echantillon) ===")
    print(f"  Cas soumis                     : {n}")
    print(f"    - appels reels               : {run.appels}")
    print(f"    - servis par le cache        : {run.servis_par_cache}")
    print("  Verdicts")
    for status, count in sorted(run.status_counts.items(), key=lambda kv: -kv[1]):
        print(f"    - {status:<14} : {count:>4}  ({count / n * 100:.1f}%)")
    print("  Motifs de non-resolution")
    for motif, count in sorted(run.motif_counts.items(), key=lambda kv: -kv[1]):
        if motif != "resolu":
            print(f"    - {motif:<22} : {count:>4}")

    if not run.appels:
        print("\n  Aucun appel reel : cout et duree non mesures sur ce run.")
        return

    cout = run.input_tokens / 1_000_000 * COUT_PAR_M_TOKENS_USD
    tokens_par_appel = run.input_tokens / run.appels
    secondes_par_appel = run.duree_s / run.appels

    print("\n  --- Cout et duree MESURES (appels reels uniquement) ---")
    print(f"    tokens d'entree              : {run.input_tokens} ({tokens_par_appel:.0f}/appel)")
    print(
        f"    duree                        : {run.duree_s:.1f} s ({secondes_par_appel:.2f} s/appel)"
    )
    print(f"    cout                         : {cout:.4f} $")

    print(f"\n  --- Extrapolation a la passe complete ({total_ambigu} mutations ambigues) ---")
    print(f"    tokens d'entree              : {tokens_par_appel * total_ambigu / 1e6:.1f} M")
    print(f"    cout                         : {cout / run.appels * total_ambigu:.2f} $")
    print(f"    duree (sequentiel)           : {secondes_par_appel * total_ambigu / 60:.0f} min")
    print(
        f"    taux de resolution observe   : {resolus / n * 100:.1f}% "
        f"-- indicatif : le seuil n'est pas encore calibre (#36)."
    )


if __name__ == "__main__":
    main()
