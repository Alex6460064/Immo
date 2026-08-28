"""Construit l'instantane de donnees du dashboard (`data/dashboard/`, issue #24)
depuis les sorties du pipeline (`data/processed/` + `data/raw/iris_communes.geojson`).

Pourquoi un instantane versionne : le deploiement Streamlit Community Cloud (#25)
deploie le repo sans executer le pipeline -- le dashboard doit pouvoir lire ses
donnees sur un clone frais. `pipeline/06_publish_dashboard_data.py` est le seul
producteur de ce dossier ; il n'est jamais edite a la main.

Idempotent : deux executions successives sur les memes entrees (et meme version
DuckDB) produisent les memes fichiers -- copie octet a octet pour les agregats et
le geojson, projection DuckDB a colonnes et ordre de lignes fixes (`ORDER BY ALL`)
pour le parquet matched. Un bump de version DuckDB change le pied de page Parquet
(chaine `created_by`) sur donnees identiques : sans consequence, on recommitte
l'instantane regenere.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb

# Colonnes de `dvf_dpe_matched.parquet` reellement lues par le dashboard.
# `dashboard/data.py` importe cette liste -- source unique. Elle vit ici (feuille
# de `pipeline/lib`, sans dependance vers `dashboard/`) plutot que l'inverse :
# le pipeline ne doit jamais dependre du dashboard. L'instantane ne publie que
# ces colonnes : le fichier reste < 1 Mo.
# code_insee / no_disposition / nature_mutation : cle de mutation + regle A du
# repli prix/m2 au niveau mutation (issue #26), pour que la re-agregation live de
# la vue Impact DPE donne le meme resultat que `agg_dpe.parquet`.
DASHBOARD_MATCHED_COLUMNS: tuple[str, ...] = (
    "commune",
    "code_insee",
    "no_disposition",
    "nature_mutation",
    "date_mutation",
    "type_local",
    "surface",
    "prix",
    "match_status",
    "etiquette_dpe",
)

MATCHED_NAME = "dvf_dpe_matched.parquet"
IRIS_GEOJSON_NAME = "iris_communes.geojson"
# Agregats copies tels quels (deja < 15 Ko, cf. issue #24).
COPIED_AGGREGATES: tuple[str, ...] = ("agg_marche.parquet", "agg_iris.parquet")


def _sql_literal(path: Path) -> str:
    """Chemin en litteral SQL DuckDB : separateurs POSIX + apostrophe echappee
    (un repo cloné sous `.../O'Brien/...` casserait sinon la requete)."""
    return str(path).replace("\\", "/").replace("'", "''")


def _parquet_rowcount(path: Path) -> int:
    return (
        duckdb.connect()
        .execute(f"SELECT COUNT(*) FROM read_parquet('{_sql_literal(path)}')")
        .fetchone()[0]
    )


def _project_matched(src: Path, dest: Path) -> None:
    """Ecrit `dest` = `src` restreint a `DASHBOARD_MATCHED_COLUMNS`. `ORDER BY ALL`
    fige l'ordre des lignes pour que deux executions donnent le meme fichier."""
    cols = ", ".join(DASHBOARD_MATCHED_COLUMNS)
    duckdb.connect().execute(
        f"COPY (SELECT {cols} FROM read_parquet('{_sql_literal(src)}') ORDER BY ALL) "
        f"TO '{_sql_literal(dest)}' (FORMAT PARQUET)"
    )


def publish_snapshot(processed_dir: Path, raw_dir: Path, out_dir: Path) -> list[dict]:
    """(Re)genere `out_dir` depuis `processed_dir` + `raw_dir`. Retourne un resume
    par fichier : `{"name", "rows", "bytes"}` (`rows` vaut `None` pour le geojson).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []

    for name in COPIED_AGGREGATES:
        dest = out_dir / name
        shutil.copyfile(processed_dir / name, dest)
        summary.append(
            {"name": name, "rows": _parquet_rowcount(dest), "bytes": dest.stat().st_size}
        )

    matched_dest = out_dir / MATCHED_NAME
    _project_matched(processed_dir / MATCHED_NAME, matched_dest)
    summary.append(
        {
            "name": MATCHED_NAME,
            "rows": _parquet_rowcount(matched_dest),
            "bytes": matched_dest.stat().st_size,
        }
    )

    geojson_dest = out_dir / IRIS_GEOJSON_NAME
    shutil.copyfile(raw_dir / IRIS_GEOJSON_NAME, geojson_dest)
    summary.append({"name": IRIS_GEOJSON_NAME, "rows": None, "bytes": geojson_dest.stat().st_size})

    return summary
