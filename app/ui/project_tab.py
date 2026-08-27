"""Project lifecycle: new/import/export/clear + class editor. Rendered in the sidebar (always
visible) rather than as a third main tab, since the requirement is "Ingest + Annotate only" as
the two screens - project setup is a persistent concern around them, not a third screen."""

from __future__ import annotations

import streamlit as st

from app.manifest import ClassDef, Manifest
from app.portable_export_import import export_zip, import_zip
from app.session_state import SessionProject, clear_project, get_project, set_project

_PALETTE = ["#3DBE5B", "#E0A030", "#4A90D9", "#D9534F", "#9B59B6", "#1ABC9C", "#E67E22", "#F1C40F"]


def _new_project_form() -> None:
    st.subheader("New project")
    name = st.text_input("Project name", value="Untitled project", key="new_project_name")
    task_type = st.selectbox("Task type", ["obb", "detect"], key="new_project_task_type")
    first_class = st.text_input("First class name", value="object", key="new_project_first_class")
    if st.button("Create", key="create_project_btn"):
        manifest = Manifest(
            name=name.strip() or "Untitled project",
            task_type=task_type,  # type: ignore[arg-type]
            classes=[ClassDef(id=0, name=first_class.strip() or "object", color=_PALETTE[0])],
        )
        set_project(SessionProject(manifest=manifest))
        st.rerun()


def _import_form() -> None:
    st.subheader("Import project (.zip)")
    uploaded = st.file_uploader("Project archive", type="zip", key="import_project_zip")
    if uploaded is not None and st.button("Load project", key="load_project_btn"):
        try:
            project = import_zip(uploaded.getvalue())
        except ValueError as exc:
            st.error(str(exc))
        else:
            set_project(project)
            st.success(f"Loaded '{project.manifest.name}' ({len(project.tiles)} tiles).")
            st.rerun()


def _class_editor(project: SessionProject) -> None:
    st.subheader("Classes")
    for cls in project.manifest.classes:
        col1, col2, col3 = st.columns([1, 4, 1])
        new_color = col1.color_picker(
            "Color", value=cls.color, key=f"class_color_{cls.id}", label_visibility="collapsed"
        )
        if new_color != cls.color:
            cls.color = new_color
            st.rerun()
        col2.markdown(cls.name)
        if col3.button("✕", key=f"remove_class_{cls.id}"):
            project.manifest.classes = [c for c in project.manifest.classes if c.id != cls.id]
            st.rerun()
    new_name = st.text_input("New class name", key="new_class_name", label_visibility="collapsed",
                              placeholder="new class name")
    if st.button("+ Add class", key="add_class_btn") and new_name.strip():
        next_id = max([c.id for c in project.manifest.classes], default=-1) + 1
        color = _PALETTE[len(project.manifest.classes) % len(_PALETTE)]
        project.manifest.classes.append(ClassDef(id=next_id, name=new_name.strip(), color=color))
        st.rerun()


def render() -> None:
    project = get_project()

    st.sidebar.title("Project")

    if project is None:
        tab1, tab2 = st.sidebar.tabs(["New", "Import"])
        with tab1:
            _new_project_form()
        with tab2:
            _import_form()
        return

    st.sidebar.markdown(f"**{project.manifest.name}**")
    st.sidebar.caption(f"{project.manifest.task_type} · {len(project.tiles)} tiles")

    _class_editor(project)

    st.sidebar.divider()
    # export_zip() re-zips every tile's full-res JPEG bytes - too expensive to run on every
    # Streamlit rerun (which happens after *every* annotation edit, not just when the user
    # actually wants to export). Only build it when asked, and cache the bytes so re-rendering
    # the download button on subsequent reruns doesn't redo the work; the cache is keyed to
    # project_id so switching/reloading projects can't hand out a stale zip.
    cache_key = "export_zip_cache"
    cached = st.session_state.get(cache_key)
    if st.sidebar.button("⬇️ Prepare export (.zip)", key="prepare_export_btn"):
        st.session_state[cache_key] = (project.manifest.project_id, export_zip(project))
        st.rerun()
    if cached is not None and cached[0] == project.manifest.project_id:
        st.sidebar.download_button(
            "Download project (.zip)",
            data=cached[1],
            file_name=f"{project.manifest.name.replace(' ', '_')}.zip",
            mime="application/zip",
            key="export_project_btn",
        )
    if st.sidebar.button("\U0001f5d1️ Clear session / start over", key="clear_session_btn"):
        clear_project()
        st.rerun()

    st.sidebar.info(
        "Uploaded images and tiles exist only in this session's server-side memory - export "
        "before closing this tab, nothing saves automatically.",
        icon="⚠️",
    )
