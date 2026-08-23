"""Tile gallery + drawing canvas. Page-level keyboard shortcuts (tile nav, number-key relabel,
confirm-tile, VI toggle) don't reliably cross the Streamlit-page/component-iframe boundary, so
this ships on-screen buttons for all of those instead of hotkeys - an intentional v1 scope cut
(the canvas component itself still handles Delete/Backspace locally, see main.tsx)."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import streamlit as st

from app.annotations import Annotation, TileStatus
from app.session_state import SessionProject, get_project

from components.obb_canvas import obb_canvas

_STATUS_FILTERS: list[TileStatus | str] = ["all", "confirmed", "unconfirmed", "empty"]


def _selected_tile_id(project: SessionProject) -> str | None:
    tile_id = st.session_state.get("annotate_selected_tile_id")
    if tile_id in project.tiles:
        return tile_id
    return None


def _select_tile(tile_id: str) -> None:
    st.session_state["annotate_selected_tile_id"] = tile_id


def _tile_gallery(project: SessionProject) -> None:
    status_filter = st.selectbox("Status filter", _STATUS_FILTERS, key="annotate_status_filter")

    tile_ids = list(project.tiles.keys())
    if status_filter != "all":
        tile_ids = [tid for tid in tile_ids if project.annotations[tid].status == status_filter]

    if not tile_ids:
        st.caption("No tiles match this filter.")
        return

    selected = _selected_tile_id(project)
    cols = st.columns(3)
    for i, tile_id in enumerate(tile_ids):
        col = cols[i % 3]
        col.image(project.thumbnails[tile_id], use_container_width=True)
        label = ("➤ " if tile_id == selected else "") + tile_id
        if col.button(label, key=f"select_tile_{tile_id}"):
            _select_tile(tile_id)
            st.rerun()


def _class_selector(project: SessionProject) -> int:
    classes = project.manifest.classes
    ids = [c.id for c in classes]
    names = {c.id: c.name for c in classes}
    default = st.session_state.get("annotate_selected_class_id", ids[0] if ids else 0)
    if default not in ids and ids:
        default = ids[0]
    selected = st.radio(
        "Class (for new boxes)",
        ids,
        format_func=lambda cid: names.get(cid, str(cid)),
        index=ids.index(default) if default in ids else 0,
        key="annotate_selected_class_id",
    )
    return selected


def _apply_event(project: SessionProject, tile_id: str, event: dict) -> None:
    tile_annotations = project.annotations[tile_id]
    now = datetime.now(timezone.utc)

    if event["type"] == "create":
        payload = event["annotation"]
        tile_annotations.annotations.append(
            Annotation(
                class_id=payload["class_id"],
                cx=payload["cx"],
                cy=payload["cy"],
                w=payload["w"],
                h=payload["h"],
                angle=payload["angle"],
            )
        )
    elif event["type"] == "change":
        for a in tile_annotations.annotations:
            if a.id == event["id"]:
                for field, value in event["patch"].items():
                    setattr(a, field, value)
                a.updated_at = now
                break
    elif event["type"] == "delete":
        tile_annotations.annotations = [a for a in tile_annotations.annotations if a.id != event["id"]]
    elif event["type"] == "select":
        return  # local UI concern only; nothing to persist

    tile_annotations.updated_at = now


def _tile_to_data_url(tile_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(tile_bytes).decode("ascii")


def render() -> None:
    project = get_project()
    if project is None or len(project.tiles) == 0:
        st.info("No tiles yet - import a project or tile some images in the Ingest tab first.")
        return

    gallery_col, canvas_col = st.columns([1, 2])

    with gallery_col:
        _tile_gallery(project)

    tile_id = _selected_tile_id(project)
    if tile_id is None:
        with canvas_col:
            st.info("Select a tile from the gallery to start annotating.")
        return

    with canvas_col:
        top = st.columns([2, 1, 1])
        with top[0]:
            selected_class_id = _class_selector(project)
        with top[1]:
            vi_mode = st.checkbox("VI overlay", key="annotate_vi_mode")
            vi_threshold = st.slider(
                "VI threshold", -2.0, 2.0, 0.0, 0.05, key="annotate_vi_threshold", disabled=not vi_mode
            )
        with top[2]:
            if st.button("✓ Confirm tile", key="confirm_tile_btn"):
                for a in project.annotations[tile_id].annotations:
                    a.status = "confirmed"
                project.annotations[tile_id].updated_at = datetime.now(timezone.utc)
                st.rerun()

        tile_annotations = project.annotations[tile_id]
        event = obb_canvas(
            image_url=_tile_to_data_url(project.tiles[tile_id]),
            annotations=tile_annotations.annotations,
            classes=project.manifest.classes,
            shape_mode=project.manifest.task_type,
            selected_class_id=selected_class_id,
            vi_mode=vi_mode,
            vi_threshold=vi_threshold,
            height=640,
            key=f"obb_canvas_{tile_id}",
        )

        # Streamlit redelivers the *last* component value on every rerun (triggered by any
        # widget, not just this one) until a genuinely new value is set - dedupe on the
        # per-event nonce so an unrelated rerun (e.g. toggling VI mode) can never reapply a
        # stale "create"/"change"/"delete" and double up an edit.
        nonce_key = f"annotate_last_nonce_{tile_id}"
        if event is not None and event.get("nonce") != st.session_state.get(nonce_key):
            st.session_state[nonce_key] = event["nonce"]
            _apply_event(project, tile_id, event)
            if event["type"] != "select":
                st.rerun()
