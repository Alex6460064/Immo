"""Cablage pur de l'appariement DVF x DPE (T10 / #11, brique #23) -- aucune I/O.

`pipeline/04_join.py` se limite a la lecture/ecriture Parquet et au rapport ;
toute la logique testable vit ici et dans `pipeline/lib/match_dvf_dpe.py`
(les 4 passes + dedup).

- `group_dpe_by_commune` : scoping des candidats (un DPE n'est candidat que pour
  les mutations de sa commune, `code_insee_ban` == `code_insee` -- voir ADR 0003).
- `match_all` : construit un `DpeIndex` par commune (grille spatiale, sinon la
  passe 2 balaierait les >10 000 DPE de Bayonne/Anglet/Biarritz a chaque
  mutation), interroge chaque mutation, emet une ligne de sortie par mutation et
  compte les etats + les DPE retires par la dedup (brique B).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from pipeline.lib.match_dvf_dpe import build_dpe_index, classify_match_indexed

# Champs de la mutation DVF recopies verbatim dans dvf_dpe_matched.parquet
# (toutes les colonnes de dvf_geocoded.parquet).
PASSTHROUGH_DVF_FIELDS = [
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

# Schema de dvf_dpe_matched.parquet : mutation DVF + colonnes d'appariement (#23).
OUTPUT_COLUMNS = {
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


def match_all(
    dvf_rows: list[dict],
    dpe_by_commune: dict[str, list[dict]],
    seuil_distance_m: float,
) -> tuple[list[dict], Counter, int]:
    """Apparie chaque mutation. Retourne (lignes de sortie, compteur par statut,
    nb de DPE retires par la dedup B).

    Le contexte bati (etiquette, GES, type, periode) est porte par `MatchResult`
    -- plus de lookup `etiquette_by_numero` : sur `resolu_consensus` le
    `numero_dpe` est NULL mais l'etiquette est connue par consensus.
    """
    index_by_commune = {
        code: build_dpe_index(rows, seuil_distance_m)
        for code, rows in dpe_by_commune.items()
    }
    empty_index = build_dpe_index([], seuil_distance_m)

    dpe_before = sum(len(rows) for rows in dpe_by_commune.values())
    dpe_after = sum(index.size for index in index_by_commune.values())
    dedup_removed = dpe_before - dpe_after

    out_rows: list[dict] = []
    status_counts: Counter = Counter()
    for mutation in dvf_rows:
        code = (mutation.get("code_insee") or "").strip()
        result = classify_match_indexed(mutation, index_by_commune.get(code, empty_index))
        status_counts[result.status] += 1

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

    return out_rows, status_counts, dedup_removed
