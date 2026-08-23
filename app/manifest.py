# Ported from supervisely/backend/app/projects/manifest.py (private repo). This is the
# authority on the project-file schema/migration - models and migrate_manifest are kept
# byte-for-byte equivalent to the source; only manifest_path/load_manifest/save_manifest
# (disk I/O against a persistent workspace) are dropped, since the portable app has none.
# Separate repo, no shared package - keep in sync manually.

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field

from app.config import (
    DEFAULT_OVERLAP_PCT,
    DEFAULT_PADDING_MODE,
    DEFAULT_PROPORTION_PCT,
    DEFAULT_TILE_SIZE,
    MANIFEST_SCHEMA_VERSION,
)

TaskType = Literal["detect", "obb"]
SourceType = Literal["photo", "orthomosaic"]


class ClassDef(BaseModel):
    id: int
    name: str
    color: str = "#3DBE5B"


class TilingDefaults(BaseModel):
    tile_w: int = DEFAULT_TILE_SIZE
    tile_h: int = DEFAULT_TILE_SIZE
    overlap_pct: float = DEFAULT_OVERLAP_PCT
    padding_mode: str = DEFAULT_PADDING_MODE
    proportion_pct: float = DEFAULT_PROPORTION_PCT


class IngestEvent(BaseModel):
    """One ingest run's contribution to a source group (one folder/prefix)."""

    ingested_at: datetime | None = None
    source_type: SourceType = "photo"
    proportion_pct: float = DEFAULT_PROPORTION_PCT
    original_filenames: list[str] = Field(default_factory=list)
    tile_ids: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tile_count(self) -> int:
        return len(self.tile_ids)


class SourceSummary(BaseModel):
    """A group of ingested images sharing one folder/prefix, e.g. "field1" - built up over
    one or more ingest events so re-ingesting more photos into the same folder later shows
    up as a new sub-batch instead of a separate near-duplicate group."""

    source_id: str
    prefix: str
    events: list[IngestEvent] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tile_count(self) -> int:
        return sum(e.tile_count for e in self.events)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tile_ids(self) -> list[str]:
        return [tid for e in self.events for tid in e.tile_ids]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ingested_at(self) -> datetime | None:
        return self.events[0].ingested_at if self.events else None


class Manifest(BaseModel):
    schema_version: int = MANIFEST_SCHEMA_VERSION
    project_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    task_type: TaskType = "obb"
    classes: list[ClassDef] = Field(default_factory=list)
    tiling_defaults: TilingDefaults = Field(default_factory=TilingDefaults)
    sources: list[SourceSummary] = Field(default_factory=list)


def migrate_manifest(data: dict) -> dict:
    version = data.get("schema_version", 1)
    if version > MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Manifest schema_version {version} is newer than this app supports "
            f"({MANIFEST_SCHEMA_VERSION}); upgrade the app before importing this project."
        )
    if version < 2:
        for src in data.get("sources", []):
            src.setdefault("ingested_at", None)
            src.setdefault("tile_ids", [])
        data["schema_version"] = 2
    if version < 3:
        # Collapse the old flat per-image source list into one group per prefix (folder),
        # each holding a single collapsed IngestEvent - old data has no reliable way to tell
        # which images came from the same ingest call vs. a separate one reusing the same
        # prefix, so this is the most faithful grouping recoverable from v1/v2 manifests.
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for src in data.get("sources", []):
            prefix = src.get("prefix") or "source"
            if prefix not in grouped:
                grouped[prefix] = {
                    "source_id": src.get("source_id") or uuid4().hex[:8],
                    "prefix": prefix,
                    "events": [
                        {
                            "ingested_at": src.get("ingested_at"),
                            "source_type": src.get("source_type", "photo"),
                            "proportion_pct": src.get("proportion_pct", DEFAULT_PROPORTION_PCT),
                            "original_filenames": [],
                            "tile_ids": [],
                        }
                    ],
                }
                order.append(prefix)
            event = grouped[prefix]["events"][0]
            if src.get("original_filename"):
                event["original_filenames"].append(src["original_filename"])
            event["tile_ids"].extend(src.get("tile_ids", []))
            if src.get("ingested_at") and (not event["ingested_at"] or src["ingested_at"] < event["ingested_at"]):
                event["ingested_at"] = src["ingested_at"]
        data["sources"] = [grouped[p] for p in order]
        data.setdefault("tiling_defaults", {})
        data["tiling_defaults"].setdefault("proportion_pct", DEFAULT_PROPORTION_PCT)
        data["schema_version"] = 3
    return data
