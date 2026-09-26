"""Cubes precalcules pour le site statique (#44) -- logique pure, aucune I/O.

Le site Observable Framework ne recalcule rien : il filtre et affiche ce que ce
module produit. Chaque cube est construit en appelant les fonctions du seam
`dashboard/data.py` (memes chaines que le pipeline, ADR 0006 / #28), jamais en
les reimplementant -- les tests verifient l'egalite cube == seam selection par
selection.

Granularites :
- Impact DPE : les medianes ne s'additionnent pas -> un agregat par plage
  d'annees [min, max] (toutes les paires). Les comptages, eux, s'additionnent sur
  des annees disjointes -> une ligne par annee, sommee cote site.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from dashboard.data import (
    DPE_GROUPS,
    TYPES_BIEN,
    impact_dpe_aggregate,
    impact_dpe_breakdown,
    market_trend_global,
)
from pipeline.lib.aggregate import aggregate_by
from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF
from pipeline.lib.impact_dpe import impact_dpe_slice


def year_ranges(years: Sequence[str]) -> list[tuple[str, str]]:
    """Toutes les plages [min, max] ordonnees d'une liste d'annees triee."""
    ys = sorted(years)
    return [(lo, hi) for i, lo in enumerate(ys) for hi in ys[i:]]


def _by_commune(rows: Sequence[dict]) -> dict[str, list[dict]]:
    # Tous les lots d'une mutation partagent la commune : partitionner avant le
    # repli ne change aucun point, et divise le cout par le nombre de communes.
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r.get("commune")].append(r)
    return out


def cube_start_year(annee_min: str, cutoff: str = POST_REFORM_CUTOFF) -> str:
    """Annee de debut effective d'une plage dans `impact_cube` : aucune annee
    anterieure a celle du `cutoff` ne porte de point Impact DPE, donc une plage
    [2016, 2023] agrege exactement les memes points que [2021, 2023]."""
    return max(annee_min, cutoff[:4])


def impact_cube(
    matched_rows: Sequence[dict],
    communes: Sequence[str],
    years: Sequence[str],
    cutoff: str = POST_REFORM_CUTOFF,
) -> list[dict]:
    """`impact_dpe_aggregate` par commune x plage d'annees (type de bien et
    regroupement en lignes). Seules les plages commencant a partir de l'annee du
    `cutoff` sont exportees (cf. `cube_start_year`) ; plages sans point omises."""
    parts = _by_commune(matched_rows)
    post = [y for y in years if y >= cutoff[:4]]
    out = []
    for commune in communes:
        rows = parts.get(commune, [])
        for lo, hi in year_ranges(post):
            agg = impact_dpe_aggregate(
                rows, commune=commune, date_min=f"{lo}-01-01", date_max=f"{hi}-12-31"
            )
            out.extend({"commune": commune, "annee_min": lo, "annee_max": hi, **r} for r in agg)
    return out


def impact_counts_by_year(
    matched_rows: Sequence[dict], communes: Sequence[str], years: Sequence[str]
) -> list[dict]:
    """`impact_dpe_breakdown` par commune x annee x type (None = tous) x
    regroupement (None = tous). Cellules entierement nulles omises."""
    parts = _by_commune(matched_rows)
    out = []
    for commune in communes:
        rows = parts.get(commune, [])
        for annee in sorted(years):
            for type_local in (None, *TYPES_BIEN):
                for groupe in (None, *DPE_GROUPS):
                    b = impact_dpe_breakdown(
                        rows,
                        commune=commune,
                        type_local=type_local,
                        groupe=groupe,
                        date_min=f"{annee}-01-01",
                        date_max=f"{annee}-12-31",
                    )
                    if any(b.values()):
                        out.append(
                            {
                                "commune": commune,
                                "annee": annee,
                                "type_local": type_local,
                                "groupe": groupe,
                                **b,
                            }
                        )
    return out


def global_trend(matched_rows: Sequence[dict], types: Sequence[str]) -> list[dict]:
    """Courbe de reference « toutes communes » (`market_trend_global`) par type."""
    return [
        {"type_local": t, **r}
        for t in types
        for r in market_trend_global(matched_rows, type_local=t)
    ]


def label_ladder(matched_rows: Sequence[dict], cutoff: str = POST_REFORM_CUTOFF) -> list[dict]:
    """Prix/m2 par etiquette EXACTE (A..G) x type, sur la tranche Impact DPE
    (etiquette certaine, post-reforme) : ensemble du perimetre (`commune` None)
    puis par commune. Meme chaine que `agg_dpe.parquet` (05_aggregate)."""
    points = impact_dpe_slice(list(matched_rows), cutoff=cutoff).points
    tous = [{"commune": None, **r} for r in aggregate_by(points, ["etiquette_dpe", "type_local"])]
    par_commune = aggregate_by(points, ["commune", "etiquette_dpe", "type_local"])
    return tous + par_commune


def commune_matching(matched_rows: Sequence[dict]) -> list[dict]:
    """Effectifs par commune x `match_status` -- meme unite que
    `load_matching_counts` (lignes de `dvf_dpe_matched`), donc sommables en
    exactement le taux global affiche."""
    c = Counter((r.get("commune"), r.get("match_status")) for r in matched_rows)
    return [{"commune": k[0], "match_status": k[1], "n": n} for k, n in sorted(c.items())]


def commune_table(
    marche_rows: Sequence[dict], communes: Sequence[str], *, latest: str, recul: int = 5
) -> list[dict]:
    """Une ligne par commune x type : mediane / n de l'annee `latest` et
    `evolution` de la mediane depuis `annee_base` = `latest - recul` (None si une
    des deux annees manque).
    Commune sans vente l'annee `latest` : conservee, valeurs None (jamais
    supprimee en silence)."""
    by = {(r["commune"], r["type_local"], r["annee"]): r for r in marche_rows}
    base = str(int(latest) - recul)
    out = []
    for commune in communes:
        for t in TYPES_BIEN:
            cur = by.get((commune, t, latest))
            old = by.get((commune, t, base))
            evo = None
            if cur and old and old["mediane"]:
                evo = cur["mediane"] / old["mediane"] - 1
            out.append(
                {
                    "commune": commune,
                    "type_local": t,
                    "annee": latest,
                    "mediane": cur["mediane"] if cur else None,
                    "moyenne": cur["moyenne"] if cur else None,
                    "n": int(cur["n"]) if cur else 0,
                    "annee_base": base,
                    "n_base": int(old["n"]) if old else 0,
                    "evolution": evo,
                }
            )
    return out
