"""Tests for pipeline.lib.parquet_io -- the shared DuckDB Parquet read/write path
used by 04_join, 04b_join_iris and 05_aggregate. Round-trip through a real file.
"""

from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows


def test_round_trip_preserves_values_and_column_order(tmp_path):
    rows = [
        {"code": "64122", "prix": 300000.0, "n": 3},
        {"code": "64024", "prix": 250000.5, "n": 1},
    ]
    path = tmp_path / "out.parquet"
    write_parquet_rows(rows, {"code": "VARCHAR", "prix": "DOUBLE", "n": "BIGINT"}, path)

    back = read_parquet_rows(path, ["code", "prix", "n"])
    assert back == rows


def test_none_values_survive_as_null(tmp_path):
    rows = [{"a": "x", "b": None}, {"a": None, "b": 2.0}]
    path = tmp_path / "out.parquet"
    write_parquet_rows(rows, {"a": "VARCHAR", "b": "DOUBLE"}, path)
    assert read_parquet_rows(path, ["a", "b"]) == rows


def test_missing_key_is_written_as_null(tmp_path):
    path = tmp_path / "out.parquet"
    write_parquet_rows([{"a": "x"}], {"a": "VARCHAR", "b": "DOUBLE"}, path)
    assert read_parquet_rows(path, ["a", "b"]) == [{"a": "x", "b": None}]


def test_str_columns_are_stringified_before_write(tmp_path):
    import datetime

    rows = [{"jour": datetime.date(2021, 7, 1), "v": 1.0}]
    path = tmp_path / "out.parquet"
    write_parquet_rows(rows, {"jour": "VARCHAR", "v": "DOUBLE"}, path, str_columns=["jour"])
    assert read_parquet_rows(path, ["jour"]) == [{"jour": "2021-07-01"}]


def test_only_declared_columns_are_written(tmp_path):
    path = tmp_path / "out.parquet"
    write_parquet_rows([{"keep": "y", "drop": "n"}], {"keep": "VARCHAR"}, path)
    assert read_parquet_rows(path, ["keep"]) == [{"keep": "y"}]
