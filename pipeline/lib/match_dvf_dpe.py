"""Appariement DVF x DPE en 3 passes (ADR 0003) -- logique pure, aucune I/O, aucun reseau.

`pipeline/04_join.py` cable ces fonctions : il lit dvf_geocoded.parquet et
dpe_clean.parquet, groupe les DPE par commune (code INSEE), et pour chaque
commune construit un `DpeIndex` (via `build_dpe_index`) qu'il interroge mutation
par mutation avec `classify_match_indexed`.

Les 3 passes, dans l'ordre (chaque mutation aboutit a exactement un etat --
CONTEXT.md : trouve / non_trouve / ambigu, jamais un choix force au hasard) :

1. **Texte exact** -- un unique DPE candidat a la meme `adresse_normalisee` (non
   vide) que la mutation -> trouve. Si plusieurs (immeuble collectif), on passe
   directement au departage par surface sur ce sous-ensemble.
2. **Distance geocodee** -- sinon, si la mutation est geocodee, les DPE candidats
   eux-memes geocodes a <= `seuil_distance_m` du point mutation. Un seul -> trouve.
   Plusieurs -> departage par surface.
3. **Departage par surface** -- parmi les candidats retenus par la passe 1 ou 2,
   ceux dont la surface est a +/- `SURFACE_TOLERANCE_M2` de la surface de la
   mutation. Un seul -> trouve. Zero, plusieurs, ou surface manquante -> ambigu.

`classify_match(mutation, dpe_candidats, seuil)` est l'implementation de reference
(criteres d'acceptation issue #11) : lisible, O(candidats) par mutation.
`classify_match_indexed(mutation, index)` donne strictement le meme resultat mais
en O(1) amorti sur la passe 2 (grille spatiale) -- indispensable sur les communes
a >10 000 DPE. Un test differentiel verrouille l'equivalence des deux.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from typing import NamedTuple

from pipeline.lib.match_distance import haversine_m

# Departage de la passe 3 (ADR 0003) : ecart tolere entre la surface de la
# mutation DVF ("Surface reelle bati") et la surface habitable du DPE.
SURFACE_TOLERANCE_M2 = 2.0

# Un degre de latitude ~= 111,32 km. Sert au pre-filtre "boite" de la passe 2 et
# au dimensionnement des cellules de la grille spatiale.
_DEG_LAT_M = 111_320.0


class MatchResult(NamedTuple):
    """Resultat d'appariement d'une mutation.

    - `status`   : "trouve" | "non_trouve" | "ambigu"
    - `numero_dpe`: identifiant du DPE apparie (None sauf si status == "trouve")
    - `methode`  : passe ayant conclu -- "texte_exact", "distance",
      "texte_exact_surface", "distance_surface" (None si non trouve / ambigu)
    """

    status: str
    numero_dpe: str | None
    methode: str | None


def _norm(value) -> str:
    return (value or "").strip()


def _surface_tiebreak(mutation: dict, candidats: list[dict], methode: str) -> MatchResult:
    """Passe 3 : garde le DPE candidat dont la surface est a +/- SURFACE_TOLERANCE_M2
    de la surface de la mutation. Un seul -> trouve ; sinon -> ambigu."""
    surface_mutation = mutation.get("surface")
    if surface_mutation is None:
        return MatchResult("ambigu", None, None)

    within = [
        d
        for d in candidats
        if d.get("surface_habitable_logement") is not None
        and abs(d["surface_habitable_logement"] - surface_mutation) <= SURFACE_TOLERANCE_M2
    ]
    if len(within) == 1:
        return MatchResult("trouve", within[0].get("numero_dpe"), f"{methode}_surface")
    return MatchResult("ambigu", None, None)


def _bbox_half_widths(lat: float, seuil_distance_m: float) -> tuple[float, float]:
    """Demi-largeurs (deg lat, deg lon) d'une boite qui circonscrit le cercle de
    rayon `seuil_distance_m` centre a la latitude `lat`."""
    d_lat = seuil_distance_m / _DEG_LAT_M
    cos_lat = math.cos(math.radians(lat)) or 1e-9
    d_lon = seuil_distance_m / (_DEG_LAT_M * abs(cos_lat))
    return d_lat, d_lon


def _within_distance(
    lat: float, lon: float, candidats: Iterable[dict], seuil_distance_m: float
) -> list[dict]:
    """DPE geocodes a <= `seuil_distance_m` du point (lat, lon). Le haversine est la
    coupe qui decide ; le test de boite ne fait qu'eviter de le calculer trop souvent."""
    d_lat, d_lon = _bbox_half_widths(lat, seuil_distance_m)
    near = []
    for d in candidats:
        d_la, d_lo = d.get("lat"), d.get("lon")
        if d_la is None or d_lo is None:
            continue
        if abs(d_la - lat) > d_lat or abs(d_lo - lon) > d_lon:
            continue
        if haversine_m(lat, lon, d_la, d_lo) <= seuil_distance_m:
            near.append(d)
    return near


