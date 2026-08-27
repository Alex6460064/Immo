"""Tests for pipeline.lib.join_iris -- pure point-in-polygon logic (ADR 0004), no I/O.

Written before the implementation (TDD, per CLAUDE.md). Seam: `assign_iris`, called
by pipeline/04b_join_iris.py once the official IGN IRIS contours are loaded, to
attach each geocoded DVF mutation to its IRIS zone.
"""

from pipeline.lib.join_iris import assign_iris, build_iris_index, iris_features_from_geojson

# Two adjacent unit squares in (lon, lat) space: A spans lon 0..1, B spans lon 1..2,
# both lat 0..1. Small enough to reason about by hand.
_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"code_iris": "A1", "nom_iris": "Alpha", "nom_commune": "Acom"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"code_iris": "B1", "nom_iris": "Bravo", "nom_commune": "Bcom"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]],
            },
        },
    ],
}


def _index():
    return build_iris_index(iris_features_from_geojson(_GEOJSON))


class TestIrisFeaturesFromGeojson:
    def test_parses_identity_and_geometry_for_each_feature(self):
        features = iris_features_from_geojson(_GEOJSON)
        assert [f["code_iris"] for f in features] == ["A1", "B1"]
        assert features[0]["nom_iris"] == "Alpha"
        assert features[0]["nom_commune"] == "Acom"
        assert features[0]["geometry"].area == 1.0

    def test_handles_both_polygon_and_multipolygon(self):
        features = iris_features_from_geojson(_GEOJSON)
        assert features[0]["geometry"].geom_type == "Polygon"
        assert features[1]["geometry"].geom_type == "MultiPolygon"


class TestAssignIris:
    def test_point_inside_first_square(self):
        result = assign_iris(0.5, 0.5, _index())
        assert result["code_iris"] == "A1"
        assert result["nom_iris"] == "Alpha"

    def test_point_inside_second_square(self):
        assert assign_iris(0.5, 1.5, _index())["code_iris"] == "B1"

    def test_point_outside_every_polygon_is_none(self):
        assert assign_iris(5.0, 5.0, _index()) is None

    def test_missing_latitude_is_none(self):
        assert assign_iris(None, 0.5, _index()) is None

    def test_missing_longitude_is_none(self):
        assert assign_iris(0.5, None, _index()) is None

    def test_point_on_shared_boundary_is_assigned_deterministically(self):
        # (lat=0.5, lon=1.0) lies on the edge both squares share. A covering test
        # matches both; the index must return one, always the same one (first in
        # feature order) -- never crash, never depend on dict iteration nondeterminism.
        first = assign_iris(0.5, 1.0, _index())["code_iris"]
        assert first == "A1"
        assert assign_iris(0.5, 1.0, _index())["code_iris"] == first

    def test_point_on_outer_corner_is_still_assigned(self):
        assert assign_iris(0.0, 0.0, _index())["code_iris"] == "A1"

    def test_empty_index_is_none(self):
        assert assign_iris(0.5, 0.5, build_iris_index([])) is None
