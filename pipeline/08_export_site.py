"""(#44) Exporte les donnees du site statique (Observable Framework, `site/`).

Lit UNIQUEMENT l'instantane versionne `data/dashboard/` (jamais
`data/processed/`) : un clone frais et la CI GitHub Pages produisent le meme
site. Ecrit `site/src/data/*.json` + `iris.geojson` (generes, non versionnes).

Toute la logique vit dans `dashboard/site_export.py` (pur, teste) et
`dashboard/data.py` : ce script ne fait que charger, appeler, ecrire.
Idempotent : JSON trie, floats arrondis, aucune date d'execution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import data  # noqa: E402
from dashboard import site_export as sx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "dashboard"
OUT = ROOT / "site" / "src" / "data"

_FLOAT_DECIMALS = {"moyenne": 1, "mediane": 1, "pct": 2}


def _round(obj):
    if isinstance(obj, dict):
        return {
            k: round(v, _FLOAT_DECIMALS.get(k, 4)) if isinstance(v, float) else _round(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def _write(name: str, payload) -> int:
    path = OUT / name
    text = json.dumps(_round(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return path.stat().st_size


def _slim_geojson(geojson: dict) -> dict:
    """Garde les proprietes lues par la carte et arrondit les coordonnees a
    1e-5 degre (~1 m, bien en deca de la precision des contours IRIS)."""

    def rnd(node):
        if node and isinstance(node[0], (int, float)):
            return [round(node[0], 5), round(node[1], 5)]
        return [rnd(n) for n in node]

    keep = ("code_iris", "nom_iris", "code_insee", "nom_commune")
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {k: f["properties"].get(k) for k in keep},
                "geometry": {
                    "type": f["geometry"]["type"],
                    "coordinates": rnd(f["geometry"]["coordinates"]),
                },
            }
            for f in geojson["features"]
        ],
    }


def main() -> None:
    sources = {
        "marche": SNAPSHOT / "agg_marche.parquet",
        "iris": SNAPSHOT / "agg_iris.parquet",
        "matched": SNAPSHOT / "dvf_dpe_matched.parquet",
        "geojson": SNAPSHOT / "iris_communes.geojson",
    }
    missing = [p for p in sources.values() if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERREUR : fichier introuvable : {p}", file=sys.stderr)
        print("  Lancer d'abord : python pipeline/06_publish_dashboard_data.py", file=sys.stderr)
        sys.exit(1)

    marche = data.load_agg_marche(sources["marche"])
    iris = data.load_agg_iris(sources["iris"])
    matched = data.load_matched(sources["matched"])
    counts = data.load_matching_counts(sources["matched"])
    geojson = data.load_iris_geojson(sources["geojson"])

    annees = sorted({r["annee"] for r in marche if r.get("annee")})
    choices = data.commune_choices()
    dvf_noms = [c["dvf_nom"] for c in choices]
    dates = sorted(r["date_mutation"] for r in matched if r.get("date_mutation"))

    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {
        "meta.json": _write(
            "meta.json",
            {
                "annees": annees,
                "communes": choices,
                "types": list(data.TYPES_BIEN),
                "groupes": list(data.DPE_GROUPS),
                "cutoff": sx.POST_REFORM_CUTOFF,
                "note_decalage": data.TEMPORAL_GAP_NOTE,
                "appariement": data.matching_rate(counts),
                "date_min": dates[0] if dates else None,
                "date_max": dates[-1] if dates else None,
            },
        ),
        "marche.json": _write(
            "marche.json",
            {"communes": marche, "global": sx.global_trend(matched, data.TYPES_BIEN)},
        ),
        "impact.json": _write(
            "impact.json",
            {
                "cube": sx.impact_cube(matched, dvf_noms, annees),
                "comptages": sx.impact_counts_by_year(matched, dvf_noms, annees),
                "echelle": sx.label_ladder(matched),
            },
        ),
        "communes.json": _write(
            "communes.json",
            {
                # Evolution sur toute la periode : une base a 5 ans tomberait sur 2020,
                # annee a faible volume dans le fichier source.
                "tableau": sx.commune_table(
                    marche, dvf_noms, latest=annees[-1], recul=int(annees[-1]) - int(annees[0])
                ),
                "appariement": sx.commune_matching(matched),
            },
        ),
        "iris.json": _write("iris.json", iris),
        "iris.geojson": _write("iris.geojson", _slim_geojson(geojson)),
    }

    rate = data.matching_rate(counts)
    print("=== Export du site statique (site/src/data/, #44) ===")
    print(f"  source : {SNAPSHOT} (instantane versionne)")
    print(f"  {len(matched)} lignes appariement, {len(marche)} lignes marche, {len(iris)} IRIS")
    print(
        "  appariement : " + " / ".join(f"{s['label']} {s['pct']:.1f} %" for s in rate["statuses"])
    )
    for name, size in sizes.items():
        print(f"  {name:<16} {size / 1024:>8.1f} Ko")


if __name__ == "__main__":
    main()
