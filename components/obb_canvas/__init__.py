"""Streamlit custom component wrapping the ported Konva OBB drawing canvas.

Streamlit Community Cloud never runs `npm install`/`npm run build` - the prebuilt
`frontend/build/` directory below must be committed to git and kept in sync with
`frontend/src/` manually (there's no shared package between this repo and the private
full app this canvas was ported from).
"""

from __future__ import annotations

import os
from typing import Any

import streamlit.components.v1 as components

from app.annotations import Annotation
from app.manifest import ClassDef

_RELEASE = True

if _RELEASE:
    _build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
    _component_func = components.declare_component("obb_canvas", path=_build_dir)
else:
    # `npm run dev` in components/obb_canvas/frontend, then flip _RELEASE above.
    _component_func = components.declare_component("obb_canvas", url="http://localhost:5173")


def obb_canvas(
    *,
    image_url: str,
    annotations: list[Annotation],
    classes: list[ClassDef],
    shape_mode: str,
    selected_class_id: int,
    vi_mode: bool = False,
    vi_threshold: float = 0.0,
    height: int = 640,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Renders the drawing canvas for one tile and returns the latest bridge event.

    The returned dict is one of {"type": "create"|"change"|"select"|"delete", "nonce": ..., ...}
    (see components/obb_canvas/frontend/src/main.tsx for the exact per-type shape), or None
    before any interaction has happened yet. Streamlit redelivers the *last* value on every
    rerun until a new one is set - callers must dedupe on "nonce" rather than reacting to every
    non-None return.
    """
    return _component_func(
        image_url=image_url,
        annotations=[a.model_dump(mode="json") for a in annotations],
        classes=[c.model_dump(mode="json") for c in classes],
        shape_mode=shape_mode,
        selected_class_id=selected_class_id,
        vi_mode=vi_mode,
        vi_threshold=vi_threshold,
        height=height,
        key=key,
        default=None,
    )
