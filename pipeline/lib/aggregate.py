"""Agregats pour les 3 tables du dashboard (issue #13) -- logique pure, aucune I/O.

`pipeline/05_aggregate.py` lit les parquets d'appariement (04_join) et de
rattachement IRIS (04b_join_iris), calcule le prix/m2 de chaque mutation via
`price_per_m2`, puis groupe via `aggregate_by`.

Regle CLAUDE.md / user story #29 : aucune moyenne n'est produite sans son
effectif `n` -- `aggregate_by` porte toujours `n` sur chaque ligne.
"""

from __future__ import annotations

import statistics
from collections import defaultdict


def price_per_m2(price: float | None, surface: float | None) -> float | None:
    """Prix au m2 d'une mutation. None si prix ou surface manquant / non strictement
    positif -- ces lignes sont exclues des agregats (documentees en amont par
    02_clean_dvf, ce garde-fou est une defense en profondeur)."""
    if price is None or surface is None or price <= 0 or surface <= 0:
        return None
    return price / surface


# Etats d'appariement porteurs d'une etiquette DPE certaine (spec §5, D3) : les deux
# entrent dans la vue Impact DPE. `resolu_consensus` = identite du DPE inconnue mais
# etiquette certaine par consensus -- se lit "ambigu sauve", pas "trouve degrade".
_IMPACT_DPE_STATUSES = ("trouve", "resolu_consensus")


def impact_dpe_rows(rows: list[dict], post_reform_cutoff: str) -> list[dict]:
    """Sous-ensemble des mutations retenu pour l'agregat Impact DPE (`agg_dpe`) :
    appariees a une etiquette certaine (`match_status` dans `_IMPACT_DPE_STATUSES`)
    ET `date_mutation` >= `post_reform_cutoff` -- apparier un prix anterieur a la
    reforme a un DPE etabli bien plus tard ne mesure rien (NOTES.md 2026-08-27).
    Date absente -> exclue (comparaison lexicographique sur chaine ISO)."""
    return [
        row
        for row in rows
        if row.get("match_status") in _IMPACT_DPE_STATUSES
        and (row.get("date_mutation") or "") >= post_reform_cutoff
    ]


def _sort_key(values: tuple) -> tuple:
    """Tri deterministe tolerant aux None : par cle, un None triant apres toute
    valeur presente (`False < True`)."""
    return tuple((v is None, v) for v in values)


def aggregate_by(
    rows: list[dict], group_keys: list[str], *, value_field: str = "prix_m2"
) -> list[dict]:
    """Groupe `rows` par `group_keys`, emet une ligne par groupe :
    `{**cles_du_groupe, "n": <effectif>, "moyenne": <fmean>, "mediane": <median>}`.

    Seules les lignes dont `value_field` est un nombre comptent (n = leur nombre) ;
    un groupe sans aucune ligne exploitable est omis. Resultat trie par cle de
    groupe (les cles None en dernier), pour un output reproductible.
    """
    buckets: dict[tuple, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(value_field)
        if value is None:
            continue
        key = tuple(row.get(k) for k in group_keys)
        buckets[key].append(value)

    result = []
    for key in sorted(buckets, key=_sort_key):
        values = buckets[key]
        row = dict(zip(group_keys, key, strict=True))
        row["n"] = len(values)
        row["moyenne"] = statistics.fmean(values)
        row["mediane"] = statistics.median(values)
        result.append(row)
    return result
