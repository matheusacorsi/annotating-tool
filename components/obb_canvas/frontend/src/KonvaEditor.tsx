// Ported from supervisely/frontend/src/components/canvas/KonvaEditor.tsx (private repo).
// This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually.
// Internals (drawing state machine, wheel/pan math, Transformer wiring) are UNCHANGED from
// the source - only the import paths differ (this component's own ./types, ./exgr instead of
// the full app's ../../api/types, ../../lib/exgr). onToolChange/onSelect/onCreate/onChange
// are supplied by main.tsx, which turns onCreate/onChange/onSelect into Streamlit bridge
// events while keeping onToolChange as local component state, exactly like the full app keeps
// tool/selectedAnnotationId as local AnnotateTab state.

import { useEffect, useRef, useState } from "react";
import { Image as KonvaImage, Layer, Line, Rect, Stage } from "react-konva";
import type Konva from "konva";
import useImage from "use-image";
import type { Annotation, ClassDef } from "./types";
import { computeExgrCanvas } from "./exgr";
import { ObbShape } from "./ObbShape";
import { threePointsToObb, type Point } from "./obbMath";

interface KonvaEditorProps {
  imageUrl: string;
  annotations: Annotation[];
  classes: ClassDef[];
  tool: "select" | "draw";
  shapeMode: "obb" | "detect";
  selectedClassId: number;
  selectedAnnotationId: string | null;
  viMode: boolean;
  viThreshold: number;
  onToolChange: (tool: "select" | "draw") => void;
  onSelect: (id: string | null) => void;
  onCreate: (patch: Omit<Annotation, "id" | "source" | "status" | "confidence" | "updated_at">) => void;
  onChange: (id: string, patch: Partial<Annotation>) => void;
}

const MIN_SCALE = 0.1;
const MAX_SCALE = 10;
const MIN_OBB_EDGE = 4;

function classColor(classes: ClassDef[], classId: number): string {
  return classes.find((c) => c.id === classId)?.color ?? "#3DBE5B";
}

