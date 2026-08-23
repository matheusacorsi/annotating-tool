// Ported verbatim from supervisely/frontend/src/components/canvas/obbMath.ts (private repo).
// This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually.

export interface Point {
  x: number;
  y: number;
}

export interface ObbBox {
  cx: number;
  cy: number;
  w: number;
  h: number;
  angle: number;
}

/**
 * Converts a 3-click rotated-box gesture into a (cx, cy, w, h, angle) box.
 *
 * p0 -> p1 defines one edge (its length becomes `w`, its direction becomes `angle`, in the
 * same degrees-clockwise convention Konva's `rotation` prop uses). p2 is then projected onto
 * the perpendicular of that edge to get `h` - this is the standard 3-point rotated-rectangle
 * construction used by rotated-box annotation tools (draw one edge, then sweep out the width),
 * and lets the user place an arbitrarily rotated box directly instead of drawing an
 * axis-aligned box and rotating it afterward.
 */
export function threePointsToObb(p0: Point, p1: Point, p2: Point): ObbBox {
  const ex = p1.x - p0.x;
  const ey = p1.y - p0.y;
  const length = Math.hypot(ex, ey);

  if (length < 1e-6) {
    return { cx: p0.x, cy: p0.y, w: 0, h: 0, angle: 0 };
  }

  const angle = (Math.atan2(ey, ex) * 180) / Math.PI;

  // Perpendicular direction matching Konva's local +y axis after rotating by `angle`.
  const perpX = -ey / length;
  const perpY = ex / length;

  const d = (p2.x - p0.x) * perpX + (p2.y - p0.y) * perpY;
  const h = Math.abs(d);

  const midX = (p0.x + p1.x) / 2;
  const midY = (p0.y + p1.y) / 2;
  const cx = midX + perpX * (d / 2);
  const cy = midY + perpY * (d / 2);

  return { cx, cy, w: length, h, angle };
}
