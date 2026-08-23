# Ported verbatim from supervisely/backend/app/annotations/obb_geometry.py (private repo).
# This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually.

from __future__ import annotations

import math

import cv2
import numpy as np


def obb_to_corners(cx: float, cy: float, w: float, h: float, angle: float) -> np.ndarray:
    """Returns 4 (x, y) corner points, ordered via cv2.boxPoints (same convention
    ultralytics/OpenCV rotated-rect tooling uses elsewhere in this codebase)."""
    rect = ((cx, cy), (w, h), angle)
    return cv2.boxPoints(rect)


def corners_to_obb(points: np.ndarray) -> tuple[float, float, float, float, float]:
    """Inverse of obb_to_corners, via cv2.minAreaRect - used to convert an arbitrary
    4-point polygon (e.g. a model's raw OBB output) into the internal (cx,cy,w,h,angle) form."""
    pts = np.asarray(points, dtype=np.float32)
    (cx, cy), (w, h), angle = cv2.minAreaRect(pts)
    return float(cx), float(cy), float(w), float(h), float(angle)


def obb_area_fraction_inside(cx: float, cy: float, w: float, h: float, angle: float, img_w: int, img_h: int) -> float:
    """Fraction of the box's area that falls within the [0,img_w] x [0,img_h] image bounds -
    used to filter out predictions that are mostly off-tile. Works for detect-task boxes too
    since angle=0 just yields an axis-aligned rect through the same corner math."""
    corners = obb_to_corners(cx, cy, w, h, angle).astype(np.float32)
    box_area = w * h
    if box_area <= 0:
        return 0.0
    tile_rect = np.array([[0, 0], [img_w, 0], [img_w, img_h], [0, img_h]], dtype=np.float32)
    inter_area, _ = cv2.intersectConvexConvex(corners, tile_rect)
    return float(inter_area / box_area)


def obb_to_axis_aligned(cx: float, cy: float, w: float, h: float, angle: float) -> tuple[float, float, float, float]:
    """Min/max bounding box of the rotated corners - used when a project's task_type is
    'detect' instead of 'obb', so the app never needs two separate annotation schemas."""
    corners = obb_to_corners(cx, cy, w, h, angle)
    x0, y0 = corners.min(axis=0)
    x1, y1 = corners.max(axis=0)
    return float((x0 + x1) / 2), float((y0 + y1) / 2), float(x1 - x0), float(y1 - y0)


def to_yolo_obb_line(
    class_id: int, cx: float, cy: float, w: float, h: float, angle: float, img_w: int, img_h: int
) -> str:
    # Deliberately not clamped to [0,1]: an object near a tile edge (common with tiled,
    # overlapping annotations) can have corners outside the tile, and clamping each corner
    # independently would distort the rectangle into a non-rectangular shape. Ultralytics'
    # own training pipeline already handles slightly out-of-range OBB coordinates.
    corners = obb_to_corners(cx, cy, w, h, angle)
    normalized = []
    for x, y in corners:
        normalized.append(x / img_w)
        normalized.append(y / img_h)
    coords = " ".join(f"{v:.6f}" for v in normalized)
    return f"{class_id} {coords}"


def from_yolo_obb_line(line: str, img_w: int, img_h: int) -> tuple[int, float, float, float, float, float]:
    parts = line.split()
    class_id = int(parts[0])
    values = [float(v) for v in parts[1:9]]
    points = np.array(
        [[values[i] * img_w, values[i + 1] * img_h] for i in range(0, 8, 2)],
        dtype=np.float32,
    )
    cx, cy, w, h, angle = corners_to_obb(points)
    return class_id, cx, cy, w, h, angle


def to_yolo_detect_line(class_id: int, cx: float, cy: float, w: float, h: float, img_w: int, img_h: int) -> str:
    return f"{class_id} {cx / img_w:.6f} {cy / img_h:.6f} {w / img_w:.6f} {h / img_h:.6f}"


def from_yolo_detect_line(line: str, img_w: int, img_h: int) -> tuple[int, float, float, float, float]:
    parts = line.split()
    class_id = int(parts[0])
    cx, cy, w, h = (float(v) for v in parts[1:5])
    return class_id, cx * img_w, cy * img_h, w * img_w, h * img_h


def normalize_angle_deg(angle: float) -> float:
    """Wraps to (-180, 180], matching how angles round-trip through cv2.minAreaRect."""
    wrapped = math.fmod(angle + 180.0, 360.0)
    if wrapped <= 0:
        wrapped += 360.0
    return wrapped - 180.0
