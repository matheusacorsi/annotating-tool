from __future__ import annotations

import streamlit as st

from app.config import DEFAULT_OVERLAP_PCT, DEFAULT_PADDING_MODE, DEFAULT_PROPORTION_PCT, DEFAULT_TILE_SIZE
from app.portable_ingest import preview_tile_counts, tile_uploaded_files
from app.session_state import SessionProject, get_project, set_project

_PALETTE_FIRST = "#3DBE5B"


def render() -> None:
    st.header("Ingest raw images")
    project = get_project()

    if project is not None and len(project.tiles) > 0:
        st.warning(
            "This session already has a tiled/loaded project. Tiling new images here "
            "**replaces** it (single active project per session) - export first if you want "
            "to keep the current one.",
            icon="⚠️",
        )

    files = st.file_uploader(
        "Raw photo(s) to tile",
        type=["jpg", "jpeg", "png", "tif", "tiff"],
        accept_multiple_files=True,
        key="ingest_files",
    )

    col1, col2, col3 = st.columns(3)
    tile_w = col1.number_input("Tile width", min_value=32, value=DEFAULT_TILE_SIZE, step=32)
    tile_h = col2.number_input("Tile height", min_value=32, value=DEFAULT_TILE_SIZE, step=32)
    overlap_pct = col3.number_input("Overlap %", min_value=0.0, max_value=99.0, value=float(DEFAULT_OVERLAP_PCT))

    col4, col5 = st.columns(2)
    proportion_pct = col4.slider("Crop % (centered on the image)", 1, 100, DEFAULT_PROPORTION_PCT)
    padding_mode = col5.selectbox(
        "Padding mode", ["shift", "reflect", "constant_black", "drop_partial"],
        index=["shift", "reflect", "constant_black", "drop_partial"].index(DEFAULT_PADDING_MODE),
    )

    prefix = st.text_input("Source prefix", value="upload")

    if not files:
        st.info("Upload one or more photos to continue.")
        return

    if st.button("Preview tiling"):
        try:
            preview = preview_tile_counts(files, tile_w, tile_h, overlap_pct, proportion_pct)
        except OSError as exc:
            # PIL.UnidentifiedImageError (a corrupt/unsupported file slipped past the
            # extension filter) is a subclass of OSError, as are other decode failures.
            st.error(f"Couldn't read one of the uploaded files as an image: {exc}")
            return
        total = sum(p["tile_count"] for p in preview)
        st.write(f"**{total} tiles total**")
        for p in preview:
            grew = abs(p["effective_width_pct"] - p["requested_proportion_pct"]) > 0.01 or (
                abs(p["effective_height_pct"] - p["requested_proportion_pct"]) > 0.01
            )
            msg = f"{p['filename']}: {p['tile_count']} tiles ({p['width']}×{p['height']}px source)"
            if grew:
                st.warning(
                    f"{msg} — crop grown to {p['effective_width_pct']:.1f}%×{p['effective_height_pct']:.1f}% "
                    "to keep tiles from overlapping at the edge",
                    icon="ℹ️",
                )
            else:
                st.caption(f"{msg} (used as requested)")

    if st.button("Tile these images", type="primary"):
        existing_classes = project.manifest.classes if project else []
        existing_task_type = project.manifest.task_type if project else "obb"
        existing_name = project.manifest.name if project else "Untitled project"
        if not existing_classes:
            st.error("Add at least one class in the sidebar before tiling images.")
            return
        try:
            with st.spinner("Tiling..."):
                new_project: SessionProject = tile_uploaded_files(
                    files=files,
                    tile_w=tile_w,
                    tile_h=tile_h,
                    overlap_pct=overlap_pct,
                    padding_mode=padding_mode,
                    proportion_pct=proportion_pct,
                    prefix=prefix or "upload",
                    classes=existing_classes,
                    project_name=existing_name,
                    task_type=existing_task_type,
                )
        except OSError as exc:
            st.error(f"Couldn't read one of the uploaded files as an image: {exc}")
            return
        set_project(new_project)
        st.success(f"Tiled {len(new_project.tiles)} tiles. Switch to the Annotate tab to start.")
        st.rerun()
