// Ported verbatim (modulo the Annotation import path) from
// supervisely/frontend/src/components/canvas/ObbShape.tsx (private repo).
// This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually;
// logic must stay byte-for-byte equivalent to the full app's canvas.

import { useEffect, useRef } from "react";
import { Rect, Transformer } from "react-konva";
import type Konva from "konva";
import type { Annotation } from "./types";

interface ObbShapeProps {
  annotation: Annotation;
  color: string;
  isSelected: boolean;
  isHovered: boolean;
  draggable: boolean;
  // False while a draw tool is active: shapes must not intercept clicks/hover then, or placing
  // a vertex on top of an existing box selects that box instead of continuing the new one.
  interactive: boolean;
  onSelect: () => void;
  onHoverChange: (hovering: boolean) => void;
  onChange: (patch: Partial<Annotation>) => void;
}

const ALL_ANCHORS = [
  "top-left",
  "top-center",
  "top-right",
  "middle-right",
  "middle-left",
  "bottom-left",
  "bottom-center",
  "bottom-right",
];

export function ObbShape({
  annotation,
  color,
  isSelected,
  isHovered,
  draggable,
  interactive,
  onSelect,
  onHoverChange,
  onChange,
}: ObbShapeProps) {
  const shapeRef = useRef<Konva.Rect>(null);
  const trRef = useRef<Konva.Transformer>(null);
  // The Transformer's anchors (and especially its rotate handle, ~50px past the shape by
  // default) sit outside the Rect's own bounds. Hovering is "true" while the pointer is over
  // either the Rect OR the Transformer/its anchors (mouseover/mouseout bubble from anchor
  // children up to the Transformer, unlike mouseenter/mouseleave) - otherwise moving the
  // cursor from the shape toward a handle crosses a dead zone that hides the handles first.
  const overRectRef = useRef(false);
  const overHandlesRef = useRef(false);
  // Additionally suppress hover-out entirely while a drag/transform is actively in progress,
  // as a safety net in case Konva doesn't fire a matching mouseout for a handle mid-gesture.
  const interactingRef = useRef(false);

  function reportHover() {
    onHoverChange(overRectRef.current || overHandlesRef.current);
  }

  const showHandles = interactive && (isSelected || isHovered);

  useEffect(() => {
    if (showHandles && shapeRef.current && trRef.current) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer()?.batchDraw();
    }
  }, [showHandles]);

  const isUnconfirmed = annotation.status === "unconfirmed";

  return (
    <>
      <Rect
        ref={shapeRef}
        x={annotation.cx}
        y={annotation.cy}
        width={annotation.w}
        height={annotation.h}
        offsetX={annotation.w / 2}
        offsetY={annotation.h / 2}
        rotation={annotation.angle}
        stroke={color}
        strokeWidth={2}
        // Small padding past the visible border so hovering along the edge doesn't drop out of
        // the hit area in the sub-pixel gap right before reaching an anchor (anchors are
        // centered on the border, ~5px outside it); the Transformer's own over/out tracking
        // below covers the rest of the distance out to the anchors and rotate handle.
        hitStrokeWidth={10}
        dash={isUnconfirmed ? [6, 4] : undefined}
        fill={isUnconfirmed ? `${color}22` : `${color}11`}
        listening={interactive}
        draggable={draggable}
        onClick={onSelect}
        onTap={onSelect}
        onMouseOver={() => {
          overRectRef.current = true;
          reportHover();
        }}
        onMouseOut={() => {
          overRectRef.current = false;
          if (!interactingRef.current) reportHover();
        }}
        onDragStart={() => {
          interactingRef.current = true;
        }}
        onDragEnd={(e) => {
          interactingRef.current = false;
          onChange({ cx: e.target.x(), cy: e.target.y() });
        }}
        onTransformStart={() => {
          interactingRef.current = true;
        }}
        onTransformEnd={() => {
          interactingRef.current = false;
          const node = shapeRef.current;
          if (!node) return;
          const scaleX = node.scaleX();
          const scaleY = node.scaleY();
          const newW = Math.max(4, node.width() * scaleX);
          const newH = Math.max(4, node.height() * scaleY);
          node.scaleX(1);
          node.scaleY(1);
          onChange({
            cx: node.x(),
            cy: node.y(),
            w: newW,
            h: newH,
            angle: node.rotation(),
          });
          reportHover();
        }}
      />
      {showHandles && (
        <Transformer
          ref={trRef}
          rotateEnabled
          enabledAnchors={ALL_ANCHORS}
          flipEnabled={false}
          onMouseOver={() => {
            overHandlesRef.current = true;
            reportHover();
          }}
          onMouseOut={() => {
            overHandlesRef.current = false;
            if (!interactingRef.current) reportHover();
          }}
        />
      )}
    </>
  );
}
