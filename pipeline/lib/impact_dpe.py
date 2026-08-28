"""Chaine unique de la vue "Impact DPE" (prix/m2 par etiquette DPE) -- logique
pure, aucune I/O.

Une seule vue analytique, un seul module : `pipeline/05_aggregate.py` (produit
`agg_dpe.parquet`, sans filtre) et `dashboard/data.py` (re-agrege a la volee
avec les filtres commune / periode de #15) appellent tous deux
`impact_dpe_slice`. Avant ce module la chaine
`mutation_price_points(extra_keys) -> filtre -> impact_dpe_rows(cutoff) ->
aggregate_by` etait ecrite deux fois, synchronisee seulement par des docstrings
(revue d'archi, issue #28, jumelle de #27). ADR 0006 (docs/adr/) impose deja
cette unicite -- ce module l'execute.

Decoupage : ici = mecanique repli / filtre / cutoff + comptages ; le dashboard =
la semantique de la selection utilisateur (`keep` construit cote dashboard,
`dpe_group` et les bornes de periode y restent).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from pipeline.lib.match_dvf_dpe import IMPACT_DPE_STATUSES
from pipeline.lib.mutations import mutation_price_points

# Dimensions qui, combinees a la cle mutation, definissent un point Impact DPE :
# l'etiquette (seule dimension consommee par la vue) et le statut d'appariement
# (pour separer certain / ambigu dans les comptages). Le litteral une seule fois
# -- il etait repete dans 05_aggregate et 2x dans dashboard/data.
IMPACT_DPE_EXTRA_KEYS: tuple[str, str] = ("etiquette_dpe", "match_status")


def impact_dpe_rows(rows: list[dict], post_reform_cutoff: str) -> list[dict]:
    """Sous-ensemble des mutations retenu pour l'agregat Impact DPE (`agg_dpe`) :
    appariees a une etiquette certaine (`match_status` dans `IMPACT_DPE_STATUSES`)
    ET `date_mutation` >= `post_reform_cutoff` -- apparier un prix anterieur a la
    reforme a un DPE etabli bien plus tard ne mesure rien (NOTES.md 2026-08-27).
    Date absente -> exclue (comparaison lexicographique sur chaine ISO)."""
    return [
        row
        for row in rows
        if row.get("match_status") in IMPACT_DPE_STATUSES
        and (row.get("date_mutation") or "") >= post_reform_cutoff
    ]


class ImpactDpeSlice(NamedTuple):
    """La "tranche Impact DPE" (CONTEXT.md) : les points prix/m2 qui alimentent
    la vue, plus tous les comptages du rapport. Immuable et comparable en test.

    - `points` : un point par (mutation, etiquette) a etiquette certaine, date
      >= cutoff, prix/m2 exploitable -- ce que `aggregate_by` consomme.
    - `n_points` : total des points replies, tous statuts confondus -- sur
      l'entree entiere (le repli est independant de `keep`).
    - `etiquette_certaine` / `resolu_consensus` / `pre_reforme` : comptages APRES
      `keep`. `pre_reforme` = etiquette certaine mais mutation < cutoff (comptee,
      hors `points`). `resolu_consensus` = parmi `points`.
    - `exclusions` : `{mixte, nature, hors_bande, sans_habitation}` verbatim de
      `mutation_price_points` -- sur l'entree entiere, comme `n_points`.
    """

    points: list[dict]
    n_points: int
    etiquette_certaine: int
    resolu_consensus: int
    pre_reforme: int
    exclusions: dict[str, int]


def impact_dpe_slice(
    matched_rows: list[dict],
    *,
    cutoff: str,
    keep: Callable[[dict], bool] | None = None,
) -> ImpactDpeSlice:
    """Replie `matched_rows` (lignes-lots `dvf_dpe_matched`) en points prix/m2 au
    niveau (mutation, etiquette), applique `keep` s'il est fourni (predicat
    post-repli, pre-cutoff -- la selection UI du dashboard), decoupe le resultat.

    `keep` s'applique APRES le repli : tous les points d'une mutation partagent
    commune / type_local / date (mono-type habitation, ADR 0006), donc filtrer
    les points revient a filtrer les mutations -- mais le prix/m2 reste calcule
    sur la surface habitation de TOUTE la mutation, jamais sur le seul point garde.

    `keep=None` -> aucun filtre : `05_aggregate.py` obtient exactement les
    mutations de `agg_dpe.parquet` (invariant
    `test_slice_sans_keep_egale_recette_pipeline`)."""
    all_points, exclusions = mutation_price_points(matched_rows, extra_keys=IMPACT_DPE_EXTRA_KEYS)
    kept = all_points if keep is None else [p for p in all_points if keep(p)]

    certaine = [p for p in kept if p.get("match_status") in IMPACT_DPE_STATUSES]
    points = impact_dpe_rows(kept, cutoff)
    return ImpactDpeSlice(
        points=points,
        n_points=len(all_points),
        etiquette_certaine=len(certaine),
        resolu_consensus=sum(1 for p in points if p.get("match_status") == "resolu_consensus"),
        pre_reforme=len(certaine) - len(points),
        exclusions=exclusions,
    )
