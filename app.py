"""
Streamlit web UI for the Student Timetable Optimizer.
Run:  streamlit run app.py
"""
import json
import os
import tempfile

import pandas as pd
import streamlit as st

from timetable import TimetableModel, load_data, verify
from timetable.report import export_excel, group_tables, room_tables, teacher_tables

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "data", "sample_input.json")

st.set_page_config(page_title="Timetable Optimizer (IP)", layout="wide")
st.title("🎓 Student Timetable Optimization — Integer Programming")
st.caption("Operations Research project · Binary Integer Programming model solved with PuLP + CBC (branch & bound)")

# ------------------------------------------------------------------ input
with st.sidebar:
    st.header("1. Input data")
    upload = st.file_uploader("Upload JSON (optional)", type="json")
    raw = json.load(upload) if upload else json.load(open(SAMPLE, encoding="utf-8"))
    st.download_button("Download sample JSON", open(SAMPLE, "rb").read(), "sample_input.json")

    st.header("2. Hard-constraint limits")
    s = raw.setdefault("settings", {})
    s["max_periods_per_day_group"] = st.slider("Max periods / day per group", 1, len(raw["periods"]),
                                               s.get("max_periods_per_day_group", 5))
    s["max_same_subject_per_day"] = st.slider("Max lectures of same subject / day", 1, 3,
                                              s.get("max_same_subject_per_day", 1))
    s["time_limit_seconds"] = st.slider("Solver time limit (s)", 5, 300, s.get("time_limit_seconds", 60))

    st.header("3. Objective weights (soft constraints)")
    w = s.setdefault("weights", {})
    w["student_gap"] = st.number_input("Student idle gap", 0, 100, w.get("student_gap", 10))
    w["last_period"] = st.number_input("Class in last period", 0, 100, w.get("last_period", 2))
    w["teacher_avoid"] = st.number_input("Teacher 'avoid' slot used", 0, 100, w.get("teacher_avoid", 5))
    w["daily_balance"] = st.number_input("Heaviest day load", 0, 100, w.get("daily_balance", 3))

try:
    data = load_data(raw)
except Exception as e:  # show input errors nicely
    st.error(f"Input error: {e}")
    st.stop()

with st.expander("📋 Input data", expanded=False):
    c1, c2 = st.columns(2)
    c1.subheader("Courses")
    c1.dataframe(pd.DataFrame([{**vars(c), "teacher": f"{c.teacher} ({data.teachers[c.teacher].name})"}
                               for c in data.courses]), hide_index=True)
    c2.subheader("Rooms")
    c2.dataframe(pd.DataFrame([vars(r) for r in data.rooms.values()]), hide_index=True)
    c2.subheader("Teachers")
    c2.dataframe(pd.DataFrame([{
        "id": t.id, "name": t.name, "max/day": t.max_per_day,
        "unavailable": ", ".join(f"{data.days[d]} P{p + 1}" for d, p in sorted(t.unavailable)),
        "avoid": ", ".join(f"{data.days[d]} P{p + 1}" for d, p in sorted(t.avoid)),
    } for t in data.teachers.values()]), hide_index=True)

# ------------------------------------------------------------------ solve
if st.button("🚀 Generate optimal timetable", type="primary"):
    with st.spinner("Building IP model and running branch & bound ..."):
        model = TimetableModel(data)
        res = model.solve()
    st.session_state["result"] = (data, res)

if "result" in st.session_state:
    data, res = st.session_state["result"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Status", res.status)
    m2.metric("Objective (penalty)", "—" if res.objective is None else f"{res.objective:.0f}")
    m3.metric("Variables / Constraints", f"{res.num_variables} / {res.num_constraints}")
    m4.metric("Solve time", f"{res.solve_seconds:.2f} s")

    if res.objective is None:
        st.error("Infeasible: no timetable satisfies all hard constraints. Relax limits, add rooms or teacher availability.")
        st.stop()

    errs = verify(data, res.sessions)
    if errs:
        st.error("Verification failed:\n" + "\n".join(errs))
    else:
        st.success("Independent verification: every hard constraint is satisfied (no clashes, all hours scheduled).")

    st.subheader("Objective breakdown")
    st.dataframe(pd.DataFrame([{"penalty term": k, "value": v, "weight": data.settings["weights"][k],
                                "weighted": v * data.settings["weights"][k]}
                               for k, v in res.penalty_breakdown.items()]), hide_index=True)

    def show(tables):
        tabs = st.tabs(list(tables))
        for tab, (name, df) in zip(tabs, tables.items()):
            with tab:
                st.dataframe(df.replace(r"\n", " · ", regex=True))

    view = st.radio("View timetable by", ["Student group", "Teacher", "Room"], horizontal=True)
    show({"Student group": group_tables, "Teacher": teacher_tables, "Room": room_tables}[view](data, res.sessions))

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        export_excel(tmp.name, data, res.sessions)
        st.download_button("⬇️ Download Excel timetable", open(tmp.name, "rb").read(), "timetable.xlsx")
