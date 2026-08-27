"""Apparie chaque mutation DVF geocodee (data/processed/dvf_geocoded.parquet, T7)
a un DPE post-reforme (data/processed/dpe_clean.parquet, T8) via l'algorithme en
3 passes d'ADR 0003, et ecrit data/processed/dvf_dpe_matched.parquet.

Voir issue #11 (T10) pour les criteres d'acceptation. La logique d'appariement
elle-meme est pure et testee sans I/O dans pipeline/lib/match_dvf_dpe.py --
ce script ne fait que le cablage : lecture parquet, scoping des candidats,
ecriture, rapport.

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
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF  # noqa: E402
from pipeline.lib.match_distance import DISTANCE_THRESHOLD_M  # noqa: E402
from pipeline.lib.match_dvf_dpe import build_dpe_index, classify_match_indexed  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DVF_PATH = ROOT / "data" / "processed" / "dvf_geocoded.parquet"
DPE_PATH = ROOT / "data" / "processed" / "dpe_clean.parquet"
OUTPUT_PATH = ROOT / "data" / "processed" / "dvf_dpe_matched.parquet"

_DVF_COLUMNS = [
    "identifiant_document",
    "no_disposition",
    "date_mutation",
    "nature_mutation",
    "code_insee",
    "commune",
    "code_postal",
    "adresse_brute",
    "adresse_normalisee",
    "type_local",
    "nombre_pieces_principales",
    "surface",
    "prix",
    "lat",
    "lon",
]

_DPE_COLUMNS = [
    "numero_dpe",
    "date_etablissement_dpe",
    "etiquette_dpe",
    "adresse_normalisee",
    "surface_habitable_logement",
    "code_insee_ban",
    "lat",
    "lon",
]

# Colonnes de sortie : toutes celles de dvf_geocoded + 4 colonnes d'appariement.
_OUTPUT_COLUMNS = {
    "identifiant_document": "VARCHAR",
    "no_disposition": "VARCHAR",
    "date_mutation": "VARCHAR",
    "nature_mutation": "VARCHAR",
    "code_insee": "VARCHAR",
    "commune": "VARCHAR",
    "code_postal": "VARCHAR",
    "adresse_brute": "VARCHAR",
    "adresse_normalisee": "VARCHAR",
    "type_local": "VARCHAR",
    "nombre_pieces_principales": "VARCHAR",
    "surface": "DOUBLE",
    "prix": "DOUBLE",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
    "match_status": "VARCHAR",
    "match_methode": "VARCHAR",
    "numero_dpe": "VARCHAR",
    "etiquette_dpe": "VARCHAR",
}


def group_dpe_by_commune(dpe_rows: list[dict]) -> tuple[dict[str, list[dict]], int]:
    """Groupe les DPE par code INSEE de commune (code_insee_ban).

    Retourne (groupes, nb_dpe_sans_commune). Un DPE sans code_insee_ban n'est
    candidat pour aucune mutation -- compte a part, pas silencieusement ignore.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    sans_commune = 0
    for dpe in dpe_rows:
        code = (dpe.get("code_insee_ban") or "").strip()
        if not code:
            sans_commune += 1
            continue
        groups[code].append(dpe)
    return groups, sans_commune


def match_all(
    dvf_rows: list[dict],
    dpe_by_commune: dict[str, list[dict]],
    etiquette_by_numero: dict[str, str],
    seuil_distance_m: float,
) -> tuple[list[dict], Counter]:
    """Apparie chaque mutation, retourne (lignes de sortie, compteur par statut).

    Un `DpeIndex` est construit une fois par commune (grille spatiale) puis
    interroge mutation par mutation -- sinon la passe 2 balaierait les >10 000
    DPE de Bayonne/Anglet/Biarritz a chaque mutation.
    """
    out_rows: list[dict] = []
    status_counts: Counter = Counter()

    index_by_commune = {
        code: build_dpe_index(dpe_rows, seuil_distance_m)
        for code, dpe_rows in dpe_by_commune.items()
    }
    empty_index = build_dpe_index([], seuil_distance_m)

    for mutation in dvf_rows:
        code = (mutation.get("code_insee") or "").strip()
        result = classify_match_indexed(mutation, index_by_commune.get(code, empty_index))
        status_counts[result.status] += 1

        row = {name: mutation.get(name) for name in _DVF_COLUMNS}
        row["match_status"] = result.status
        row["match_methode"] = result.methode
        row["numero_dpe"] = result.numero_dpe
        row["etiquette_dpe"] = (
            etiquette_by_numero.get(result.numero_dpe) if result.numero_dpe else None
        )
        out_rows.append(row)

    return out_rows, status_counts


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
    dvf_rows = read_parquet_rows(DVF_PATH, _DVF_COLUMNS)
    print(f"[04_join] Lecture de {DPE_PATH}")
    dpe_rows = read_parquet_rows(DPE_PATH, _DPE_COLUMNS)
    print(f"[04_join] {len(dvf_rows)} mutations DVF, {len(dpe_rows)} DPE post-reforme")

    dpe_by_commune, dpe_sans_commune = group_dpe_by_commune(dpe_rows)
    etiquette_by_numero = {
        d["numero_dpe"]: d.get("etiquette_dpe") for d in dpe_rows if d.get("numero_dpe")
    }

    print(f"[04_join] Appariement 3 passes (seuil distance passe 2 : {DISTANCE_THRESHOLD_M} m)")
    out_rows, status_counts = match_all(
        dvf_rows, dpe_by_commune, etiquette_by_numero, DISTANCE_THRESHOLD_M
    )

    print(f"[04_join] Ecriture de {OUTPUT_PATH}")
    write_parquet_rows(out_rows, _OUTPUT_COLUMNS, OUTPUT_PATH, str_columns=["date_mutation"])

    total = len(out_rows)
    trouve = status_counts.get("trouve", 0)
    non_trouve = status_counts.get("non_trouve", 0)
    ambigu = status_counts.get("ambigu", 0)
    methode_counts = Counter(r["match_methode"] for r in out_rows if r["match_status"] == "trouve")

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%" if total else "-"

    # Le DPE post-reforme n'existe qu'a partir de juillet 2021 : un "trouve" sur une
    # mutation anterieure apparie un prix ancien a un DPE etabli bien plus tard sur
    # le meme bien (CONTEXT.md, "Vente appariee"). A garder visible, pas enterre --
    # la vue "Impact DPE" du dashboard porte l'avertissement (user story #34).
    trouve_pre_reforme = sum(
        1
        for r in out_rows
        if r["match_status"] == "trouve" and (r["date_mutation"] or "") < POST_REFORM_CUTOFF
    )

    print("\n=== Rapport d'appariement DVF x DPE (T10 / #11, ADR 0003) ===")
    print(f"  Mutations en entree            : {total}")
    print(f"    - trouve      : {trouve:>6}  ({pct(trouve)})")
    for methode, n in sorted(methode_counts.items(), key=lambda kv: -kv[1]):
        print(f"        dont {methode:<22} : {n:>6}")
    print(
        f"        dont mutation < {POST_REFORM_CUTOFF} (DPE forcement posterieur au bien vendu)"
        f" : {trouve_pre_reforme}"
    )
    print(f"    - non trouve  : {non_trouve:>6}  ({pct(non_trouve)})")
    print(f"    - ambigu      : {ambigu:>6}  ({pct(ambigu)})")
    print(f"  DPE sans commune exploitable (hors candidats) : {dpe_sans_commune}")

    if trouve == 0:
        print(
            "ATTENTION : 0 mutation appariee -- verifier le scoping commune et le "
            "geocodage des deux cotes.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
