import streamlit as st

from app.ui import annotate_tab, ingest_tab, project_tab

st.set_page_config(page_title="YOLO OBB Portable", layout="wide")
st.title("YOLO OBB Portable")
st.caption("Lightweight companion app: ingest + annotate only. Nothing is saved server-side.")

project_tab.render()

ingest_tab_ui, annotate_tab_ui = st.tabs(["Ingest", "Annotate"])

with ingest_tab_ui:
    ingest_tab.render()

with annotate_tab_ui:
    annotate_tab.render()
