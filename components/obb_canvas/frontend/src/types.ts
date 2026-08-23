// Mirrors the relevant subset of supervisely/frontend/src/api/types.ts (private repo) - the
// component only needs the Annotation/ClassDef shapes, not the full API surface.

export type AnnotationSource = "manual" | "model";
export type AnnotationStatus = "unconfirmed" | "confirmed";

export interface Annotation {
  id: string;
  class_id: number;
  cx: number;
  cy: number;
  w: number;
  h: number;
  angle: number;
  source: AnnotationSource;
  confidence: number | null;
  status: AnnotationStatus;
  updated_at: string;
}

export interface ClassDef {
  id: number;
  name: string;
  color: string;
}
