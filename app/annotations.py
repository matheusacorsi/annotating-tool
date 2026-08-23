# Ported verbatim (modulo the import path) from supervisely/backend/app/annotations/schema.py
# (private repo). This is a separate repo (yolo-obb-portable) - no shared package - keep in
# sync manually.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import ANNOTATION_SCHEMA_VERSION

AnnotationSource = Literal["manual", "model"]
AnnotationStatus = Literal["unconfirmed", "confirmed"]
TileStatus = Literal["empty", "unconfirmed", "confirmed"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Annotation(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    class_id: int
    cx: float
    cy: float
    w: float
    h: float
    angle: float = 0.0
    source: AnnotationSource = "manual"
    confidence: float | None = None
    status: AnnotationStatus = "confirmed"
    updated_at: datetime = Field(default_factory=_now)


class TileAnnotations(BaseModel):
    schema_version: int = ANNOTATION_SCHEMA_VERSION
    tile_id: str
    width: int
    height: int
    annotations: list[Annotation] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def status(self) -> TileStatus:
        if not self.annotations:
            return "empty"
        if any(a.status == "unconfirmed" for a in self.annotations):
            return "unconfirmed"
        return "confirmed"

    @property
    def avg_confidence(self) -> float | None:
        confs = [a.confidence for a in self.annotations if a.source == "model" and a.confidence is not None]
        return sum(confs) / len(confs) if confs else None


def migrate_tile_annotations(data: dict) -> dict:
    version = data.get("schema_version", 1)
    if version > ANNOTATION_SCHEMA_VERSION:
        raise ValueError(
            f"Annotation schema_version {version} is newer than this app supports "
            f"({ANNOTATION_SCHEMA_VERSION}); upgrade the app before opening this project."
        )
    # No migrations defined yet; add version-by-version upgrades here as schema_version increases,
    # mirroring migrate_manifest() in app/manifest.py.
    data["schema_version"] = ANNOTATION_SCHEMA_VERSION
    return data
