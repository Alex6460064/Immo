"""Rattache chaque mutation DVF geocodee (data/processed/dvf_geocoded.parquet, T7)
a son IRIS par jointure spatiale point-in-polygon (ADR 0004), et ecrit
data/processed/dvf_iris.parquet.

Voir issue #12 (T11) pour les criteres d'acceptation. La logique point-in-polygon
est pure et testee sans I/O dans pipeline/lib/join_iris.py -- ce script ne fait
que le cablage : telechargement des contours, lecture parquet, ecriture, rapport.

--- Source des contours IRIS ---
API WFS officielle IGN (Geoplateforme, data.geopf.fr), couche
STATISTICALUNITS.IRIS:contours_iris -- la fiche "Contours IRIS" de data.gouv.fr
(citee par ADR 0004) pointe elle-meme vers ce service ; le fichier GeoJSON
national n'y est plus distribue en telechargement direct ("File too large").
La requete est filtree (CQL_FILTER code_insee IN ...) aux seules communes ciblees
(config/communes.py) -- ~75 IRIS, ~250 Ko, jamais la France entiere.

--- Dependance shapely ---
Ajoutee a pyproject.toml (issue #12) : DuckDB ne fait pas de point-in-polygon
contre des polygones GeoJSON arbitraires. `shapely` (+ `numpy` tire comme
dependance) est la lib de reference pour cette geometrie.

Idempotent a deux niveaux : le GeoJSON brut est mis en cache dans
data/raw/iris_communes.geojson (supprimer pour re-telecharger) ; le parquet de
sortie n'est pas recalcule s'il existe deja et n'est pas vide.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.communes import get_codes_insee  # noqa: E402
from pipeline.lib.join_iris import (  # noqa: E402
    assign_iris,
    build_iris_index,
    iris_features_from_geojson,
)
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DVF_PATH = ROOT / "data" / "processed" / "dvf_geocoded.parquet"
IRIS_GEOJSON_PATH = ROOT / "data" / "raw" / "iris_communes.geojson"
OUTPUT_PATH = ROOT / "data" / "processed" / "dvf_iris.parquet"

WFS_URL = "https://data.geopf.fr/wfs/ows"
WFS_LAYER = "STATISTICALUNITS.IRIS:contours_iris"
USER_AGENT = "dvf-dpe-pays-basque/0.1 (portfolio project; contact via GitHub Alex6460064/Immo)"
REQUEST_TIMEOUT_S = 60

_DVF_COLUMNS = [
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

_OUTPUT_COLUMNS = {
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
    "code_iris": "VARCHAR",
    "nom_iris": "VARCHAR",
}


def download_iris_geojson(codes_insee: list[str], dest: Path) -> dict:
    """Telecharge (ou relit depuis le cache) les contours IRIS des communes ciblees."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[04b_join_iris] Contours IRIS deja en cache : {dest}")
        return json.loads(dest.read_text(encoding="utf-8"))

    codes_list = ", ".join(f"'{c}'" for c in codes_insee)
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": WFS_LAYER,
        "OUTPUTFORMAT": "application/json",
        "SRSNAME": "urn:ogc:def:crs:EPSG::4326",
        "CQL_FILTER": f"code_insee IN ({codes_list})",
    }
    url = f"{WFS_URL}?{urllib.parse.urlencode(params)}"
    print(
        f"[04b_join_iris] Telechargement des contours IRIS (WFS IGN, {len(codes_insee)} communes)"
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        body = response.read()

    geojson = json.loads(body)
    if geojson.get("type") != "FeatureCollection" or not geojson.get("features"):
        print(
            "ERREUR : la reponse WFS n'est pas un FeatureCollection GeoJSON non vide "
            f"(type={geojson.get('type')!r}, features={len(geojson.get('features', []))}).",
            file=sys.stderr,
        )
        sys.exit(1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    print(f"[04b_join_iris] {len(geojson['features'])} IRIS ecrits dans {dest}")
    return geojson


def attach_iris(dvf_rows: list[dict], iris_index) -> tuple[list[dict], Counter]:
    """Ajoute `code_iris` / `nom_iris` a chaque mutation. Retourne (lignes, compteur).

    Compteur : "rattachee", "non_geocodee" (pas de lat/lon en amont),
    "hors_perimetre_iris" (geocodee mais dans aucun IRIS des communes ciblees).
    """
    out_rows: list[dict] = []
    counts: Counter = Counter()

    for row in dvf_rows:
        iris = assign_iris(row.get("lat"), row.get("lon"), iris_index)
        new_row = dict(row)
        if iris is not None:
            new_row["code_iris"] = iris["code_iris"]
            new_row["nom_iris"] = iris["nom_iris"]
            counts["rattachee"] += 1
        else:
            new_row["code_iris"] = None
            new_row["nom_iris"] = None
            if row.get("lat") is None or row.get("lon") is None:
                counts["non_geocodee"] += 1
            else:
                counts["hors_perimetre_iris"] += 1
        out_rows.append(new_row)

    return out_rows, counts


def main() -> None:
    if not DVF_PATH.exists():
        print(f"ERREUR : fichier introuvable : {DVF_PATH}", file=sys.stderr)
        print("  Lancer d'abord : python pipeline/02b_geocode_ban.py", file=sys.stderr)
        sys.exit(1)

    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        print(
            f"[04b_join_iris] Fichier deja present ({OUTPUT_PATH}) -- jointure IRIS sautee "
            "(idempotent). Supprimer le fichier pour forcer un re-run."
        )
        return

    codes_insee = get_codes_insee()
    geojson = download_iris_geojson(codes_insee, IRIS_GEOJSON_PATH)
    features = iris_features_from_geojson(geojson)
    iris_index = build_iris_index(features)
    communes_avec_iris = len({f["nom_commune"] for f in features})
    print(
        f"[04b_join_iris] {len(features)} IRIS charges sur {communes_avec_iris} communes "
        f"(certaines petites communes n'ont qu'un IRIS = leur territoire entier, ADR 0004)"
    )

    print(f"[04b_join_iris] Lecture de {DVF_PATH}")
    dvf_rows = read_parquet_rows(DVF_PATH, _DVF_COLUMNS)
    print(f"[04b_join_iris] {len(dvf_rows)} mutations DVF a rattacher")

    out_rows, counts = attach_iris(dvf_rows, iris_index)

    print(f"[04b_join_iris] Ecriture de {OUTPUT_PATH}")
    write_parquet_rows(out_rows, _OUTPUT_COLUMNS, OUTPUT_PATH, str_columns=["date_mutation"])

    total = len(out_rows)
    rattachee = counts.get("rattachee", 0)
    non_geocodee = counts.get("non_geocodee", 0)
    hors = counts.get("hors_perimetre_iris", 0)

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%" if total else "-"

    print("\n=== Rapport rattachement IRIS (T11 / #12, ADR 0004) ===")
    print(f"  Mutations en entree                        : {total}")
    print(f"    - rattachee a un IRIS                    : {rattachee:>6}  ({pct(rattachee)})")
    print(
        f"    - non rattachable (echec geocodage amont): {non_geocodee:>6}  ({pct(non_geocodee)})"
    )
    print(f"    - geocodee mais hors perimetre IRIS      : {hors:>6}  ({pct(hors)})")

    if rattachee == 0:
        print(
            "ATTENTION : 0 mutation rattachee -- verifier l'ordre des coordonnees "
            "(lon/lat) et le perimetre des contours telecharges.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
