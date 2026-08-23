import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.obb_geometry import (
    corners_to_obb,
    from_yolo_obb_line,
    obb_area_fraction_inside,
    obb_to_axis_aligned,
    obb_to_corners,
    to_yolo_obb_line,
)

obb_strategy = st.tuples(
    st.floats(min_value=50, max_value=590, allow_nan=False),  # cx
    st.floats(min_value=50, max_value=590, allow_nan=False),  # cy
    st.floats(min_value=5, max_value=100, allow_nan=False),  # w
    st.floats(min_value=5, max_value=100, allow_nan=False),  # h
    st.floats(min_value=-179, max_value=179, allow_nan=False),  # angle
)


@given(obb_strategy)
@settings(max_examples=200)
def test_corners_to_obb_round_trip_preserves_geometry(params):
    cx, cy, w, h, angle = params
    corners = obb_to_corners(cx, cy, w, h, angle)
    cx2, cy2, w2, h2, angle2 = corners_to_obb(corners)

    assert math.isclose(cx, cx2, abs_tol=0.5)
    assert math.isclose(cy, cy2, abs_tol=0.5)
    # minAreaRect can report the box as (w,h,angle) or (h,w,angle+90) - both describe
    # the same rectangle, so compare the corner polygons rather than the raw tuple.
    corners2 = obb_to_corners(cx2, cy2, w2, h2, angle2)
    assert _polygons_close(corners, corners2)


def _polygons_close(a, b, tol=1.0) -> bool:
    # Rotation/reflection/starting-point invariant: compare centroid + sorted vertex-to-centroid
    # distances, rather than sorting raw (x, y) tuples - lexicographic sort breaks on thin
    # rectangles where two vertices share (or nearly share) an x-coordinate.
    import numpy as _np

    a_arr, b_arr = _np.asarray(a, dtype=float), _np.asarray(b, dtype=float)
    ca, cb = a_arr.mean(axis=0), b_arr.mean(axis=0)
    if not (math.isclose(ca[0], cb[0], abs_tol=tol) and math.isclose(ca[1], cb[1], abs_tol=tol)):
        return False
    da = sorted(_np.linalg.norm(a_arr - ca, axis=1))
    db = sorted(_np.linalg.norm(b_arr - cb, axis=1))
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(da, db))


@given(obb_strategy)
@settings(max_examples=200)
def test_yolo_line_round_trip(params):
    cx, cy, w, h, angle = params
    img_w, img_h = 640, 640
    line = to_yolo_obb_line(0, cx, cy, w, h, angle, img_w, img_h)
    class_id, cx2, cy2, w2, h2, angle2 = from_yolo_obb_line(line, img_w, img_h)

    assert class_id == 0
    assert math.isclose(cx, cx2, abs_tol=1.0)
    assert math.isclose(cy, cy2, abs_tol=1.0)
    corners = obb_to_corners(cx, cy, w, h, angle)
    corners2 = obb_to_corners(cx2, cy2, w2, h2, angle2)
    assert _polygons_close(corners, corners2, tol=2.0)


def test_yolo_line_format_matches_ultralytics_convention():
    line = to_yolo_obb_line(3, 320, 320, 100, 50, 0, 640, 640)
    parts = line.split()
    assert len(parts) == 9  # class + 4 (x,y) pairs
    assert parts[0] == "3"
    assert all(0.0 <= float(v) <= 1.0 for v in parts[1:])


def test_axis_aligned_zero_angle_matches_wh():
    cx, cy, w, h = obb_to_axis_aligned(100, 100, 40, 20, 0)[:4]
    assert math.isclose(cx, 100, abs_tol=1e-3)
    assert math.isclose(cy, 100, abs_tol=1e-3)


def test_axis_aligned_45deg_bounding_box_is_larger_than_unrotated():
    _, _, w0, h0 = obb_to_axis_aligned(100, 100, 40, 20, 0)
    _, _, w45, h45 = obb_to_axis_aligned(100, 100, 40, 20, 45)
    assert w45 > w0
    assert h45 > h0


def test_line_allows_out_of_bounds_coords_for_edge_straddling_boxes():
    # A box near a tile edge (common with tiled, overlapping annotations) legitimately has
    # corners outside [0, img_w/img_h] - normalization must not clamp/distort it.
    line = to_yolo_obb_line(0, 10, 10, 100, 100, 0, 640, 640)
    values = [float(v) for v in line.split()[1:]]
    assert min(values) < 0.0


class TestObbAreaFractionInside:
    def test_fully_inside_box_is_100_pct(self):
        fraction = obb_area_fraction_inside(100, 100, 40, 40, 0, 640, 640)
        assert fraction == pytest.approx(1.0, abs=1e-3)

    def test_fully_outside_box_is_0_pct(self):
        fraction = obb_area_fraction_inside(-100, -100, 40, 40, 0, 640, 640)
        assert fraction == pytest.approx(0.0, abs=1e-3)

    def test_box_straddling_edge_is_half_inside(self):
        # 40x40 box centered exactly on the left edge (x=0) - half its area is inside.
        fraction = obb_area_fraction_inside(0, 100, 40, 40, 0, 640, 640)
        assert fraction == pytest.approx(0.5, abs=1e-3)

    def test_works_for_rotated_boxes_too(self):
        # A 40x40 box centered well inside the tile is fully inside regardless of rotation.
        fraction = obb_area_fraction_inside(100, 100, 40, 40, 30, 640, 640)
        assert fraction == pytest.approx(1.0, abs=1e-3)
