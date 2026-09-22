"""Appariement DVF x DPE : dedup (B) puis 4 passes (ADR 0003, #23) -- logique pure,
aucune I/O, aucun reseau.

`pipeline/lib/join_dvf_dpe.py` cable ces fonctions : il groupe les DPE par commune
(code INSEE) et pour chaque commune construit un `DpeIndex` (via `build_dpe_index`)
interroge mutation par mutation avec `classify_match_indexed`.

**Dedup B** (`dedup_dpe`, appelee par `classify_match` ET `build_dpe_index`) : au sein
d'une `adresse_normalisee` exacte, les DPE partageant surface (0,1) + etiquette + GES
+ periode + type sont le meme logement diagnostique plusieurs fois -> on garde le plus
recent. Ne change jamais une reponse analytique (etiquette figee dans la cle).

Puis, pour chaque mutation, exactement un etat -- CONTEXT.md : jamais un choix force
au hasard -- parmi `trouve` / `resolu_consensus` / `non_trouve` / `ambigu` :

1. **Texte exact** -- unique DPE a la meme `adresse_normalisee` (non vide) -> trouve.
   Plusieurs (immeuble collectif) -> pool multi-candidats (voir 3-4).
2. **Distance geocodee** -- sinon, si la mutation est geocodee, DPE candidats a
   <= `seuil_distance_m`. Un seul -> trouve. Plusieurs -> pool multi-candidats.
3. **Filtre type + departage surface** -- sur un pool > 1 : filtre C retire les DPE
   dont `type_batiment` contredit `type_local` (narrow-only : jamais un non-appariement,
   `immeuble` toujours garde) ; puis un seul candidat a +/- `SURFACE_TOLERANCE_M2` de
   la surface de la mutation -> trouve.
4. **Consensus d'etiquette** -- sinon, si tous les candidats du sous-ensemble (within
   si >= 2, sinon le pool) portent la meme `etiquette_dpe` non nulle -> `resolu_consensus`
   (identite inconnue, `numero_dpe` NULL, etiquette certaine). Sinon -> `ambigu`.

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

# Jeu PAR DEFAUT des etats d'appariement porteurs d'une etiquette DPE certaine
# (spec §5, D3) : `trouve` (identite du DPE connue) et `resolu_consensus` (identite
# inconnue, etiquette certaine par consensus -- se lit "ambigu sauve", pas "trouve
# degrade"). Les deux entrent dans la vue Impact DPE.
#
# Definition unique ET seule valeur par defaut (#34). Les trois consommateurs
# parametres -- join_dvf_dpe.match_all (rapport d'appariement),
# impact_dpe.impact_dpe_rows / impact_dpe_slice (vue Impact DPE) et
# dashboard.data.matching_rate / impact_dpe_aggregate / impact_dpe_breakdown
# (resumes) -- prennent le jeu en parametre `statuses` et retombent ici. Un jeu
# different (p. ex. avec le 5e etat `resolu_jev`, #33) se passe explicitement,
# sans qu'aucune des trois surfaces puisse diverger : le test differentiel
# `tests/test_statuts_certains.py` verrouille la propriete.
#
# Exception assumee : `pipeline/07_report.py` (synthese PDF) reste epingle sur ce
# defaut, hors perimetre de #34 -- c'est #39 qui l'ouvrira en meme temps qu'il
# fera figurer la contribution de Jev dans le PDF. Tant que ce n'est pas fait, un
# 5e etat compterait dans le dashboard et le rapport d'appariement mais PAS dans
# le PDF.
IMPACT_DPE_STATUSES = ("trouve", "resolu_consensus")


def normalize_statuses(statuses: Iterable[str]) -> tuple[str, ...]:
    """Normalise un jeu de statuts en tuple, pour les consommateurs de
    `IMPACT_DPE_STATUSES`.

    Refuse une chaine nue : `Sequence[str]` l'accepte, mais `tuple("trouve")`
    l'eclaterait en caracteres et aucun `match_status` ne serait plus retenu --
    tranche vide, agregats vides, aucune erreur. On prefere l'echec bruyant.
    """
    if isinstance(statuses, str):
        raise TypeError(
            f"jeu de statuts attendu (tuple/liste/set), chaine nue recue : {statuses!r}. "
            f"Pour un seul statut, passer ({statuses!r},)."
        )
    return tuple(statuses)


class MatchResult(NamedTuple):
    """Resultat d'appariement d'une mutation (spec §6).

    - `status`   : "trouve" | "resolu_consensus" | "non_trouve" | "ambigu"
    - `numero_dpe`: identifiant du DPE apparie (None sauf si status == "trouve" --
      pour `resolu_consensus` l'identite reste inconnue)
    - `methode`  : passe ayant conclu -- "texte_exact", "distance",
      "texte_exact_surface", "distance_surface", "consensus_etiquette"
      (None si non trouve / ambigu)
    - `filtre_type_applique` : True si le filtre C `type_batiment` a retire >= 1
      candidat du pool pour cette mutation (spec §4 C)
    - `etiquette_dpe` / `etiquette_ges` / `type_batiment` / `periode_construction` :
      contexte bati, porte depuis le DPE apparie (`trouve`) ou depuis le consensus
      quand identique sur tout le sous-ensemble ; None sinon
    """

    status: str
    numero_dpe: str | None
    methode: str | None
    filtre_type_applique: bool = False
    etiquette_dpe: str | None = None
    etiquette_ges: str | None = None
    type_batiment: str | None = None
    periode_construction: str | None = None


# Resultat interne des passes : le `MatchResult` + le sous-ensemble de candidats
# sur lequel la passe 4 est restee indecise (vide des que le statut n'est pas
# `ambigu`). Les deux entrees publiques historiques jettent le pool ;
# `classify_with_pool` le rend. Un seul parcours produit les deux : aucune logique
# de selection n'est dupliquee, donc aucune derive possible entre le pool juge par
# Jev et l'ambiguite reellement mesuree (#35).
_Outcome = tuple[MatchResult, list[dict]]


def _context(dpe: dict) -> dict:
    """Contexte bati d'un DPE pour `MatchResult` (spec §6)."""
    return {
        "etiquette_dpe": dpe.get("etiquette_dpe"),
        "etiquette_ges": dpe.get("etiquette_ges"),
        "type_batiment": dpe.get("type_batiment"),
        "periode_construction": dpe.get("periode_construction"),
    }


def _norm(value) -> str:
    return (value or "").strip()


def _dedup_key(dpe: dict) -> tuple:
    """Signature analytique + bati d'un DPE (brique B, spec §4 / ADR 0003) : deux DPE
    de meme `adresse_normalisee` qui partagent cette cle sont le meme logement
    diagnostique plusieurs fois. La cle fige `etiquette_dpe` + `etiquette_ges`, donc
    fusionner ne change jamais une reponse analytique (`agg_dpe`)."""
    surface = dpe.get("surface_habitable_logement")
    return (
        round(surface, 1) if surface is not None else None,
        dpe.get("etiquette_dpe"),
        dpe.get("etiquette_ges"),
        dpe.get("periode_construction"),
        dpe.get("type_batiment"),
    )


def _sortable(value: float | None) -> tuple[bool, float]:
    """Rend une valeur numerique potentiellement absente comparable (None en tete)."""
    return (value is not None, value if value is not None else 0.0)


def _recency(dpe: dict) -> tuple:
    """Ordre de departage d'un groupe de dedup : date d'etablissement la plus recente,
    puis `numero_dpe` max. Si deux lignes partagent date + `numero_dpe` -- l'export
    ADEME peut livrer un meme DPE geocode differemment (#32) --, on departage encore
    sur lat / lon / surface : sans ce complement, `max` renvoie le premier a egalite,
    donc le survivant (et l'appariement) depend de l'ordre physique du parquet
    `dpe_clean`. Date absente -> trie en dernier (cas theorique, tous les DPE retenus
    etant post-reforme donc dates)."""
    return (
        dpe.get("date_etablissement_dpe") or "",
        dpe.get("numero_dpe") or "",
        _sortable(dpe.get("lat")),
        _sortable(dpe.get("lon")),
        _sortable(dpe.get("surface_habitable_logement")),
    )


def dedup_dpe(dpe_candidats: list[dict]) -> list[dict]:
    """Collapse les DPE redondants d'une commune (brique B, spec §4).

    Entree : DPE deja restreints a une commune. Au sein d'une `adresse_normalisee`
    exacte identique (non vide) et d'une meme `_dedup_key`, on garde un seul
    enregistrement -- le plus recent (`_recency`). Les DPE a adresse vide ne sont
    jamais groupes (pas de cle d'adresse fiable) et passent tels quels.

    Deterministe, pure. Appelee par `classify_match` et `build_dpe_index` pour que
    les deux chemins voient exactement la meme liste dedupliquee.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    kept: list[dict] = []
    for dpe in dpe_candidats:
        adresse = _norm(dpe.get("adresse_normalisee"))
        if not adresse:
            kept.append(dpe)
            continue
        groups[(adresse, _dedup_key(dpe))].append(dpe)
    for group in groups.values():
        kept.append(group[0] if len(group) == 1 else max(group, key=_recency))
    return kept


# Filtre C (spec §4) : type_local DVF -> type_batiment DPE tenu pour contradictoire.
# `immeuble` (DPE collectif) n'est jamais contradictoire -> toujours conserve.
_TYPE_CONTRADICTION = {"Appartement": "maison", "Maison": "appartement"}


def _type_filter(pool: list[dict], type_local: str | None) -> tuple[list[dict], bool]:
    """Filtre C : sur un pool > 1, retire les DPE dont `type_batiment` contredit
    `type_local`. narrow-only (D1) : si le filtre viderait le pool, on rend le pool
    d'origine -- C ne cree jamais un non-appariement. Retourne (pool, a_retire)."""
    contradiction = _TYPE_CONTRADICTION.get(type_local or "")
    if contradiction is None:
        return pool, False
    filtered = [d for d in pool if d.get("type_batiment") != contradiction]
    if not filtered or len(filtered) == len(pool):
        return pool, False
    return filtered, True


def _surface_within(mutation: dict, candidats: list[dict]) -> list[dict]:
    """Passe 3 : DPE candidats dont la surface est a +/- SURFACE_TOLERANCE_M2 de
    celle de la mutation. Liste vide si la surface de la mutation est absente."""
    surface_mutation = mutation.get("surface")
    if surface_mutation is None:
        return []
    return [
        d
        for d in candidats
        if d.get("surface_habitable_logement") is not None
        and abs(d["surface_habitable_logement"] - surface_mutation) <= SURFACE_TOLERANCE_M2
    ]


def _unanimous(subset: list[dict], field: str) -> str | None:
    """Valeur de `field` si elle est identique et non nulle sur tout le sous-ensemble,
    sinon None (contexte porte seulement quand certain -- spec §6)."""
    values = {d.get(field) for d in subset}
    return next(iter(values)) if len(values) == 1 and None not in values else None


def _consensus_pass(subset: list[dict], filtre_type: bool) -> _Outcome:
    """Passe 4 (spec §4 A2, D5) : si tous les candidats du sous-ensemble partagent
    la meme `etiquette_dpe` non nulle -> `resolu_consensus` (identite inconnue,
    etiquette certaine). GES / type / periode portes seulement s'ils sont eux aussi
    unanimes. Sinon -> `ambigu`, et le sous-ensemble juge remonte tel quel : c'est
    le pool que `classify_with_pool` expose a la brique de desambiguisation (#35)."""
    etiquette = _unanimous(subset, "etiquette_dpe")
    if etiquette is None:
        return MatchResult("ambigu", None, None, filtre_type_applique=filtre_type), list(subset)
    return MatchResult(
        "resolu_consensus",
        None,
        "consensus_etiquette",
        filtre_type_applique=filtre_type,
        etiquette_dpe=etiquette,
        etiquette_ges=_unanimous(subset, "etiquette_ges"),
        type_batiment=_unanimous(subset, "type_batiment"),
        periode_construction=_unanimous(subset, "periode_construction"),
    ), []


def _judged_subset(mutation: dict, candidats: list[dict]) -> list[dict]:
    """Sous-ensemble sur lequel la passe 3 puis la passe 4 statuent : la fenetre de
    surface si elle retient au moins un candidat, sinon le pool d'entree (spec §5 --
    quand la surface ne discrimine rien, la question porte sur tout le batiment).

    `candidats` porte toujours >= 2 elements (`_resolve_pool` traite le cas unique
    avant d'appeler), donc un sous-ensemble de taille 1 ne peut venir que de la
    fenetre de surface : c'est le departage de la passe 3.
    """
    within = _surface_within(mutation, candidats)
    return within if within else candidats


def _surface_tiebreak(
    mutation: dict, candidats: list[dict], methode: str, filtre_type: bool
) -> _Outcome:
    """Passe 3 puis passe 4 : un seul candidat dans la tolerance de surface -> trouve.
    Sinon, passe 4 consensus sur le sous-ensemble juge (`_judged_subset`)."""
    subset = _judged_subset(mutation, candidats)
    if len(subset) == 1:
        return MatchResult(
            "trouve",
            subset[0].get("numero_dpe"),
            f"{methode}_surface",
            filtre_type_applique=filtre_type,
            **_context(subset[0]),
        ), []
    return _consensus_pass(subset, filtre_type)


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


def _resolve_pool(mutation: dict, pool: list[dict], methode: str) -> _Outcome:
    """Pool multi-candidats (passe 1 texte exact >1, ou passe 2 distance >1) :
    filtre C `type_batiment` (narrow-only) -> passe 3 surface -> passe 4 consensus.

    ATTENTION : `_resolve_pool_backtest` (#36) reimplemente cette meme sequence pour
    exposer, en plus, le pool pre-surface d'un `trouve`. Toute passe ajoutee/modifiee
    ici (filtre, departage, consensus) doit etre repercutee la-bas, sous peine de
    faire juger au backtest une ambiguite differente de celle que l'algorithme
    rencontre reellement -- le test differentiel de `TestClassifyWithBacktestPool`
    (tests/lib/test_match_dvf_dpe.py) ne verrouille que le `MatchResult`, pas la
    structure du pool expose."""
    pool, filtre_type = _type_filter(pool, mutation.get("type_local"))
    if len(pool) == 1:
        d = pool[0]
        return MatchResult(
            "trouve", d.get("numero_dpe"), methode, filtre_type_applique=filtre_type, **_context(d)
        ), []
    return _surface_tiebreak(mutation, pool, methode, filtre_type)


def _resolve(mutation: dict, exact: list[dict], near: list[dict]) -> _Outcome:
    """Applique passes 1->2->3(->4) a partir des sous-ensembles deja calcules :
    `exact` = DPE a adresse_normalisee identique, `near` = DPE geocodes a <= seuil
    (liste vide si la mutation n'a pas de coordonnees : la passe 2 ne trouve rien)."""
    if len(exact) == 1:
        d = exact[0]
        return MatchResult("trouve", d.get("numero_dpe"), "texte_exact", **_context(d)), []
    if exact:
        return _resolve_pool(mutation, exact, "texte_exact")

    if len(near) == 1:
        d = near[0]
        return MatchResult("trouve", d.get("numero_dpe"), "distance", **_context(d)), []
    if near:
        return _resolve_pool(mutation, near, "distance")
    return MatchResult("non_trouve", None, None), []


def classify_match(
    mutation: dict, dpe_candidats: list[dict], seuil_distance_m: float
) -> MatchResult:
    """Apparie une mutation DVF a un DPE via l'algorithme en 3 passes (ADR 0003).

    Implementation de reference (criteres d'acceptation issue #11).

    `mutation` : dict avec `adresse_normalisee`, `lat`, `lon`, `surface`,
        `type_local`.
    `dpe_candidats` : DPE deja restreints a la commune de la mutation, chacun un
        dict avec `numero_dpe`, `adresse_normalisee`, `lat`, `lon`,
        `surface_habitable_logement`, `etiquette_dpe`, `etiquette_ges`,
        `type_batiment`, `periode_construction`, `date_etablissement_dpe`.
    `seuil_distance_m` : seuil de la passe 2 (calibre en T9, voir
        `pipeline.lib.match_distance.DISTANCE_THRESHOLD_M`) -- passe en parametre,
        jamais lu en dur ici.

    Les candidats sont dedupliques en entree (`dedup_dpe`, brique B) : les deux
    chemins de matching (cette reference et l'indexe) voient la meme liste.
    """
    if not dpe_candidats:
        return MatchResult("non_trouve", None, None)

    dpe_candidats = dedup_dpe(dpe_candidats)
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
    return _resolve(mutation, exact, near)[0]


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
    """Construit le `DpeIndex` des DPE d'une commune pour le seuil de distance donne.

    Les candidats sont dedupliques (`dedup_dpe`, brique B) avant indexation -- meme
    liste que celle vue par la reference `classify_match`."""
    dpe_candidats = dedup_dpe(dpe_candidats)
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
    return classify_with_pool(mutation, index)[0]


def _gather_candidates(mutation: dict, index: DpeIndex) -> tuple[list[dict], list[dict]]:
    """Candidats des passes 1 (texte exact) et 2 (distance <= seuil), via l'index de
    la commune -- factorise entre `classify_with_pool` et `classify_with_backtest_pool`
    pour que les deux voient strictement le meme pool d'entree."""
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

    return list(exact), near


def classify_with_pool(mutation: dict, index: DpeIndex) -> _Outcome:
    """`classify_match_indexed` + le pool de candidats reste indecis.

    Retourne `(MatchResult, pool)`. `pool` est vide sauf si le statut est `ambigu` ;
    il porte alors, dans l'ordre d'indexation, le sous-ensemble exact sur lequel la
    passe 4 a echoue a degager un consensus -- apres filtre C `type_batiment` et
    apres restriction a la fenetre de surface quand celle-ci retient >= 2 candidats.

    C'est l'entree de la brique de desambiguisation (#35 / spec #33) : Jev doit juger
    l'ambiguite que l'algorithme a reellement rencontree, pas un pool reconstitue a
    cote.
    """
    if index.size == 0:
        return MatchResult("non_trouve", None, None), []
    exact, near = _gather_candidates(mutation, index)
    return _resolve(mutation, exact, near)


def _resolve_pool_backtest(mutation: dict, pool: list[dict], methode: str) -> _Outcome:
    """Comme `_resolve_pool`, mais un `trouve` par departage de surface expose aussi
    le pool multi-candidats PRE-surface (#36) : c'est ce que Jev verrait si
    l'identite etait masquee. `ambigu` / `resolu_consensus` restent hors de portee
    de cette fonction (aucune identite certaine a masquer) -- pool vide.

    Sequence VOLONTAIREMENT dupliquee de `_resolve_pool` (voir sa note d'attention) :
    les deux doivent rester synchronisees a la main."""
    pool, filtre_type = _type_filter(pool, mutation.get("type_local"))
    if len(pool) == 1:
        d = pool[0]
        return MatchResult(
            "trouve", d.get("numero_dpe"), methode, filtre_type_applique=filtre_type, **_context(d)
        ), [d]
    subset = _judged_subset(mutation, pool)
    if len(subset) == 1:
        d = subset[0]
        result = MatchResult(
            "trouve",
            d.get("numero_dpe"),
            f"{methode}_surface",
            filtre_type_applique=filtre_type,
            **_context(d),
        )
        return result, pool
    return _consensus_pass(subset, filtre_type)[0], []


def classify_with_backtest_pool(mutation: dict, index: DpeIndex) -> _Outcome:
    """Verite terrain gratuite du backtest Jev (#36) : meme statut/identite que
    `classify_with_pool`, mais pour tout `trouve`, le pool rendu est l'ensemble des
    candidats en jeu au moment ou l'algorithme a tranche -- exactement ce que Jev
    jugerait si la reponse etait masquee :

      - `texte_exact` / `distance` singuliers -> pool a UN candidat (le seul jamais
        en jeu : pas de distractor, seul `SCORE_MIN` peut mordre -- cf. la note de
        calibration sur `decide`) ;
      - `*_surface` -> pool multi-candidats considere AVANT que la surface ne tranche
        (`SCORE_MIN` et `MARGE_MIN` mordent tous deux -- meme structure qu'`ambigu`).

    Vide pour `ambigu` / `resolu_consensus` : pas d'identite certaine a masquer,
    c'est `classify_with_pool` qui les couvre."""
    if index.size == 0:
        return MatchResult("non_trouve", None, None), []
    exact, near = _gather_candidates(mutation, index)

    if len(exact) == 1:
        d = exact[0]
        return MatchResult("trouve", d.get("numero_dpe"), "texte_exact", **_context(d)), [d]
    if exact:
        return _resolve_pool_backtest(mutation, exact, "texte_exact")

    if len(near) == 1:
        d = near[0]
        return MatchResult("trouve", d.get("numero_dpe"), "distance", **_context(d)), [d]
    if near:
        return _resolve_pool_backtest(mutation, near, "distance")
    return MatchResult("non_trouve", None, None), []
