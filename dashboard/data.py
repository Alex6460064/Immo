"""Chargement + filtrage des donnees du dashboard (vues "Marche" #14 et
"Impact DPE" #15) -- seam teste sans I/O reelle (CLAUDE.md).

Les sources sont lues depuis `data/processed/` + `data/raw/` si le pipeline a
tourne localement (les 4 fichiers presents), sinon toutes depuis l'instantane
versionne `data/dashboard/` (issue #24, `_resolve_sources()` -- tout ou rien,
jamais un melange de millesimes). C'est ce qui permet `streamlit run` sur un
clone frais et le deploiement Cloud (#25).

Sources (produites par le pipeline) :
  - `agg_marche.parquet` (05_aggregate) : prix/m2 par commune / annee / type de
    bien -- vue "Marche", courbe de tendance.
  - `agg_iris.parquet` (05_aggregate)   : prix/m2 par IRIS / type -- carte
    choroplethe (cumul toutes annees, cf. ADR 0004).
  - `dvf_dpe_matched.parquet` (04_join) : une ligne par mutation, `match_status`
    + `etiquette_dpe`. Sert au taux d'appariement (les 4 etats, CONTEXT.md) et a
    la re-agregation live de la vue "Impact DPE".
  - `data/raw/iris_communes.geojson` (04b_join_iris) : contours IRIS pour la carte.

--- Choix : vue "Impact DPE" re-agregee a la volee ---
`agg_dpe.parquet` (#T12) n'est indexe que par (etiquette, type de bien) -- il ne
permet pas les filtres commune / periode demandes par #15. Cette vue re-agrege
donc depuis `dvf_dpe_matched.parquet` avec les MÊMES fonctions pures que
`pipeline/05_aggregate.py` : `mutation_price_points` (repli mutation + garde-fous,
#26) -> `impact_dpe_rows` -> `aggregate_by`. Sans filtre commune/periode, le
resultat est exactement `agg_dpe.parquet` (au regroupement d'etiquette pres).
Voir NOTES.md.

Pas d'import Streamlit ici : le cache (`@st.cache_data`) et l'UI vivent dans
`dashboard/app.py`.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

import duckdb

from config.communes import COMMUNES
from pipeline.lib.aggregate import aggregate_by, impact_dpe_rows
from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF
from pipeline.lib.match_dvf_dpe import IMPACT_DPE_STATUSES
from pipeline.lib.mutations import mutation_price_points
from pipeline.lib.parquet_io import read_parquet_rows
from pipeline.lib.publish_dashboard import DASHBOARD_MATCHED_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
# Instantane versionne : le pipeline n'a pas tourne sur un clone frais / le
# deploiement Cloud (issue #24). `pipeline/06_publish_dashboard_data.py` le produit.
SNAPSHOT = ROOT / "data" / "dashboard"


# Emplacement "live" de chaque source quand le pipeline a tourne localement.
_LIVE_SOURCES: dict[str, Path] = {
    "agg_marche.parquet": PROCESSED,
    "agg_iris.parquet": PROCESSED,
    "dvf_dpe_matched.parquet": PROCESSED,
    "iris_communes.geojson": RAW,
}


def _resolve_sources(live_sources: dict[str, Path], snapshot: Path) -> tuple[dict[str, Path], bool]:
    """Tout ou rien : si les 4 sources "live" sont toutes presentes, le dashboard
    les utilise ; sinon il sert les 4 depuis l'instantane versionne `snapshot`
    (#24). Jamais un melange -- une vue "Marche" fraiche a cote d'un taux
    d'appariement perime serait une supposition silencieuse sur les donnees
    (CLAUDE.md). Retourne `({nom: chemin}, using_snapshot)`."""
    using_snapshot = not all((root / name).exists() for name, root in live_sources.items())
    if using_snapshot:
        return {name: snapshot / name for name in live_sources}, True
    return {name: root / name for name, root in live_sources.items()}, False


_RESOLVED, USING_SNAPSHOT = _resolve_sources(_LIVE_SOURCES, SNAPSHOT)
AGG_MARCHE_PATH = _RESOLVED["agg_marche.parquet"]
AGG_IRIS_PATH = _RESOLVED["agg_iris.parquet"]
MATCHED_PATH = _RESOLVED["dvf_dpe_matched.parquet"]
IRIS_GEOJSON_PATH = _RESOLVED["iris_communes.geojson"]

# Types de bien exposes comme filtre de lecture (user story #35). `type_local`
# reste une dimension de groupement des agregats -- rien n'est exclu en amont.
TYPES_BIEN = ("Appartement", "Maison")

# 4 etats d'appariement (CONTEXT.md, #23), ordre canonique d'affichage.
MATCH_STATUS_LABELS = {
    "trouve": "trouvé",
    "resolu_consensus": "résolu par consensus",
    "non_trouve": "non trouvé",
    "ambigu": "ambigu",
}
MATCH_STATUSES = tuple(MATCH_STATUS_LABELS)

DPE_GROUPS = ("A-C", "D", "E", "F-G")
_DPE_GROUP_OF = {"A": "A-C", "B": "A-C", "C": "A-C", "D": "D", "E": "E", "F": "F-G", "G": "F-G"}

# Avertissement porte par la vue "Impact DPE" (user story #34) : le decalage
# temporel DVF (2016+) / DPE post-reforme (juillet 2021+) ne doit pas se lire
# comme une tendance de marche.
TEMPORAL_GAP_NOTE = (
    "Les mutations DVF remontent à 2016, mais le DPE post-réforme n'existe que "
    f"depuis juillet 2021. Cette vue est restreinte aux mutations postérieures au "
    f"{POST_REFORM_CUTOFF} : une étiquette rapprochée d'une vente plus ancienne "
    "décrit le bien, pas ce que l'acheteur avait sous les yeux. Le décalage "
    "résiduel (vente 2021-2022 / DPE établi en 2024) invite à lire les écarts "
    "entre étiquettes comme un ordre de grandeur, pas une mesure fine."
)

_MARCHE_COLUMNS = ["commune", "annee", "type_local", "n", "moyenne", "mediane"]
_IRIS_COLUMNS = ["code_iris", "nom_iris", "type_local", "n", "moyenne", "mediane"]
# Source unique : `pipeline.lib.publish_dashboard` (l'instantane #24 ne publie
# que ces colonnes -- la liste ne peut pas deriver entre les deux).
_MATCHED_COLUMNS = list(DASHBOARD_MATCHED_COLUMNS)


# --- helpers purs ---


def dpe_group(etiquette: str | None) -> str | None:
    """Regroupe une etiquette DPE (A-G) en `A-C` / `D` / `E` / `F-G` (#15).
    `None`, chaine vide ou valeur inconnue -> `None`."""
    if not etiquette:
        return None
    return _DPE_GROUP_OF.get(etiquette.strip().upper())


def dvf_commune_name(nom: str) -> str:
    """Nom de commune sous la forme utilisee par DVF dans `agg_marche` : sans
    accent, en capitales, apostrophe -> espace (`Saint-Pierre-d'Irube` ->
    `SAINT-PIERRE-D IRUBE`, `Guéthary` -> `GUETHARY`)."""
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return ascii_.upper().replace("'", " ")


def commune_choices() -> list[dict]:
    """Communes ciblees (`config/communes.py`) avec les cles dont le dashboard a
    besoin : `nom` (affichage), `code_insee` (filtre carte IRIS), `dvf_nom`
    (filtre `agg_marche`)."""
    return [
        {"nom": c["nom"], "code_insee": c["code_insee"], "dvf_nom": dvf_commune_name(c["nom"])}
        for c in COMMUNES
    ]


def commune_from_code_iris(code_iris: str | None) -> str | None:
    """Code INSEE de la commune = 5 premiers caracteres du code IRIS."""
    if not code_iris:
        return None
    return code_iris[:5]


def matching_rate(counts: Mapping[str, int]) -> dict:
    """Taux d'appariement DVF x DPE a partir des effectifs par `match_status`
    (CONTEXT.md : les 4 etats affiches separement, jamais masques).

    Retourne `{total, statuses: [{status, label, n, pct}], etiquette_certaine:
    {n, pct}}` -- `etiquette_certaine` = `trouve` + `resolu_consensus`.
    """
    total = sum(int(counts.get(s, 0)) for s in MATCH_STATUSES)

    def pct(n: int) -> float:
        return (n / total * 100) if total else 0.0

    statuses = [
        {
            "status": s,
            "label": MATCH_STATUS_LABELS[s],
            "n": int(counts.get(s, 0)),
            "pct": pct(int(counts.get(s, 0))),
        }
        for s in MATCH_STATUSES
    ]
    certaine = sum(int(counts.get(s, 0)) for s in IMPACT_DPE_STATUSES)
    return {
        "total": total,
        "statuses": statuses,
        "etiquette_certaine": {"n": certaine, "pct": pct(certaine)},
    }


def _in_range(value: str | None, lo: str | None, hi: str | None) -> bool:
    if value is None:
        return lo is None and hi is None
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def filter_marche(
    rows: Sequence[dict],
    *,
    commune: str | None = None,
    type_local: str | None = None,
    annee_min: str | None = None,
    annee_max: str | None = None,
) -> list[dict]:
    """Filtre les lignes de `agg_marche` (cles : commune / annee / type_local).
    Un critere `None` n'exclut rien."""
    return [
        r
        for r in rows
        if (commune is None or r.get("commune") == commune)
        and (type_local is None or r.get("type_local") == type_local)
        and _in_range(r.get("annee"), annee_min, annee_max)
    ]


def market_trend(
    rows: Sequence[dict],
    *,
    commune: str | None = None,
    type_local: str | None = None,
    annee_min: str | None = None,
    annee_max: str | None = None,
) -> list[dict]:
    """Lignes de `agg_marche` filtrees puis triees par annee -- serie de la
    courbe de tendance prix/m2 de la vue "Marche"."""
    out = filter_marche(
        rows,
        commune=commune,
        type_local=type_local,
        annee_min=annee_min,
        annee_max=annee_max,
    )
    return sorted(out, key=lambda r: r.get("annee") or "")


def market_trend_global(
    matched_rows: Sequence[dict],
    *,
    type_local: str | None = None,
    annee_min: str | None = None,
    annee_max: str | None = None,
) -> list[dict]:
    """Courbe de reference « toutes communes confondues » de la vue « Marche » :
    prix/m2 `moyenne` ET `mediane` par annee, re-agrege depuis les lignes brutes
    d'appariement (`dvf_dpe_matched`, toutes les mutations quel que soit
    `match_status`).

    MÊME chaine pure que `pipeline/05_aggregate.py` (`mutation_price_points` ->
    `aggregate_by`), groupee par annee seule : une moyenne / mediane d'ensemble,
    pas une moyenne de moyennes par commune (biaisee par les petites communes).
    L'UI choisit la stat affichee via le toggle de la sidebar. Trie par annee.
    """
    points, _ = mutation_price_points(list(matched_rows))
    kept = [
        p
        for p in points
        if (type_local is None or p.get("type_local") == type_local)
        and _in_range(p.get("annee"), annee_min, annee_max)
    ]
    return sorted(aggregate_by(kept, ["annee"]), key=lambda r: r.get("annee") or "")


def filter_iris(
    rows: Sequence[dict],
    *,
    code_commune: str | None = None,
    type_local: str | None = None,
) -> list[dict]:
    """Filtre les lignes de `agg_iris`. `code_commune` compare le prefixe INSEE
    du `code_iris` -- une commune a IRIS unique (code `...0000`) passe comme les
    autres (ADR 0004, critere d'acceptation #14)."""
    return [
        r
        for r in rows
        if (code_commune is None or commune_from_code_iris(r.get("code_iris")) == code_commune)
        and (type_local is None or r.get("type_local") == type_local)
    ]


def iris_map_values(
    rows: Sequence[dict],
    *,
    type_local: str,
    stat: str = "mediane",
    code_commune: str | None = None,
) -> list[dict]:
    """Une ligne `agg_iris` par IRIS pour la carte choroplethe : prix/m2 du type de
    bien selectionne, dans la statistique choisie par l'UI (`stat` vaut
    `"moyenne"` ou `"mediane"`, pilote par le toggle de la sidebar de la vue
    « Marche »).

    Le prix/m2 est deja calcule par mutation et borne [200, 30 000] en amont (#26,
    ADR 0006) : la moyenne d'IRIS n'est plus exposee a des valeurs aberrantes. La
    mediane reste le defaut du projet (NOTES.md) pour sa robustesse a la queue
    haute des prix. La vue « Marche » impose toujours un `type_local`, donc un
    IRIS = une ligne. Trie par `code_iris` ; cle de valeur : `valeur`.
    """
    kept = filter_iris(rows, code_commune=code_commune, type_local=type_local)
    return sorted(
        (
            {
                "code_iris": r["code_iris"],
                "nom_iris": r.get("nom_iris"),
                "valeur": r[stat],
                "n": int(r.get("n") or 0),
            }
            for r in kept
            if r.get("code_iris") is not None and r.get(stat) is not None
        ),
        key=lambda r: r["code_iris"],
    )


def color_range(values: Sequence[float]) -> tuple[float, float] | None:
    """Bornes `(zmin, zmax)` = min / max des medianes IRIS pour l'echelle de
    couleur de la carte. `None` si aucune valeur.

    Plus de plafonnement au centile : depuis le repli mutation (#26, ADR 0006) le
    prix/m2 est calcule par mutation (prix / somme des surfaces habitation) et
    borne a [200, 30 000] EUR/m2 en amont -- il n'y a plus d'IRIS a mediane
    aberrante a cacher, l'echelle peut refleter les vraies valeurs."""
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return None
    return (vs[0], vs[-1])


def filter_matched(
    rows: Sequence[dict],
    *,
    commune: str | None = None,
    type_local: str | None = None,
    date_min: str | None = None,
    date_max: str | None = None,
    groupe: str | None = None,
) -> list[dict]:
    """Filtre les lignes brutes de `dvf_dpe_matched` (`date_mutation` = ISO
    complet). `groupe` compare le regroupement d'etiquette (`dpe_group`, un des
    `DPE_GROUPS`). Un critere `None` n'exclut rien."""
    return [
        r
        for r in rows
        if (commune is None or r.get("commune") == commune)
        and (type_local is None or r.get("type_local") == type_local)
        and (groupe is None or dpe_group(r.get("etiquette_dpe")) == groupe)
        and _in_range(r.get("date_mutation"), date_min, date_max)
    ]


def _impact_dpe_kept(
    matched_rows: Sequence[dict],
    *,
    commune: str | None,
    type_local: str | None,
    date_min: str | None,
    date_max: str | None,
    groupe: str | None,
    cutoff: str,
) -> list[dict]:
    """Points prix/m2 retenus pour la vue "Impact DPE" : repli mutation (#26,
    un point par (mutation, etiquette)) puis filtres de #15 puis `impact_dpe_rows`
    (etiquette certaine + mutation >= `cutoff`). Base commune a
    `impact_dpe_aggregate` et `impact_dpe_breakdown`.

    Le repli precede les filtres : tous les points d'une mutation partagent
    commune / type_local / date (mono-type habitation, ADR 0006), donc filtrer
    les points revient a filtrer les lignes -- mais le prix/m2 est deja calcule
    sur la surface habitation de TOUTE la mutation, jamais sur le seul lot filtre.
    """
    points, _ = mutation_price_points(
        list(matched_rows), extra_keys=("etiquette_dpe", "match_status")
    )
    filtered = filter_matched(
        points,
        commune=commune,
        type_local=type_local,
        date_min=date_min,
        date_max=date_max,
        groupe=groupe,
    )
    return impact_dpe_rows(filtered, cutoff)


def impact_dpe_aggregate(
    matched_rows: Sequence[dict],
    *,
    commune: str | None = None,
    type_local: str | None = None,
    date_min: str | None = None,
    date_max: str | None = None,
    groupe: str | None = None,
    cutoff: str = POST_REFORM_CUTOFF,
) -> list[dict]:
    """Agregat prix/m2 par (regroupement d'etiquette DPE, type de bien) de la vue
    "Impact DPE" -- prix/m2 median/moyen par `DPE_GROUPS` (`A-C` / `D` / `E` /
    `F-G`, granularite demandee par #15), calcule a la volee depuis les lignes
    d'appariement.

    MÊME chaine pure que `pipeline/05_aggregate.py` (`mutation_price_points` ->
    `impact_dpe_rows` -> `aggregate_by`), a la difference de la cle de groupe :
    `agg_dpe.parquet` groupe par etiquette exacte (A..G), cette vue par
    regroupement -- pour un `n` par barre suffisant sur le petit echantillon
    apparie. `n` compte des points (mutation x etiquette), pas des lots (#26).
    Sans filtre commune/periode, les memes mutations sont agregees que dans
    `agg_dpe.parquet`. Voir NOTES.md.
    """
    kept = _impact_dpe_kept(
        matched_rows,
        commune=commune,
        type_local=type_local,
        date_min=date_min,
        date_max=date_max,
        groupe=groupe,
        cutoff=cutoff,
    )
    enriched = [{**r, "groupe": dpe_group(r.get("etiquette_dpe"))} for r in kept]
    return aggregate_by(enriched, ["groupe", "type_local"])


def impact_dpe_breakdown(
    matched_rows: Sequence[dict],
    *,
    commune: str | None = None,
    type_local: str | None = None,
    date_min: str | None = None,
    date_max: str | None = None,
    groupe: str | None = None,
    cutoff: str = POST_REFORM_CUTOFF,
) -> dict:
    """Composition du sous-ensemble alimentant la vue "Impact DPE" pour une
    selection donnee : `{retenues, resolu_consensus, pre_reforme_exclus}`.

    Effectifs en points (mutation x etiquette) depuis le repli #26, plus en lots.
    `retenues` = points a etiquette certaine, posterieurs au `cutoff`, avec un
    prix/m2 exploitable (les points sans prix/m2 valide n'existent pas -- une
    mutation ecartee par les garde-fous ne produit aucun point).
    `pre_reforme_exclus` = points a etiquette certaine mais anterieurs au `cutoff`
    (comptes, pas supprimes -- cf. `TEMPORAL_GAP_NOTE`). Sert la mention
    « dont N resolus par consensus » demandee par #15.
    """
    points, _ = mutation_price_points(
        list(matched_rows), extra_keys=("etiquette_dpe", "match_status")
    )
    kept_pre = filter_matched(
        points,
        commune=commune,
        type_local=type_local,
        date_min=date_min,
        date_max=date_max,
        groupe=groupe,
    )
    usable = impact_dpe_rows(kept_pre, cutoff)
    return {
        "retenues": len(usable),
        "resolu_consensus": sum(1 for r in usable if r.get("match_status") == "resolu_consensus"),
        "pre_reforme_exclus": sum(
            1
            for r in kept_pre
            if r.get("match_status") in IMPACT_DPE_STATUSES
            and (r.get("date_mutation") or "") < cutoff
        ),
    }


# --- chargement I/O ---


def load_agg_marche(path: str | Path = AGG_MARCHE_PATH) -> list[dict]:
    return read_parquet_rows(path, _MARCHE_COLUMNS)


def load_agg_iris(path: str | Path = AGG_IRIS_PATH) -> list[dict]:
    return read_parquet_rows(path, _IRIS_COLUMNS)


def load_matched(path: str | Path = MATCHED_PATH) -> list[dict]:
    return read_parquet_rows(path, _MATCHED_COLUMNS)


def load_matching_counts(path: str | Path = MATCHED_PATH) -> dict[str, int]:
    """Effectifs par `match_status` sur l'ensemble du perimetre (via DuckDB, pas
    de chargement des lignes en memoire)."""
    con = duckdb.connect()
    rows = con.execute(
        "SELECT match_status, COUNT(*) FROM read_parquet(?) GROUP BY match_status",
        [str(path)],
    ).fetchall()
    return {status: int(n) for status, n in rows}


def load_iris_geojson(path: str | Path = IRIS_GEOJSON_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _iter_coords(geometry: dict):
    """Positions [lon, lat] d'une geometrie GeoJSON (Polygon / MultiPolygon,
    profondeur d'imbrication variable)."""
    stack = [geometry.get("coordinates", [])]
    while stack:
        node = stack.pop()
        if node and isinstance(node[0], (int, float)):
            yield node
        else:
            stack.extend(node)


def geojson_center(geojson: dict, codes: set[str] | None = None) -> dict | None:
    """Centre (`{"lat", "lon"}`) de la boite englobante des features dont
    `properties.code_iris` est dans `codes` (toutes si `codes` est None) -- pour
    recadrer la carte sur la commune selectionnee. `None` si aucune feature."""
    lons: list[float] = []
    lats: list[float] = []
    for feature in geojson.get("features", []):
        if codes is not None and feature.get("properties", {}).get("code_iris") not in codes:
            continue
        for lon, lat in _iter_coords(feature.get("geometry", {})):
            lons.append(lon)
            lats.append(lat)
    if not lons:
        return None
    return {"lat": (min(lats) + max(lats)) / 2, "lon": (min(lons) + max(lons)) / 2}
