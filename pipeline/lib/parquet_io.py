"""Lecture / ecriture Parquet partagee par les etapes du pipeline.

DuckDB ne sait pas scanner directement une liste de dict Python (seulement
pandas.DataFrame / pyarrow / relations DuckDB). Pour rester sur la stack
DuckDB + Parquet sans tirer pandas/pyarrow (CLAUDE.md), l'ecriture passe par un
JSONL temporaire relu via `read_json_auto` avec un schema explicite.

Ces deux fonctions etaient copiees quasi a l'identique dans 04_join.py,
04b_join_iris.py et 05_aggregate.py (#11-#13), puis 02b_geocode_ban.py et
03_clean_dpe.py les ont rejointes (#22) -- factorisees ici, testees par un
aller-retour, pour qu'un correctif du chemin d'ecriture ne se fasse qu'a un
seul endroit.

02_clean_dvf.py garde son propre chemin (table typee + executemany, colonne
DATE native) : voir la docstring de sa fonction write_output.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

import duckdb


def read_parquet_rows(path: str | Path, columns: Sequence[str]) -> list[dict]:
    """Lit `columns` de `path` en liste de dict (une par ligne), via DuckDB."""
    con = duckdb.connect()
    result = con.execute(f"SELECT {', '.join(columns)} FROM read_parquet(?)", [str(path)])
    names = [d[0] for d in result.description]
    return [dict(zip(names, row, strict=True)) for row in result.fetchall()]


def write_parquet_rows(
    rows: Iterable[dict],
    column_types: dict[str, str],
    path: str | Path,
    *,
    str_columns: Sequence[str] = (),
) -> None:
    """Ecrit `rows` en Parquet a `path`, colonnes et types donnes par `column_types`
    (`{"nom": "VARCHAR" | "DOUBLE" | "BIGINT" | ...}`, ordre = ordre des colonnes).

    `str_columns` : colonnes converties via `str()` avant serialisation JSONL
    (ex. un objet `date` DuckDB, non serialisable tel quel).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    str_cols = set(str_columns)

    with tempfile.TemporaryDirectory(prefix="parquet_io_") as tmp:
        tmp_path = Path(tmp) / "rows.jsonl"
        with tmp_path.open("w", encoding="utf-8") as f:
            for row in rows:
                record = {}
                for name in column_types:
                    value = row.get(name)
                    if value is not None and name in str_cols:
                        value = str(value)
                    record[name] = value
                f.write(json.dumps(record, ensure_ascii=False))
                f.write("\n")

        cols_literal = ", ".join(f"'{n}': '{t}'" for n, t in column_types.items())
        tmp_posix = str(tmp_path).replace("\\", "/")
        out_literal = str(path).replace("\\", "/").replace("'", "''")

        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT {", ".join(column_types)}
                FROM read_json_auto('{tmp_posix}', columns={{{cols_literal}}})
            ) TO '{out_literal}' (FORMAT PARQUET)
            """
        )
