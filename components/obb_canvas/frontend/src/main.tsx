import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
// Import from the `streamlit` submodule directly, NOT the package root / `StreamlitReact`
// (which is what `withStreamlitConnection`/`ComponentProps` live in). streamlit-component-lib
// bundles its own react@16.14.0 as a real dependency (not a peer dep), and that HOC is built
// with it - mixing its React-16-created elements into this app's React 19 tree throws "A React
// Element from an older version of React was rendered." `streamlit.ts` itself has zero React
// dependency (it's a plain messaging class + a CustomEvent-based render event), so importing
// only that file avoids ever loading the old React copy, at the cost of reimplementing the
// handful of lines `withStreamlitConnection` would otherwise give us (ready/render-event
// subscription, frame height).
import { Streamlit, type RenderData } from "streamlit-component-lib/dist/streamlit";
import { KonvaEditor } from "./KonvaEditor";
import type { Annotation, ClassDef } from "./types";

interface ObbCanvasArgs {
  image_url: string;
  annotations: Annotation[];
  classes: ClassDef[];
  shape_mode: "obb" | "detect";
  selected_class_id: number;
  vi_mode: boolean;
  vi_threshold: number;
  height: number;
}

type BridgeEvent =
  | { type: "create"; nonce: string; annotation: Omit<Annotation, "id" | "source" | "status" | "confidence" | "updated_at"> }
  | { type: "change"; nonce: string; id: string; patch: Partial<Annotation> }
  | { type: "select"; nonce: string; id: string | null }
  | { type: "delete"; nonce: string; id: string };

// Plain `Omit<Union, K>` collapses a discriminated union down to its common fields only (a
// well-known TS gotcha - Pick/Omit don't distribute over a union on their own), which would
// strip `annotation`/`id`/`patch` from every variant below. Distributing over `T` first (via
// the `T extends any ? ... : never` conditional) keeps each variant's own fields intact.
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

function ObbCanvas({ args }: { args: ObbCanvasArgs }) {
  // tool/selection are local UI-only state (matching the full app's own KonvaEditor usage) -
  // no reason to round-trip every draw-mode toggle or hover through Python; only the four
  // semantically-meaningful events below cross the Streamlit bridge.
  const [tool, setTool] = useState<"select" | "draw">("select");
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);

  useEffect(() => {
    Streamlit.setFrameHeight(args.height || 640);
  }, [args.height]);

  function emit(event: DistributiveOmit<BridgeEvent, "nonce">) {
    // nonce lets the Python side dedupe: Streamlit redelivers the *last* component value on
    // every rerun (triggered by any widget, not just this one) until a genuinely new value is
    // set - without a per-event nonce, an unrelated rerun could reapply a stale "create" and
    // duplicate a box.
    Streamlit.setComponentValue({ ...event, nonce: crypto.randomUUID() } as BridgeEvent);
  }

  function handleSelect(id: string | null) {
    setSelectedAnnotationId(id);
    emit({ type: "select", id });
  }

  function handleDelete() {
    if (!selectedAnnotationId) return;
    emit({ type: "delete", id: selectedAnnotationId });
    setSelectedAnnotationId(null);
  }

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.key === "Delete" || e.key === "Backspace") && selectedAnnotationId) {
        e.preventDefault();
        handleDelete();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAnnotationId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
        <button
          type="button"
          onClick={() => setTool("select")}
          style={{ fontWeight: tool === "select" ? 700 : 400 }}
        >
          Select (V)
        </button>
        <button
          type="button"
          onClick={() => setTool("draw")}
          style={{ fontWeight: tool === "draw" ? 700 : 400 }}
        >
          Draw (D)
        </button>
        <button type="button" onClick={handleDelete} disabled={!selectedAnnotationId}>
          Delete selected
        </button>
        {tool === "draw" && args.shape_mode === "obb" && (
          <span style={{ color: "#888" }}>click edge start → edge end → width</span>
        )}
      </div>
      <div style={{ height: (args.height || 640) - 40 }}>
        <KonvaEditor
          imageUrl={args.image_url}
          annotations={args.annotations}
          classes={args.classes}
          tool={tool}
          shapeMode={args.shape_mode}
          selectedClassId={args.selected_class_id}
          selectedAnnotationId={selectedAnnotationId}
          viMode={args.vi_mode}
          viThreshold={args.vi_threshold}
          onToolChange={setTool}
          onSelect={handleSelect}
          onCreate={(annotation) => emit({ type: "create", annotation })}
          onChange={(id, patch) => emit({ type: "change", id, patch })}
        />
      </div>
    </div>
  );
}

function Root() {
  const [args, setArgs] = useState<ObbCanvasArgs | null>(null);

  useEffect(() => {
    function onRender(event: Event) {
      setArgs((event as CustomEvent<RenderData<ObbCanvasArgs>>).detail.args);
    }
    Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
    Streamlit.setComponentReady();
    return () => Streamlit.events.removeEventListener(Streamlit.RENDER_EVENT, onRender);
  }, []);

  if (!args) return null;
  return <ObbCanvas args={args} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
