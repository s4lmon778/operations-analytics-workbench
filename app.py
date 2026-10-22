"""Local Python/SQL workbench with an embedded interactive data observatory."""
from pathlib import Path
import pandas as pd
import streamlit as st
from pipeline import analyze, sample_data, export, SUMMARY_SQL

st.set_page_config(page_title="Signal / Operations Observatory", page_icon="◉", layout="wide")
st.title("Signal / Operations Observatory")
st.caption("A small experiment in how dirty data changes an operational decision. Synthetic data throughout.")
root = Path(__file__).parent
result = analyze(*sample_data())
if not (root / "docs/index.html").exists():
    export(root)
view, audit, query = st.tabs(["Observatory", "Transformation audit", "SQL and records"])
with view:
    st.iframe(root / "docs/index.html", height=1020, alt="Interactive operations data observatory")
with audit:
    st.json(result["audit"])
    st.json(result["checks"])
    st.dataframe(pd.DataFrame(result["quarantine"]), hide_index=True, width="stretch")
with query:
    region = st.selectbox("Region", ["All", "West", "Central", "East"])
    data = pd.DataFrame(result["accepted"])
    if region != "All":
        data = data[data.region == region]
    st.code(SUMMARY_SQL, language="sql")
    st.dataframe(data, hide_index=True, width="stretch")
    st.download_button("Download filtered accepted records", data.to_csv(index=False), "accepted.csv", "text/csv")
