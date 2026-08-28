"""Cablage pur de l'appariement DVF x DPE (T10 / #11, brique #23) -- aucune I/O.

`pipeline/04_join.py` se limite a la lecture/ecriture Parquet et a l'impression du
rapport ; toute la logique testable vit ici et dans `pipeline/lib/match_dvf_dpe.py`
(les 4 passes + dedup).

- `group_dpe_by_commune` : scoping des candidats (un DPE n'est candidat que pour
  les mutations de sa commune, `code_insee_ban` == `code_insee` -- voir ADR 0003).
  Reste public/teste mais appele par `match_all`, plus par le script.
- `match_all(dvf_rows, dpe_rows, seuil) -> (out_rows, MatchReport)` : le `join`
  complet. Scope les DPE par commune, construit un `DpeIndex` par commune (grille
  spatiale, sinon la passe 2 balaierait les >10 000 DPE de Bayonne/Anglet/Biarritz
  a chaque mutation), interroge chaque mutation, emet une ligne de sortie par
  mutation et remplit un `MatchReport` avec tous les comptages du rapport.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import NamedTuple

from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF
from pipeline.lib.dvf_schema import DVF_GEOCODED_COLUMNS
from pipeline.lib.match_dvf_dpe import (
    IMPACT_DPE_STATUSES,
    build_dpe_index,
    classify_match_indexed,
)

# Champs de la mutation DVF recopies verbatim dans dvf_dpe_matched.parquet
# (toutes les colonnes de dvf_geocoded.parquet -- schema partage, voir dvf_schema.py, #22).
PASSTHROUGH_DVF_FIELDS = list(DVF_GEOCODED_COLUMNS)

# Champs lus depuis dpe_clean.parquet pour chaque candidat : identifiant + date
# (dedup), adresse + coordonnees + surface (passes 1-3), etiquette / GES / type /
# periode (passe 4 consensus, filtre C, contexte de sortie -- spec #23 §6).
DPE_FIELDS = [
    "numero_dpe",
    "date_etablissement_dpe",
    "etiquette_dpe",
    "etiquette_ges",
    "type_batiment",
    "periode_construction",
    "adresse_normalisee",
    "surface_habitable_logement",
    "code_insee_ban",
    "lat",
    "lon",
]

# Schema de dvf_dpe_matched.parquet : mutation DVF (schema partage, dvf_schema.py)
# + colonnes d'appariement (#23).
OUTPUT_COLUMNS = {
    **DVF_GEOCODED_COLUMNS,
    "match_status": "VARCHAR",
    "match_methode": "VARCHAR",
    "filtre_type_applique": "BOOLEAN",
    "numero_dpe": "VARCHAR",
    "etiquette_dpe": "VARCHAR",
    "etiquette_ges": "VARCHAR",
    "type_batiment": "VARCHAR",
    "periode_construction": "VARCHAR",
}


def group_dpe_by_commune(dpe_rows: list[dict]) -> tuple[dict[str, list[dict]], int]:
    """Groupe les DPE par code INSEE de commune (`code_insee_ban`).

    Retourne (groupes, nb_dpe_sans_commune). Un DPE sans `code_insee_ban` n'est
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


class MatchReport(NamedTuple):
    """Synthese d'un run d'appariement -- tous les comptages imprimes par
    `pipeline/04_join.py`, calcules ici (le script ne fait qu'afficher).

    Dicts ordinaires (pas `Counter`) : `MatchReport` est immuable et comparable
    en test. `methode_counts` et `pre_reforme_count` ne portent que sur les
    lignes a etiquette certaine (`status` dans `IMPACT_DPE_STATUSES`) ;
    `filtre_type_count` porte sur toutes les mutations.
    """

    total: int
    dedup_removed: int
    status_counts: dict[str, int]
    methode_counts: dict[str, int]
    filtre_type_count: int
    pre_reforme_count: int
    dpe_sans_commune: int


def match_all(
    dvf_rows: list[dict],
    dpe_rows: list[dict],
    seuil_distance_m: float,
) -> tuple[list[dict], MatchReport]:
    """`join` complet DVF x DPE. Retourne (lignes de sortie, `MatchReport`).

    Scope les DPE par commune (`group_dpe_by_commune`), construit un `DpeIndex`
    par commune, interroge chaque mutation. Le contexte bati (etiquette, GES,
    type, periode) est porte par `MatchResult` -- sur `resolu_consensus` le
    `numero_dpe` est NULL mais l'etiquette est connue par consensus.
    """
    dpe_by_commune, dpe_sans_commune = group_dpe_by_commune(dpe_rows)

    index_by_commune = {
        code: build_dpe_index(rows, seuil_distance_m) for code, rows in dpe_by_commune.items()
    }
    empty_index = build_dpe_index([], seuil_distance_m)

    dpe_before = sum(len(rows) for rows in dpe_by_commune.values())
    dpe_after = sum(index.size for index in index_by_commune.values())
    dedup_removed = dpe_before - dpe_after

    out_rows: list[dict] = []
    status_counts: Counter = Counter()
    methode_counts: Counter = Counter()
    filtre_type_count = 0
    pre_reforme_count = 0
    for mutation in dvf_rows:
        code = (mutation.get("code_insee") or "").strip()
        result = classify_match_indexed(mutation, index_by_commune.get(code, empty_index))
        status_counts[result.status] += 1

        certaine = result.status in IMPACT_DPE_STATUSES
        if certaine and result.methode is not None:
            methode_counts[result.methode] += 1
        if result.filtre_type_applique:
            filtre_type_count += 1
        if certaine and (mutation.get("date_mutation") or "") < POST_REFORM_CUTOFF:
            pre_reforme_count += 1

        row = {name: mutation.get(name) for name in PASSTHROUGH_DVF_FIELDS}
        row["match_status"] = result.status
        row["match_methode"] = result.methode
        row["filtre_type_applique"] = result.filtre_type_applique
        row["numero_dpe"] = result.numero_dpe
        row["etiquette_dpe"] = result.etiquette_dpe
        row["etiquette_ges"] = result.etiquette_ges
        row["type_batiment"] = result.type_batiment
        row["periode_construction"] = result.periode_construction
        out_rows.append(row)

    report = MatchReport(
        total=len(out_rows),
        dedup_removed=dedup_removed,
        status_counts=dict(status_counts),
        methode_counts=dict(methode_counts),
        filtre_type_count=filtre_type_count,
        pre_reforme_count=pre_reforme_count,
        dpe_sans_commune=dpe_sans_commune,
    )
    return out_rows, report
