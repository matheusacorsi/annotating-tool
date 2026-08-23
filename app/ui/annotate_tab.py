"""Tile gallery + drawing canvas. Page-level keyboard shortcuts (tile nav, confirm-tile, VI
toggle) don't reliably cross the Streamlit-page/component-iframe boundary, so those ship as
on-screen buttons instead of hotkeys - an intentional v1 scope cut. Shortcuts that only need to
work *inside* the canvas (Delete/Backspace to remove the selected box, 1-9 to relabel it) are
handled entirely client-side in main.tsx instead, where that boundary isn't a problem."""

from __future__ import annotations

import base64
import io
from datetime import datetime, timezone

import streamlit as st
from PIL import Image

from app.annotations import Annotation, TileStatus
from app.session_state import SessionProject, get_project

from components.obb_canvas import obb_canvas

_STATUS_FILTERS: list[TileStatus | str] = ["all", "confirmed", "unconfirmed", "empty"]

# The stored/exported tile stays full-quality (JPEG quality=100, no chroma subsampling - see
# portable_ingest.py) since that's what training/export needs. But that same full-size blob was
# getting base64-embedded into the canvas component's args and re-sent over the Streamlit
# WebSocket on *every* rerun - not just tile switches, but every single draw/edit/VI-toggle/etc,
# since Streamlit's custom-component protocol has no way to skip re-transmitting an unchanged
# arg. Over a real network (Streamlit Cloud) that's the difference between a snappy click and a
# noticeable stall; locally it's not felt because localhost round trips are near-instant either
# way. A lower-quality preview cuts that payload by roughly 3x+ with no effect on annotation
# correctness (box coordinates are geometry, not pixels) or on what actually gets exported.
_CANVAS_PREVIEW_QUALITY = 85


def _selected_tile_id(project: SessionProject) -> str | None:
    tile_id = st.session_state.get("annotate_selected_tile_id")
    if tile_id in project.tiles:
        return tile_id
    return None


def _select_tile(tile_id: str) -> None:
    st.session_state["annotate_selected_tile_id"] = tile_id


def _tile_gallery(project: SessionProject) -> None:
    # Lives in the sidebar (see render()) rather than a main-pane column - a narrow one-tile-
    # per-row list keeps its footprint minimal so the main pane can give the canvas nearly its
    # full width, which is the whole point of the drawing surface being here at all.
    status_filter = st.selectbox("Status filter", _STATUS_FILTERS, key="annotate_status_filter")

    tile_ids = list(project.tiles.keys())
    if status_filter != "all":
        tile_ids = [tid for tid in tile_ids if project.annotations[tid].status == status_filter]

    if not tile_ids:
        st.caption("No tiles match this filter.")
        return

    selected = _selected_tile_id(project)
    for tile_id in tile_ids:
        thumb_col, btn_col = st.columns([1, 2])
        thumb_col.image(project.thumbnails[tile_id], width=56)
        label = ("➤ " if tile_id == selected else "") + tile_id
        if btn_col.button(label, key=f"select_tile_{tile_id}", width="stretch"):
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
        horizontal=True,
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


def _tile_preview_data_url(project: SessionProject, tile_id: str) -> str:
    # Cached per (project_id, tile_id) so the recompression only happens once per tile per
    # session, not on every rerun - session-local only, matches the app's session-ephemeral
    # storage (see session_state.clear_project, which evicts this cache too).
    cache = st.session_state.setdefault("_canvas_preview_cache", {})
    cache_key = (project.manifest.project_id, tile_id)
    encoded = cache.get(cache_key)
    if encoded is None:
        img = Image.open(io.BytesIO(project.tiles[tile_id])).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_CANVAS_PREVIEW_QUALITY)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        cache[cache_key] = encoded
    return "data:image/jpeg;base64," + encoded


@st.fragment
def _canvas_fragment(
    project: SessionProject, tile_id: str, selected_class_id: int, vi_mode: bool, vi_threshold: float
) -> None:
    # Every call to obb_canvas() from Python normally triggers a *full app* rerun the instant
    # the component calls back (Streamlit.setComponentValue) - that's automatic, not something
    # our own st.rerun() calls control, and a full rerun dims/freezes the whole page (sidebar
    # gallery, project panel, everything) while it recomputes top to bottom. Fine for an
    # occasional click, bad for something that fires on every single draw/drag/relabel.
    # @st.fragment scopes that down: reruns triggered from inside this function only redraw
    # this function's own output, with no whole-page dimming. Confirm tile (in render(), outside
    # this fragment) still does a normal full rerun on purpose, since it's an occasional action
    # and the sidebar gallery's status badges need to pick up the change.
    tile_annotations = project.annotations[tile_id]
    event = obb_canvas(
        image_url=_tile_preview_data_url(project, tile_id),
        annotations=tile_annotations.annotations,
        classes=project.manifest.classes,
        shape_mode=project.manifest.task_type,
        selected_class_id=selected_class_id,
        vi_mode=vi_mode,
        vi_threshold=vi_threshold,
        height=780,
        key=f"obb_canvas_{tile_id}",
    )

    # Streamlit redelivers the *last* component value on every rerun (triggered by any widget,
    # not just this one) until a genuinely new value is set - dedupe on the per-event nonce so
    # an unrelated rerun (e.g. toggling VI mode) can never reapply a stale
    # "create"/"change"/"delete" and double up an edit.
    nonce_key = f"annotate_last_nonce_{tile_id}"
    if event is not None and event.get("nonce") != st.session_state.get(nonce_key):
        st.session_state[nonce_key] = event["nonce"]
        _apply_event(project, tile_id, event)
        if event["type"] != "select":
            st.rerun(scope="fragment")


def render() -> None:
    project = get_project()
    if project is None or len(project.tiles) == 0:
        st.info("No tiles yet - import a project or tile some images in the Ingest tab first.")
        return

    # The gallery lives in the sidebar (not a main-pane column) specifically so the main pane
    # can dedicate nearly its full width to the canvas - that's the surface people actually
    # spend their time in, the gallery is just tile navigation.
    with st.sidebar:
        st.divider()
        st.subheader("Tiles")
        _tile_gallery(project)

    tile_id = _selected_tile_id(project)
    if tile_id is None:
        st.info("Select a tile from the sidebar gallery to start annotating.")
        return

    top = st.columns([3, 1, 2, 1])
    with top[0]:
        selected_class_id = _class_selector(project)
    with top[1]:
        vi_mode = st.checkbox("VI overlay", key="annotate_vi_mode")
    with top[2]:
        vi_threshold = st.slider(
            "VI threshold", -2.0, 2.0, 0.0, 0.05, key="annotate_vi_threshold", disabled=not vi_mode
        )
    with top[3]:
        if st.button("✓ Confirm tile", key="confirm_tile_btn", width="stretch"):
            for a in project.annotations[tile_id].annotations:
                a.status = "confirmed"
            project.annotations[tile_id].updated_at = datetime.now(timezone.utc)
            st.rerun()

    _canvas_fragment(project, tile_id, selected_class_id, vi_mode, vi_threshold)
