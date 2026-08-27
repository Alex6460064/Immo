"""Apparie chaque mutation DVF geocodee (data/processed/dvf_geocoded.parquet, T7)
a un DPE post-reforme (data/processed/dpe_clean.parquet, T8) via l'algorithme
d'ADR 0003 (dedup B -> 4 passes, #23), et ecrit data/processed/dvf_dpe_matched.parquet.

Voir issue #11 (T10) et #23 pour les criteres d'acceptation. Toute la logique
est pure et testee sans I/O : les 4 passes + dedup dans pipeline/lib/match_dvf_dpe.py,
le cablage (scoping commune, lignes de sortie, comptages) dans
pipeline/lib/join_dvf_dpe.py -- ce script ne fait que lecture/ecriture Parquet et
rapport.

--- Choix documente : scoping des DPE candidats par commune ---
Pour chaque mutation, les DPE candidats sont ceux de la MEME commune (code INSEE
== code_insee_ban du DPE). `adresse_normalisee` est une cle rue seule (sans
CP/commune -- voir pipeline/lib/clean_dvf.py) : "RUE DES ECOLES" existe dans
plusieurs communes du perimetre, une passe 1 "texte exact" non scopee produirait
de faux appariements inter-communes. Les DPE sans code_insee_ban exploitable
seraient donc hors de tout groupe -- comptes a part dans le resume (ici : aucun,
verifie sur le jeu courant).

--- Choix documente : seuil de distance passe 2 ---
Importe depuis pipeline/lib/match_distance.DISTANCE_THRESHOLD_M (calibre en T9,
ADR 0003 -- 15 m). Jamais une valeur en dur dans ce script.

Idempotent : si data/processed/dvf_dpe_matched.parquet existe deja et n'est pas
vide, le script ne refait rien (supprimer le fichier pour forcer un re-run).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF  # noqa: E402
from pipeline.lib.join_dvf_dpe import (  # noqa: E402
    DPE_FIELDS,
    OUTPUT_COLUMNS,
    PASSTHROUGH_DVF_FIELDS,
    group_dpe_by_commune,
    match_all,
)
from pipeline.lib.match_distance import DISTANCE_THRESHOLD_M  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DVF_PATH = ROOT / "data" / "processed" / "dvf_geocoded.parquet"
DPE_PATH = ROOT / "data" / "processed" / "dpe_clean.parquet"
OUTPUT_PATH = ROOT / "data" / "processed" / "dvf_dpe_matched.parquet"

def main() -> None:
    for path, prev in ((DVF_PATH, "02b_geocode_ban.py"), (DPE_PATH, "03_clean_dpe.py")):
        if not path.exists():
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print(f"  Lancer d'abord : python pipeline/{prev}", file=sys.stderr)
            sys.exit(1)

    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        print(
            f"[04_join] Fichier deja present ({OUTPUT_PATH}) -- appariement saute "
            "(idempotent). Supprimer le fichier pour forcer un re-run."
        )
        return

    print(f"[04_join] Lecture de {DVF_PATH}")
    dvf_rows = read_parquet_rows(DVF_PATH, PASSTHROUGH_DVF_FIELDS)
    print(f"[04_join] Lecture de {DPE_PATH}")
    dpe_rows = read_parquet_rows(DPE_PATH, DPE_FIELDS)
    print(f"[04_join] {len(dvf_rows)} mutations DVF, {len(dpe_rows)} DPE post-reforme")

    dpe_by_commune, dpe_sans_commune = group_dpe_by_commune(dpe_rows)

    print(f"[04_join] Dedup B + 4 passes (seuil distance passe 2 : {DISTANCE_THRESHOLD_M} m)")
    out_rows, status_counts, dedup_removed = match_all(
        dvf_rows, dpe_by_commune, DISTANCE_THRESHOLD_M
    )

    print(f"[04_join] Ecriture de {OUTPUT_PATH}")
    write_parquet_rows(out_rows, OUTPUT_COLUMNS, OUTPUT_PATH, str_columns=["date_mutation"])

    total = len(out_rows)
    trouve = status_counts.get("trouve", 0)
    resolu_consensus = status_counts.get("resolu_consensus", 0)
    non_trouve = status_counts.get("non_trouve", 0)
    ambigu = status_counts.get("ambigu", 0)
    methode_counts = Counter(
        r["match_methode"]
        for r in out_rows
        if r["match_status"] in ("trouve", "resolu_consensus")
    )
    filtre_type_count = sum(1 for r in out_rows if r["filtre_type_applique"])

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%" if total else "-"

    # Le DPE post-reforme n'existe qu'a partir de juillet 2021 : une paire sur une
    # mutation anterieure apparie un prix ancien a un DPE etabli bien plus tard sur
    # le meme bien (CONTEXT.md, "Vente appariee"). A garder visible, pas enterre --
    # la vue "Impact DPE" du dashboard porte l'avertissement (user story #34).
    etiquette_certaine_pre_reforme = sum(
        1
        for r in out_rows
        if r["match_status"] in ("trouve", "resolu_consensus")
        and (r["date_mutation"] or "") < POST_REFORM_CUTOFF
    )

    print("\n=== Rapport d'appariement DVF x DPE (T10 / #11 / #23, ADR 0003) ===")
    print(f"  Mutations en entree            : {total}")
    print(f"  DPE retires par la dedup (B)   : {dedup_removed}")
    print(f"    - trouve            : {trouve:>6}  ({pct(trouve)})")
    print(f"    - resolu_consensus  : {resolu_consensus:>6}  ({pct(resolu_consensus)})")
    for methode, n in sorted(methode_counts.items(), key=lambda kv: -kv[1]):
        print(f"        dont {methode:<24} : {n:>6}")
    print(f"        dont filtre_type_applique : {filtre_type_count}")
    print(
        f"        dont mutation < {POST_REFORM_CUTOFF} (DPE forcement posterieur au bien vendu)"
        f" : {etiquette_certaine_pre_reforme}"
    )
    print(f"    - non trouve        : {non_trouve:>6}  ({pct(non_trouve)})")
    print(f"    - ambigu            : {ambigu:>6}  ({pct(ambigu)})")
    print(f"  DPE sans commune exploitable (hors candidats) : {dpe_sans_commune}")

    if trouve == 0:
        print(
            "ATTENTION : 0 mutation appariee -- verifier le scoping commune et le "
            "geocodage des deux cotes.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
