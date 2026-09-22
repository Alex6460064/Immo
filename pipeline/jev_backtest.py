"""Backtest Jev sur les mutations `trouve` (#36, spec #33) -- calibre le seuil de
decision du projet a partir d'une courbe mesuree, au lieu d'un nombre choisi a la
main.

Principe (verite terrain gratuite) : une mutation `trouve` porte une identite DPE
connue avec certitude. On reconstruit son pool de candidats (`classify_with_backtest_pool`,
`pipeline/lib/match_dvf_dpe.py`) comme s'il etait ambigu, masque la reponse, la
soumet a Jev, et compare le candidat prefere a la reponse connue. Logique pure et
testee dans `pipeline/lib/jev_backtest.py` ; ce script ne fait que l'I/O et le reseau.

Analyse ponctuelle, PAS une etape du pipeline : rejouable a la main, jamais appelee
par la CI (aucun test n'importe ce fichier), jamais par les autres scripts
`pipeline/0*`. Le cache (data/jev/backtest_verdicts.parquet) rend un rerun gratuit
pour les cles deja jugees -- meme principe que `04c_jev_disambiguate.py`.

Usage :
    python pipeline/jev_backtest.py [--limit-par-regime 150] [--max-workers 10]
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.jev_backtest import (  # noqa: E402
    REGIME_ISOLE,
    REGIME_MULTI,
    BacktestCase,
    EvalRecord,
    bucket_by,
    build_cases,
    evaluate_case,
    stratified_sample,
    summarize,
)
from pipeline.lib.jev_client import make_ask, normalize_response  # noqa: E402
from pipeline.lib.jev_decision import (  # noqa: E402
    CONFIANCE_MIN,
    JEV_MODEL,
    MARGE_MIN,
    QUESTIONS_VERSION,
    SCORE_MIN,
    best_candidate,
    build_questions,
    build_state,
    cache_key,
)
from pipeline.lib.join_dvf_dpe import DPE_FIELDS, PASSTHROUGH_DVF_FIELDS  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCHED_PATH = ROOT / "data" / "processed" / "dvf_dpe_matched.parquet"
DPE_PATH = ROOT / "data" / "processed" / "dpe_clean.parquet"
CACHE_PATH = ROOT / "data" / "jev" / "backtest_verdicts.parquet"
REPORT_PATH = ROOT / "data" / "jev" / "backtest_report.md"

JEV_DPE_FIELDS = [*DPE_FIELDS, "adresse_brut"]

# Schema du cache de backtest -- distinct de VERDICT_COLUMNS (jev_client) : porte
# `verite_numero_dpe` (jamais soumise a Jev) et `numero_dpe_propose` (le meilleur
# candidat AVANT tout seuil, renseigne meme quand `decide` reste indecis) --
# exactement ce qu'un backtest doit auditer et qu'un cache de production n'a pas
# a connaitre.
CACHE_COLUMNS = {
    "cle": "VARCHAR",
    "regime": "VARCHAR",
    "date_mutation": "VARCHAR",
    "code_insee": "VARCHAR",
    "no_disposition": "VARCHAR",
    "pool_taille": "BIGINT",
    "verite_numero_dpe": "VARCHAR",
    "numero_dpe_propose": "VARCHAR",
    "correct_top1": "BOOLEAN",
    "score": "DOUBLE",
    "marge": "DOUBLE",
    "confiance": "DOUBLE",
    "modele": "VARCHAR",
    "questions_version": "VARCHAR",
    "input_tokens": "BIGINT",
    "duree_ms": "BIGINT",
}


def _read_inputs() -> tuple[list[dict], list[dict]]:
    for path, producer in ((MATCHED_PATH, "04_join.py"), (DPE_PATH, "03_clean_dpe.py")):
        if not path.exists():
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print(f"  Lancer d'abord : python pipeline/{producer}", file=sys.stderr)
            sys.exit(1)
    print(f"[jev_backtest] Lecture de {MATCHED_PATH}")
    matched = read_parquet_rows(MATCHED_PATH, [*PASSTHROUGH_DVF_FIELDS, "match_status"])
    print(f"[jev_backtest] Lecture de {DPE_PATH}")
    dpe_rows = read_parquet_rows(DPE_PATH, JEV_DPE_FIELDS)
    return matched, dpe_rows


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists() or CACHE_PATH.stat().st_size == 0:
        return {}
    rows = read_parquet_rows(CACHE_PATH, list(CACHE_COLUMNS))
    return {row["cle"]: row for row in rows}


def _save_cache(cache: dict[str, dict]) -> None:
    rows = [cache[cle] for cle in sorted(cache)]
    write_parquet_rows(rows, CACHE_COLUMNS, CACHE_PATH)


def _cache_row(cle: str, case: BacktestCase, gagnant: str | None, record) -> dict:
    return {
        "cle": cle,
        "regime": case.regime,
        "date_mutation": case.mutation.get("date_mutation"),
        "code_insee": case.mutation.get("code_insee"),
        "no_disposition": case.mutation.get("no_disposition"),
        "pool_taille": len(case.candidats),
        "verite_numero_dpe": case.verite_numero_dpe,
        "numero_dpe_propose": gagnant,
        "correct_top1": record.correct_top1,
        "score": record.score,
        "marge": record.marge,
        "confiance": record.confiance,
        "modele": JEV_MODEL,
        "questions_version": QUESTIONS_VERSION,
        "input_tokens": None,
        "duree_ms": None,
    }


def _ask_one(ask, case: BacktestCase) -> tuple[BacktestCase, dict, int, float]:
    started = time.monotonic()
    response = ask(
        state=build_state(case.mutation, case.candidats),
        questions=build_questions(case.candidats),
        model=JEV_MODEL,
    )
    duree = time.monotonic() - started
    answers, _modele, tokens = normalize_response(response, expected_model=JEV_MODEL)
    return case, answers, tokens, duree


def _print_bucket_table(title: str, buckets) -> list[str]:
    lines = [f"\n  {title}", f"    {'tranche':<16}{'n':>6}  {'exactitude top-1':>18}"]
    print(lines[0])
    print(lines[1])
    for b in buckets:
        line = f"    [{b.lo:.2f}, {b.hi:.2f}){' ':<2}{b.n:>6}  {b.exactitude:>17.1%}"
        print(line)
        lines.append(line)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-par-regime", type=int, default=150)
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    matched, dpe_rows = _read_inputs()
    cases, incoherences = build_cases(matched, dpe_rows)
    par_regime = {
        REGIME_ISOLE: sum(1 for c in cases if c.regime == REGIME_ISOLE),
        REGIME_MULTI: sum(1 for c in cases if c.regime == REGIME_MULTI),
    }
    print(
        f"[jev_backtest] {len(cases)} mutations `trouve` avec verite terrain "
        f"({par_regime[REGIME_ISOLE]} isolees, {par_regime[REGIME_MULTI]} multi-candidats)"
    )
    if incoherences:
        print(
            f"ATTENTION : {incoherences} mutations `trouve` non reclassees `trouve` par le "
            "rematch -- dvf_dpe_matched et dpe_clean ne viennent probablement pas du meme run.",
            file=sys.stderr,
        )
    if not cases:
        print("[jev_backtest] Rien a juger.")
        return

    retenus = stratified_sample(cases, args.limit_par_regime)
    print(f"[jev_backtest] Echantillon : {len(retenus)} cas ({args.limit_par_regime}/regime max)")

    ask = make_ask()
    if ask is None:
        print(
            "[jev_backtest] TYPESAFE_API_KEY absente -- aucun appel possible, seul le cache "
            "deja connu peut etre resume.",
            file=sys.stderr,
        )

    cache = _load_cache()
    print(f"[jev_backtest] Cache : {len(cache)} cas deja juges ({CACHE_PATH})")

    to_call = []
    records = []
    record_by_case = {}
    for case in retenus:
        cle = cache_key(
            case.mutation, case.candidats, model=JEV_MODEL, questions_version=QUESTIONS_VERSION
        )
        row = cache.get(cle)
        if row is not None:
            record_by_case[cle] = row
        elif ask is not None:
            to_call.append((cle, case))

    appels = 0
    tokens_total = 0
    duree_total = 0.0
    connus = len(cache)
    if to_call:
        # `ask` (TypeSafeClient.system_one) est appele depuis plusieurs threads a la
        # fois : IO-bound, et le SDK porte sa propre politique de retry (voir
        # jev_client.make_ask) -- on suppose l'appel thread-safe comme tout client
        # HTTP standard, hypothese non testee ici faute d'acces au SDK en CI.
        workers = max(1, min(args.max_workers, len(to_call)))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_item = {
                    pool.submit(_ask_one, ask, case): (cle, case) for cle, case in to_call
                }
                for future in as_completed(future_to_item):
                    cle, case = future_to_item[future]
                    # Une exception ici (timeout, retries epuises) ne doit perdre
                    # QUE ce cas : les futures deja resolues restent dans `cache`,
                    # ecrit dans le `finally` -- un appel paye n'est jamais rejoue.
                    _case, answers, tokens, duree = future.result()
                    appels += 1
                    tokens_total += tokens
                    duree_total += duree
                    record = evaluate_case(
                        case,
                        answers,
                        score_min=SCORE_MIN,
                        marge_min=MARGE_MIN,
                        confiance_min=CONFIANCE_MIN,
                    )
                    best, _score, _marge, _conf = best_candidate(answers, case.candidats)
                    gagnant = case.candidats[best].get("numero_dpe") if best is not None else None
                    row = _cache_row(cle, case, gagnant, record)
                    row["input_tokens"] = tokens
                    row["duree_ms"] = round(duree * 1000)
                    cache[cle] = row
                    record_by_case[cle] = row
                    if appels % 20 == 0:
                        print(f"[jev_backtest] {appels}/{len(to_call)} appels traites", flush=True)
        finally:
            if len(cache) > connus:
                _save_cache(cache)
                print(f"[jev_backtest] Ecriture de {CACHE_PATH} ({len(cache)} cas)")

    # Reconstruit un `EvalRecord` par cas depuis le cache (frais ou deja connu) --
    # `resolu`/`correct_a_seuil` sont recalcules contre les seuils COURANTS, jamais
    # relus tels quels : un backtest sert a rejouer un autre seuil sans rappeler Jev.
    for case in retenus:
        cle = cache_key(
            case.mutation, case.candidats, model=JEV_MODEL, questions_version=QUESTIONS_VERSION
        )
        row = record_by_case.get(cle)
        if row is None:
            continue
        resolu = (
            row["score"] >= SCORE_MIN
            and row["marge"] >= MARGE_MIN
            and row["confiance"] >= CONFIANCE_MIN
        )
        correct_a_seuil = (
            (row["numero_dpe_propose"] == row["verite_numero_dpe"]) if resolu else None
        )
        records.append(
            EvalRecord(
                regime=row["regime"],
                score=row["score"],
                marge=row["marge"],
                confiance=row["confiance"],
                correct_top1=row["correct_top1"],
                resolu=resolu,
                correct_a_seuil=correct_a_seuil,
            )
        )

    print("\n=== Backtest Jev sur les mutations `trouve` (#36) ===")
    if appels:
        print(
            f"  Appels reels : {appels}  ({tokens_total} tokens, "
            f"{duree_total / appels:.2f} s/appel)"
        )

    report_lines = [
        "# Backtest Jev sur les mutations `trouve` (#36)",
        "",
        f"Echantillon : {len(records)} cas juges "
        f"({sum(1 for r in records if r.regime == REGIME_ISOLE)} isoles, "
        f"{sum(1 for r in records if r.regime == REGIME_MULTI)} multi-candidats), "
        f"modele `{JEV_MODEL}`, questions `{QUESTIONS_VERSION}`.",
    ]

    resume = summarize(records)
    for regime_label, titre in (
        (REGIME_ISOLE, "Regime isole (pool a 1 candidat)"),
        (REGIME_MULTI, "Regime multi (pool a >= 2 candidats)"),
    ):
        stats = resume[regime_label]
        print(f"\n  --- {titre} ---")
        print(f"    n = {stats['n']}, exactitude top-1 = {stats['exactitude_top1']:.1%}")
        report_lines.append(f"\n## {titre}\n")
        report_lines.append(f"- n = {stats['n']}")
        report_lines.append(
            f"- exactitude top-1 (avant tout seuil) : {stats['exactitude_top1']:.1%}"
        )
        if stats["resolus"]:
            print(
                f"    au seuil courant (SCORE_MIN={SCORE_MIN}, MARGE_MIN={MARGE_MIN}, "
                f"CONFIANCE_MIN={CONFIANCE_MIN}) : {stats['resolus']} resolus, "
                f"exactitude {stats['exactitude_a_seuil']:.1%}, "
                f"erreur residuelle {stats['taux_erreur_residuel_a_seuil']:.1%}"
            )
            report_lines.append(
                f"- au seuil courant (SCORE_MIN={SCORE_MIN}, MARGE_MIN={MARGE_MIN}, "
                f"CONFIANCE_MIN={CONFIANCE_MIN}) : {stats['resolus']} resolus, "
                f"exactitude {stats['exactitude_a_seuil']:.1%}, "
                f"**taux d'erreur residuel {stats['taux_erreur_residuel_a_seuil']:.1%}**"
            )
        else:
            print("    au seuil courant : aucun cas resolu.")
            report_lines.append("- au seuil courant : aucun cas resolu.")

        subset = [r for r in records if r.regime == regime_label]
        conf_lines = _print_bucket_table(
            "Exactitude x tranche de confiance", bucket_by(subset, "confiance")
        )
        report_lines += (
            ["", "**Exactitude x tranche de confiance**", "```"] + conf_lines[1:] + ["```"]
        )
        if regime_label == REGIME_MULTI:
            marge_lines = _print_bucket_table(
                "Exactitude x tranche de marge", bucket_by(subset, "marge")
            )
            report_lines += (
                ["", "**Exactitude x tranche de marge**", "```"] + marge_lines[1:] + ["```"]
            )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"\n[jev_backtest] Rapport ecrit : {REPORT_PATH}")


if __name__ == "__main__":
    main()