export function KonvaEditor({
  imageUrl,
  annotations,
  classes,
  tool,
  shapeMode,
  selectedClassId,
  selectedAnnotationId,
  viMode,
  viThreshold,
  onToolChange,
  onSelect,
  onCreate,
  onChange,
}: KonvaEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const [image] = useImage(imageUrl, "anonymous");
  const [viCanvas, setViCanvas] = useState<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [stageScale, setStageScale] = useState(1);
  const [stagePos, setStagePos] = useState({ x: 0, y: 0 });
  const [fitted, setFitted] = useState(false);
  const [hoveredAnnotationId, setHoveredAnnotationId] = useState<string | null>(null);

  const panState = useRef<{ startPointer: Point; startPos: Point } | null>(null);

  // draw + shapeMode "detect" (drag corner-to-corner, always axis-aligned)
  const rectDrawState = useRef<Point | null>(null);
  const [draftRect, setDraftRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  // draw + shapeMode "obb" (click edge start -> edge end -> width; see obbMath.ts)
  const [obbDraft, setObbDraft] = useState<{ p0: Point; p1?: Point } | null>(null);
  const [cursorPos, setCursorPos] = useState<Point | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setFitted(false);
  }, [imageUrl]);

  useEffect(() => {
    if (!image || fitted || size.width === 0) return;
    const scale = Math.min(size.width / image.width, size.height / image.height, 1) * 0.95;
    setStageScale(scale);
    setStagePos({
      x: (size.width - image.width * scale) / 2,
      y: (size.height - image.height * scale) / 2,
    });
    setFitted(true);
  }, [image, size, fitted]);

  // Escape cancels an in-progress OBB placement (1st or 2nd click already placed) and drops
  // back to select mode, mirroring the auto-return-to-select on a completed draw below.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setObbDraft(null);
        onToolChange("select");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onToolChange]);

  // Only clears the draft when *leaving* draw mode (e.g. the user manually hits the Select
  // button/hotkey mid-gesture) - NOT when entering it, since starting a gesture (below) sets
  // `tool` to "draw" in the same event as setting the first point, and this effect running
  // right after must not wipe that point back out from under it.
  useEffect(() => {
    if (tool === "select") setObbDraft(null);
    else setHoveredAnnotationId(null);
  }, [tool]);

  useEffect(() => {
    setObbDraft(null);
    setHoveredAnnotationId(null);
  }, [imageUrl]);

  // requestAnimationFrame collapses bursts of threshold-slider onChange events so recompute
  // never runs more than once per paint; a 640x640 tile is well under a frame budget either way.
  useEffect(() => {
    if (!viMode || !image) {
      setViCanvas(null);
      return;
    }
    const raf = requestAnimationFrame(() => {
      setViCanvas(computeExgrCanvas(image, viThreshold));
    });
    return () => cancelAnimationFrame(raf);
  }, [viMode, viThreshold, image]);

  function toImageCoords(pointer: Point): Point {
    return { x: (pointer.x - stagePos.x) / stageScale, y: (pointer.y - stagePos.y) / stageScale };
  }

  function handleWheel(e: Konva.KonvaEventObject<WheelEvent>) {
    e.evt.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const oldScale = stageScale;
    const mousePointTo = { x: (pointer.x - stagePos.x) / oldScale, y: (pointer.y - stagePos.y) / oldScale };
    const direction = e.evt.deltaY > 0 ? -1 : 1;
    const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, oldScale * (1 + direction * 0.08)));

    setStageScale(newScale);
    setStagePos({
      x: pointer.x - mousePointTo.x * newScale,
      y: pointer.y - mousePointTo.y * newScale,
    });
  }

  function isEmptyTarget(e: Konva.KonvaEventObject<MouseEvent>) {
    return e.target === stageRef.current || e.target.name() === "background";
  }

  function handleMouseDown(e: Konva.KonvaEventObject<MouseEvent>) {
    const stage = stageRef.current;
    if (!stage) return;
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    // The right mouse button always pans, regardless of tool or what's under the cursor -
    // checked before the isEmptyTarget/tool branches below so it works even mid-draw or
    // while hovering an existing annotation.
    if (e.evt.button === 2) {
      panState.current = { startPointer: pointer, startPos: stagePos };
      return;
    }

    if (!isEmptyTarget(e)) return; // let the shape's own onClick handle selection

    // Clicking empty canvas always means "start a new box" - no separate action needed to
    // enter draw mode first. `tool` auto-flips to "draw" for the duration of the gesture (so
    // the existing shapes-non-interactive-during-draw fix keeps applying) and back to "select"
    // once the box is finalized or cancelled, so a plain click can immediately select the
    // shape you just drew, and the next empty click starts the next one - no manual toggling.
    const imgPos = toImageCoords(pointer);

    if (shapeMode === "detect") {
      if (tool !== "draw") onToolChange("draw");
      rectDrawState.current = imgPos;
      setDraftRect({ x: imgPos.x, y: imgPos.y, w: 0, h: 0 });
    } else if (!obbDraft) {
      if (tool !== "draw") onToolChange("draw");
      setObbDraft({ p0: imgPos });
    } else if (!obbDraft.p1) {
      setObbDraft({ p0: obbDraft.p0, p1: imgPos });
    } else {
      // third click: finalize. Read obbDraft from the closure (current render's state) and
      // call onCreate directly here rather than inside the setObbDraft updater - updater
      // callbacks must stay pure and can run during React's render phase, so triggering a
      // parent setState (onCreate) from inside one violates that and warns/misbehaves.
      const box = threePointsToObb(obbDraft.p0, obbDraft.p1, imgPos);
      setObbDraft(null);
      onToolChange("select");
      if (box.w > MIN_OBB_EDGE && box.h > MIN_OBB_EDGE) {
        onCreate({ class_id: selectedClassId, cx: box.cx, cy: box.cy, w: box.w, h: box.h, angle: box.angle });
      }
    }
  }

  function handleMouseMove() {
    const stage = stageRef.current;
    if (!stage) return;
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    if (rectDrawState.current) {
      const imgPos = toImageCoords(pointer);
      const { x: x0, y: y0 } = rectDrawState.current;
      setDraftRect({
        x: Math.min(x0, imgPos.x),
        y: Math.min(y0, imgPos.y),
        w: Math.abs(imgPos.x - x0),
        h: Math.abs(imgPos.y - y0),
      });
    } else if (obbDraft) {
      setCursorPos(toImageCoords(pointer));
    } else if (panState.current) {
      const { startPointer, startPos } = panState.current;
      setStagePos({
        x: startPos.x + (pointer.x - startPointer.x),
        y: startPos.y + (pointer.y - startPointer.y),
      });
    }
  }

  function handleMouseUp() {
    if (rectDrawState.current) {
      if (draftRect && draftRect.w > 4 && draftRect.h > 4) {
        onCreate({
          class_id: selectedClassId,
          cx: draftRect.x + draftRect.w / 2,
          cy: draftRect.y + draftRect.h / 2,
          w: draftRect.w,
          h: draftRect.h,
          angle: 0,
        });
      }
      rectDrawState.current = null;
      setDraftRect(null);
      onToolChange("select");
    }
    panState.current = null;
  }

  function handleContextMenu(e: Konva.KonvaEventObject<PointerEvent>) {
    // Right button is dedicated to panning (see handleMouseDown) - just suppress the native
    // browser context menu. Press Escape to cancel an in-progress OBB draft instead.
    e.evt.preventDefault();
  }

  const obbPreviewBox = obbDraft?.p1 && cursorPos ? threePointsToObb(obbDraft.p0, obbDraft.p1, cursorPos) : null;
  const drawColor = classColor(classes, selectedClassId);

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%", overflow: "hidden", background: "#1e1e1e" }}>
      <Stage
        ref={stageRef}
        width={size.width}
        height={size.height}
        scaleX={stageScale}
        scaleY={stageScale}
        x={stagePos.x}
        y={stagePos.y}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onContextMenu={handleContextMenu}
        style={{ cursor: tool === "select" ? "default" : "crosshair" }}
      >
        <Layer>
          {(viMode ? viCanvas : image) && (
            <KonvaImage
              image={(viMode ? viCanvas : image) as HTMLCanvasElement | HTMLImageElement}
              name="background"
              listening
            />
          )}
          {annotations.map((a) => (
            <ObbShape
              key={a.id}
              annotation={a}
              color={classColor(classes, a.class_id)}
              isSelected={a.id === selectedAnnotationId}
              isHovered={tool === "select" && a.id === hoveredAnnotationId}
              draggable={tool === "select"}
              interactive={tool === "select"}
              onSelect={() => onSelect(a.id)}
              onHoverChange={(hovering) =>
                setHoveredAnnotationId((prev) => {
                  if (hovering) return a.id;
                  return prev === a.id ? null : prev;
                })
              }
              onChange={(patch) => onChange(a.id, patch)}
            />
          ))}
          {draftRect && (
            <Rect
              x={draftRect.x}
              y={draftRect.y}
              width={draftRect.w}
              height={draftRect.h}
              stroke={drawColor}
              strokeWidth={2}
              dash={[4, 4]}
              listening={false}
            />
          )}
          {obbDraft && !obbDraft.p1 && cursorPos && (
            <Line
              points={[obbDraft.p0.x, obbDraft.p0.y, cursorPos.x, cursorPos.y]}
              stroke={drawColor}
              strokeWidth={2}
              dash={[4, 4]}
              listening={false}
            />
          )}
          {obbDraft?.p1 && !cursorPos && (
            <Line
              points={[obbDraft.p0.x, obbDraft.p0.y, obbDraft.p1.x, obbDraft.p1.y]}
              stroke={drawColor}
              strokeWidth={2}
              dash={[4, 4]}
              listening={false}
            />
          )}
          {obbPreviewBox && (
            <Rect
              x={obbPreviewBox.cx}
              y={obbPreviewBox.cy}
              width={obbPreviewBox.w}
              height={obbPreviewBox.h}
              offsetX={obbPreviewBox.w / 2}
              offsetY={obbPreviewBox.h / 2}
              rotation={obbPreviewBox.angle}
              stroke={drawColor}
              strokeWidth={2}
              dash={[4, 4]}
              listening={false}
            />
          )}
        </Layer>
      </Stage>
    </div>
  );
}
