"""Rattachement d'un point geocode a son IRIS par jointure spatiale (ADR 0004) --
logique pure, aucune I/O, aucun reseau.

`pipeline/04b_join_iris.py` telecharge les contours IRIS officiels IGN, les parse
via `iris_features_from_geojson`, construit un `IrisIndex` (`build_iris_index`),
puis appelle `assign_iris` pour chaque mutation DVF geocodee.

Dependance : `shapely` (geometrie point-in-polygon). Justifiee dans l'issue #12
et ADR 0004 -- DuckDB seul ne fait pas de point-in-polygon contre des polygones
GeoJSON arbitraires.
"""

from __future__ import annotations

from typing import Any

from shapely import STRtree
from shapely.geometry import Point, shape


def iris_features_from_geojson(geojson: dict) -> list[dict[str, Any]]:
    """Parse un FeatureCollection GeoJSON de contours IRIS en liste de dict
    `{"code_iris", "nom_iris", "nom_commune", "geometry"}` (geometry = objet
    shapely). L'ordre des features est conserve (il departage les points sur une
    frontiere commune -- voir `assign_iris`)."""
    features = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        features.append(
            {
                "code_iris": props.get("code_iris"),
                "nom_iris": props.get("nom_iris"),
                "nom_commune": props.get("nom_commune"),
                "geometry": shape(feature["geometry"]),
            }
        )
    return features


class IrisIndex:
    """Index spatial (R-tree) des contours IRIS, interroge par `assign_iris`.

    Conserve les features dans leur ordre d'origine : quand un point est couvert
    par plusieurs polygones (frontiere partagee), c'est le premier dans cet ordre
    qui est retenu -- resultat deterministe, jamais dependant de l'ordre de
    parcours du R-tree.
    """

    def __init__(self, features: list[dict[str, Any]]):
        self._features = list(features)
        self._geometries = [f["geometry"] for f in self._features]
        self._tree = STRtree(self._geometries) if self._geometries else None

    def __len__(self) -> int:
        return len(self._features)

    def covering(self, point: Point) -> dict[str, Any] | None:
        # Pour un point, "intersects" equivaut a "polygone couvre le point",
        # frontiere incluse -- et contrairement au predicat "covers" du STRtree
        # (bugue sur point/polygone dans shapely 2.1), il filtre correctement.
        if self._tree is None:
            return None
        matches = self._tree.query(point, predicate="intersects")
        if len(matches) == 0:
            return None
        feature = self._features[int(min(matches))]
        return {"code_iris": feature["code_iris"], "nom_iris": feature["nom_iris"]}


def build_iris_index(features: list[dict[str, Any]]) -> IrisIndex:
    """Construit l'`IrisIndex` a partir des features parsees (une fois, en amont)."""
    return IrisIndex(features)


def assign_iris(lat: float | None, lon: float | None, iris_index: IrisIndex) -> dict | None:
    """IRIS (`{"code_iris", "nom_iris"}`) contenant le point (lat, lon), ou None.

    None si le point n'a pas de coordonnees (echec de geocodage en amont) ou s'il
    ne tombe dans aucun IRIS du perimetre -- les deux cas sont comptes a part par
    le script appelant, jamais silencieusement confondus avec un rattachement.
    """
    if lat is None or lon is None:
        return None
    return iris_index.covering(Point(lon, lat))
