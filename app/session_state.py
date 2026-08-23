from __future__ import annotations

from dataclasses import dataclass, field

import streamlit as st

from app.annotations import TileAnnotations
from app.manifest import Manifest

SESSION_KEY = "project"


@dataclass
class SessionProject:
    manifest: Manifest
    tiles: dict[str, bytes] = field(default_factory=dict)  # tile_id -> full-res JPEG bytes
    thumbnails: dict[str, bytes] = field(default_factory=dict)  # tile_id -> thumbnail JPEG bytes
    annotations: dict[str, TileAnnotations] = field(default_factory=dict)


def get_project() -> SessionProject | None:
    return st.session_state.get(SESSION_KEY)


def set_project(project: SessionProject) -> None:
    st.session_state[SESSION_KEY] = project


def clear_project() -> None:
    # Drops every reference to the in-memory tile/thumbnail bytes so they're eligible for GC -
    # this, not any disk cleanup, is what "removed after session" actually means here (see
    # README for the honest caveat about tab-close timing). Also drops the annotate tab's
    # recompressed-preview cache (see ui/annotate_tab.py) - it's keyed by project_id so a new
    # project wouldn't collide with stale entries anyway, but there's no reason to keep them
    # around once their project is gone.
    st.session_state.pop(SESSION_KEY, None)
    st.session_state.pop("_canvas_preview_cache", None)
