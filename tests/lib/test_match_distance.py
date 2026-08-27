"""Tests for pipeline.lib.match_distance -- pure logic only, no DuckDB/network.

Written before pipeline/calibrate_distance.py (TDD, per CLAUDE.md). Seam: the two
pure functions used by the "distance geocodee" pass of the DVF x DPE join
(ADR 0003) and by the T9 threshold calibration.
"""

import math

import pytest

from pipeline.lib.match_distance import distance_distribution, haversine_m

# IUGG mean Earth radius used by the implementation (see module docstring).
_EARTH_RADIUS_M = 6371008.8


class TestHaversineM:
    def test_identical_points_is_zero(self):
        assert haversine_m(43.48, -1.56, 43.48, -1.56) == 0.0

    def test_one_degree_of_latitude_is_a_meridian_arc(self):
        # Along a meridian the great-circle distance reduces to arc length R*theta,
        # independent of the haversine expression itself.
        expected = _EARTH_RADIUS_M * math.radians(1)
        assert haversine_m(0.0, 0.0, 1.0, 0.0) == pytest.approx(expected, rel=1e-6)

    def test_one_degree_of_longitude_shrinks_with_latitude(self):
        # A parallel circle at latitude phi has radius R*cos(phi); one degree of
        # longitude there is that fraction of a degree at the equator.
        at_equator = haversine_m(0.0, 0.0, 0.0, 1.0)
        at_sixty = haversine_m(60.0, 0.0, 60.0, 1.0)
        assert at_sixty == pytest.approx(at_equator * math.cos(math.radians(60)), rel=1e-4)

    def test_symmetric(self):
        a = haversine_m(43.4933, -1.5527, 43.4839, -1.5619)
        b = haversine_m(43.4839, -1.5619, 43.4933, -1.5527)
        assert a == b

    def test_known_short_distance_pays_basque(self):
        # Biarritz: Rocher de la Vierge (43.4831, -1.5686) to the casino on the
        # Grande Plage (43.4823, -1.5583) -- ~840 m, checked against an external
        # map measure tool.
        d = haversine_m(43.4831, -1.5686, 43.4823, -1.5583)
        assert d == pytest.approx(840, abs=60)


class TestDistanceDistribution:
    def test_empty_input(self):
        result = distance_distribution([])
        assert result["count"] == 0
        for key in ("mean", "min", "max", "p50", "p75", "p90", "p95", "p99"):
            assert result[key] is None

    def test_single_value(self):
        result = distance_distribution([12.5])
        assert result["count"] == 1
        for key in ("mean", "min", "max", "p50", "p75", "p90", "p95", "p99"):
            assert result[key] == 12.5

    def test_one_to_hundred(self):
        # Percentiles by linear interpolation on rank (pos = (n-1)*q), computed
        # independently of the implementation.
        result = distance_distribution([float(x) for x in range(1, 101)])
        assert result["count"] == 100
        assert result["mean"] == pytest.approx(50.5)
        assert result["min"] == 1.0
        assert result["max"] == 100.0
        assert result["p50"] == pytest.approx(50.5)
        assert result["p90"] == pytest.approx(90.1)
        assert result["p95"] == pytest.approx(95.05)
        assert result["p99"] == pytest.approx(99.01)

    def test_unsorted_input(self):
        result = distance_distribution([40.0, 10.0, 30.0, 20.0])
        assert result["min"] == 10.0
        assert result["max"] == 40.0
        assert result["p50"] == pytest.approx(25.0)
