"""Groupement generique pour les tables du dashboard (issue #13) -- logique pure,
aucune I/O.

`aggregate_by` groupe des lignes deja porteuses d'une valeur numerique (le prix/m2
est calcule en amont par `pipeline/lib/mutations.py` depuis #26) et emet
moyenne / mediane / effectif `n` par groupe. Appele par `pipeline/05_aggregate.py`
et `dashboard/data.py`.

Regle CLAUDE.md / user story #29 : aucune moyenne n'est produite sans son
effectif `n` -- `aggregate_by` porte toujours `n` sur chaque ligne.
"""

from __future__ import annotations

import statistics
from collections import defaultdict


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
