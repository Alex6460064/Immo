"""Tests de `pipeline.lib.publish_dashboard` -- construction de l'instantane
`data/dashboard/` lu par le dashboard sur un clone frais (issue #24).

Ecrits avant l'implementation du cablage (`pipeline/06_publish_dashboard_data.py`),
sur de petits fichiers (pas d'I/O sur `data/`).
"""

from __future__ import annotations

import json

from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows
from pipeline.lib.publish_dashboard import (
    COPIED_AGGREGATES,
    DASHBOARD_MATCHED_COLUMNS,
    IRIS_GEOJSON_NAME,
    MATCHED_NAME,
    publish_snapshot,
)

_AGG_TYPES = {
    "commune": "VARCHAR",
    "annee": "VARCHAR",
    "type_local": "VARCHAR",
    "n": "BIGINT",
    "moyenne": "DOUBLE",
    "mediane": "DOUBLE",
}


def _build_processed(processed_dir, raw_dir):
    processed_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    for name in COPIED_AGGREGATES:
        write_parquet_rows(
            [
                {
                    "commune": "ANGLET",
                    "annee": "2022",
                    "type_local": "Maison",
                    "n": 3,
                    "moyenne": 5000.0,
                    "mediane": 4800.0,
                }
            ],
            _AGG_TYPES,
            processed_dir / name,
        )

    # matched avec des colonnes EN PLUS de celles lues par le dashboard
    write_parquet_rows(
        [
            {
                "commune": "ANGLET",
                "date_mutation": "2022-01-01",
                "type_local": "Maison",
                "surface": 60.0,
                "prix": 300000.0,
                "match_status": "trouve",
                "etiquette_dpe": "D",
                "adresse_brute": "10 rue X",
                "numero_dpe": "2299E0001",
            },
            {
                "commune": "BIARRITZ",
                "date_mutation": "2023-05-01",
                "type_local": "Appartement",
                "surface": 40.0,
                "prix": 250000.0,
                "match_status": "ambigu",
                "etiquette_dpe": None,
                "adresse_brute": "2 av Y",
                "numero_dpe": None,
            },
        ],
        {
            "commune": "VARCHAR",
            "date_mutation": "VARCHAR",
            "type_local": "VARCHAR",
            "surface": "DOUBLE",
            "prix": "DOUBLE",
            "match_status": "VARCHAR",
            "etiquette_dpe": "VARCHAR",
            "adresse_brute": "VARCHAR",
            "numero_dpe": "VARCHAR",
        },
        processed_dir / MATCHED_NAME,
    )

    (raw_dir / IRIS_GEOJSON_NAME).write_text(
        json.dumps({"type": "FeatureCollection", "features": [{"id": 1}]}), encoding="utf-8"
    )


def test_writes_the_four_snapshot_files(tmp_path):
    processed, raw, out = tmp_path / "processed", tmp_path / "raw", tmp_path / "dashboard"
    _build_processed(processed, raw)

    publish_snapshot(processed, raw, out)

    written = {p.name for p in out.iterdir()}
    assert written == {*COPIED_AGGREGATES, MATCHED_NAME, IRIS_GEOJSON_NAME}


def test_matched_keeps_only_dashboard_columns(tmp_path):
    processed, raw, out = tmp_path / "processed", tmp_path / "raw", tmp_path / "dashboard"
    _build_processed(processed, raw)

    publish_snapshot(processed, raw, out)

    rows = read_parquet_rows(out / MATCHED_NAME, list(DASHBOARD_MATCHED_COLUMNS))
    assert len(rows) == 2
    import duckdb

    cols = [
        c[0]
        for c in duckdb.connect()
        .execute(f"DESCRIBE SELECT * FROM read_parquet('{(out / MATCHED_NAME).as_posix()}')")
        .fetchall()
    ]
    assert set(cols) == set(DASHBOARD_MATCHED_COLUMNS)


def test_aggregates_and_geojson_are_byte_copies(tmp_path):
    processed, raw, out = tmp_path / "processed", tmp_path / "raw", tmp_path / "dashboard"
    _build_processed(processed, raw)

    publish_snapshot(processed, raw, out)

    for name in (*COPIED_AGGREGATES, IRIS_GEOJSON_NAME):
        src = (processed / name) if name in COPIED_AGGREGATES else (raw / name)
        assert (out / name).read_bytes() == src.read_bytes()


def test_idempotent_second_run_is_identical(tmp_path):
    processed, raw, out = tmp_path / "processed", tmp_path / "raw", tmp_path / "dashboard"
    _build_processed(processed, raw)

    publish_snapshot(processed, raw, out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    publish_snapshot(processed, raw, out)
    second = {p.name: p.read_bytes() for p in out.iterdir()}

    assert first == second


def test_summary_reports_rows_and_bytes(tmp_path):
    processed, raw, out = tmp_path / "processed", tmp_path / "raw", tmp_path / "dashboard"
    _build_processed(processed, raw)

    summary = publish_snapshot(processed, raw, out)

    by_name = {item["name"]: item for item in summary}
    assert by_name[MATCHED_NAME]["rows"] == 2
    assert by_name["agg_marche.parquet"]["rows"] == 1
    assert by_name[IRIS_GEOJSON_NAME]["rows"] is None
    assert all(item["bytes"] > 0 for item in summary)
