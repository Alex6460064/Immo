"""Tests pour pipeline.lib.reporting -- helper de formatage de pourcentage
partage par les rapports de 04_join et 04b_join_iris (#22)."""

from pipeline.lib.reporting import format_pct


def test_basic_ratio():
    assert format_pct(1, 4) == "25.0%"


def test_rounds_to_one_decimal():
    assert format_pct(1, 3) == "33.3%"


def test_zero_total_returns_dash():
    assert format_pct(0, 0) == "-"


def test_zero_numerator():
    assert format_pct(0, 10) == "0.0%"


def test_full():
    assert format_pct(7, 7) == "100.0%"