def _resolve(mutation: dict, exact: list[dict], near: list[dict]) -> MatchResult:
    """Applique passes 1->2->3 a partir des sous-ensembles deja calcules :
    `exact` = DPE a adresse_normalisee identique, `near` = DPE geocodes a <= seuil
    (liste vide si la mutation n'a pas de coordonnees : la passe 2 ne trouve rien)."""
    if len(exact) == 1:
        return MatchResult("trouve", exact[0].get("numero_dpe"), "texte_exact")
    if len(exact) > 1:
        return _surface_tiebreak(mutation, exact, "texte_exact")

    if len(near) == 1:
        return MatchResult("trouve", near[0].get("numero_dpe"), "distance")
    if len(near) > 1:
        return _surface_tiebreak(mutation, near, "distance")
    return MatchResult("non_trouve", None, None)


def classify_match(
    mutation: dict, dpe_candidats: list[dict], seuil_distance_m: float
) -> MatchResult:
    """Apparie une mutation DVF a un DPE via l'algorithme en 3 passes (ADR 0003).

    Implementation de reference (criteres d'acceptation issue #11).

    `mutation` : dict avec `adresse_normalisee`, `lat`, `lon`, `surface`.
    `dpe_candidats` : DPE deja restreints a la commune de la mutation, chacun un
        dict avec `numero_dpe`, `adresse_normalisee`, `lat`, `lon`,
        `surface_habitable_logement`.
    `seuil_distance_m` : seuil de la passe 2 (calibre en T9, voir
        `pipeline.lib.match_distance.DISTANCE_THRESHOLD_M`) -- passe en parametre,
        jamais lu en dur ici.
    """
    if not dpe_candidats:
        return MatchResult("non_trouve", None, None)

    adresse_mutation = _norm(mutation.get("adresse_normalisee"))
    exact = (
        [d for d in dpe_candidats if _norm(d.get("adresse_normalisee")) == adresse_mutation]
        if adresse_mutation
        else []
    )

    lat, lon = mutation.get("lat"), mutation.get("lon")
    near = (
        []
        if lat is None or lon is None
        else _within_distance(lat, lon, dpe_candidats, seuil_distance_m)
    )
    return _resolve(mutation, exact, near)


class DpeIndex(NamedTuple):
    """Index des DPE d'une commune : `by_addr` pour la passe 1 (texte exact),
    `grid` (cellules de ~`seuil` de cote) pour la passe 2 (distance). Construit
    une fois par commune, interroge par `classify_match_indexed`."""

    by_addr: dict[str, list[dict]]
    grid: dict[tuple[int, int], list[dict]]
    cell_deg: float
    seuil_distance_m: float
    size: int


def build_dpe_index(dpe_candidats: list[dict], seuil_distance_m: float) -> DpeIndex:
    """Construit le `DpeIndex` des DPE d'une commune pour le seuil de distance donne."""
    by_addr: dict[str, list[dict]] = defaultdict(list)
    grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
    cell_deg = max(seuil_distance_m / _DEG_LAT_M, 1e-9)

    for d in dpe_candidats:
        adresse = _norm(d.get("adresse_normalisee"))
        if adresse:
            by_addr[adresse].append(d)
        lat, lon = d.get("lat"), d.get("lon")
        if lat is not None and lon is not None:
            grid[(int(lat / cell_deg), int(lon / cell_deg))].append(d)

    return DpeIndex(dict(by_addr), dict(grid), cell_deg, seuil_distance_m, len(dpe_candidats))


def classify_match_indexed(mutation: dict, index: DpeIndex) -> MatchResult:
    """Comme `classify_match` mais via un `DpeIndex` pre-construit -- meme resultat,
    sans balayer tous les DPE de la commune a chaque mutation."""
    if index.size == 0:
        return MatchResult("non_trouve", None, None)

    adresse_mutation = _norm(mutation.get("adresse_normalisee"))
    exact = index.by_addr.get(adresse_mutation, []) if adresse_mutation else []

    lat, lon = mutation.get("lat"), mutation.get("lon")
    near: list[dict] = []
    if lat is not None and lon is not None:
        d_lat, d_lon = _bbox_half_widths(lat, index.seuil_distance_m)
        cell = index.cell_deg
        i_lo, i_hi = int((lat - d_lat) / cell), int((lat + d_lat) / cell)
        j_lo, j_hi = int((lon - d_lon) / cell), int((lon + d_lon) / cell)
        bucket: list[dict] = []
        for i in range(i_lo, i_hi + 1):
            for j in range(j_lo, j_hi + 1):
                bucket.extend(index.grid.get((i, j), ()))
        near = _within_distance(lat, lon, bucket, index.seuil_distance_m)

    return _resolve(mutation, list(exact), near)


def match_mutation(mutation: dict, dpe_candidats: list[dict], seuil_distance_m: float) -> str:
    """Etat d'appariement d'une mutation : "trouve" | "non_trouve" | "ambigu".

    Signature des criteres d'acceptation de l'issue #11. Enveloppe fine sur
    `classify_match` quand seul l'etat compte (rapport, comptages)."""
    return classify_match(mutation, dpe_candidats, seuil_distance_m).status
