# Adapted from supervisely/backend/tests/test_manifest.py's TestManifestMigration class (private
# repo) - same migrate_manifest behavior/assertions, but calling it directly on constructed dicts
# instead of through the full app's disk-backed service/load_manifest round-trip, since the
# portable app has no such layer.

import pytest

from app.manifest import Manifest, migrate_manifest


class TestManifestMigration:
    def test_schema_v1_manifest_backfills_source_batch_fields(self):
        legacy_data = {
            "schema_version": 1,
            "project_id": "abc",
            "name": "Legacy Project",
            "sources": [
                {
                    "source_id": "abc123",
                    "original_filename": "IMG_0001.jpg",
                    "source_type": "photo",
                    "width": 1280,
                    "height": 1280,
                    "proportion_pct": 100,
                    "tile_count": 4,
                    "prefix": "field1",
                    # no ingested_at / tile_ids - simulates a pre-migration manifest on disk
                }
            ],
        }

        migrated = migrate_manifest(legacy_data)
        reloaded = Manifest.model_validate(migrated)

        assert reloaded.schema_version == 3
        assert len(reloaded.sources) == 1
        assert reloaded.sources[0].ingested_at is None
        assert reloaded.sources[0].tile_ids == []

    def test_schema_v1_manifest_collapses_into_one_group_per_prefix(self):
        legacy_data = {
            "schema_version": 1,
            "project_id": "abc",
            "name": "Very Legacy Project",
            "sources": [
                {
                    "source_id": "abc123",
                    "original_filename": "IMG_0001.jpg",
                    "source_type": "photo",
                    "width": 1280,
                    "height": 1280,
                    "proportion_pct": 100,
                    "tile_count": 4,
                    "prefix": "field1",
                    "tile_ids": ["field1_IMG_0001_tile_00000", "field1_IMG_0001_tile_00001"],
                },
                {
                    "source_id": "def456",
                    "original_filename": "IMG_0002.jpg",
                    "source_type": "photo",
                    "width": 1280,
                    "height": 1280,
                    "proportion_pct": 100,
                    "tile_count": 4,
                    "prefix": "field1",
                    "tile_ids": ["field1_IMG_0002_tile_00000", "field1_IMG_0002_tile_00001"],
                },
                {
                    "source_id": "ghi789",
                    "original_filename": "IMG_0100.jpg",
                    "source_type": "orthomosaic",
                    "width": 4000,
                    "height": 4000,
                    "proportion_pct": 50,
                    "tile_count": 9,
                    "prefix": "field2",
                    "tile_ids": [f"field2_IMG_0100_tile_{i:05d}" for i in range(9)],
                },
            ],
        }

        migrated = migrate_manifest(legacy_data)
        reloaded = Manifest.model_validate(migrated)

        assert reloaded.schema_version == 3
        # Two prefixes ("field1", "field2") collapse the three old per-image entries into two groups.
        assert len(reloaded.sources) == 2
        assert reloaded.tiling_defaults.proportion_pct is not None

        field1 = next(s for s in reloaded.sources if s.prefix == "field1")
        assert len(field1.events) == 1
        assert field1.tile_count == 4
        assert sorted(field1.events[0].original_filenames) == ["IMG_0001.jpg", "IMG_0002.jpg"]

        field2 = next(s for s in reloaded.sources if s.prefix == "field2")
        assert len(field2.events) == 1
        assert field2.tile_count == 9
        assert field2.events[0].source_type == "orthomosaic"

    def test_rejects_a_manifest_newer_than_this_app_supports(self):
        with pytest.raises(ValueError):
            migrate_manifest({"schema_version": 99, "project_id": "abc", "name": "Future"})
