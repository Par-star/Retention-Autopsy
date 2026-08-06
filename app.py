"""
app.py — Retention Autopsy
---------------------------
Streamlit app: upload a YouTube Studio retention export + a transcript,
and get an AI-generated "autopsy report" explaining WHY viewers dropped
off at each steep point in the curve, with concrete edit suggestions.

Run:
    streamlit run app.py
"""

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # reads GROQ_API_KEY from a local .env file, if present

from retention_core import (
    detect_drop_zones,
    diagnose_zone,
    parse_retention_csv,
    parse_transcript,
)

st.set_page_config(page_title="Retention Autopsy", page_icon="🔎", layout="wide")

st.title("🔎 Retention Autopsy")
st.caption(
    "Upload your YouTube Studio audience-retention export + transcript. "
    "Get a plain-English diagnosis of *why* viewers dropped off — not just where."
)

with st.sidebar:
    st.header("Setup")
    api_key = st.text_input(
        "Groq API key (optional)",
        value=os.environ.get("GROQ_API_KEY", ""),
        type="password",
        help="Auto-filled from your local .env file if GROQ_API_KEY is set there. "
             "Without a key, the tool falls back to a rule-based heuristic diagnosis "
             "so it still works offline.",
    )
    duration_sec = st.number_input(
        "Video duration (seconds)",
        min_value=10,
        value=600,
        step=10,
        help="Used to convert the retention curve's % position into timestamps.",
    )
    min_drop = st.slider(
        "Sensitivity: min drop (percentage points) to flag",
        min_value=1.0, max_value=15.0, value=4.0, step=0.5,
    )
    st.divider()
    use_demo = st.button("▶ Load demo data (no files needed)", use_container_width=True)

st.subheader("1. Inputs")
col1, col2 = st.columns(2)

demo_dir = os.path.join(os.path.dirname(__file__), "sample_data")

with col1:
    retention_file = st.file_uploader(
        "Retention CSV (YouTube Studio export)", type=["csv"], key="retention_csv"
    )
with col2:
    transcript_file = st.file_uploader(
        "Transcript (.txt, timestamped)", type=["txt"], key="transcript_txt"
    )
    transcript_paste = st.text_area(
        "...or paste transcript directly",
        height=120,
        placeholder="[0] Hey everyone, welcome back...\n[12] Today we're talking about...",
    )

retention_df = None
transcript_raw = None

if use_demo:
    retention_path = os.path.join(demo_dir, "demo_retention.csv")
    transcript_path = os.path.join(demo_dir, "demo_transcript.txt")
    if os.path.exists(retention_path) and os.path.exists(transcript_path):
        retention_df = parse_retention_csv(retention_path)
        with open(transcript_path) as f:
            transcript_raw = f.read()
        st.success("Loaded synthetic demo data.")
    else:
        st.error("Demo data not found — run `python demo_data.py` first to generate it.")
elif retention_file is not None:
    retention_df = parse_retention_csv(retention_file)
    if transcript_file is not None:
        transcript_raw = transcript_file.read().decode("utf-8")
    elif transcript_paste.strip():
        transcript_raw = transcript_paste

if retention_df is not None and transcript_raw:
    st.subheader("2. Retention Curve")

    zones = detect_drop_zones(retention_df, duration_sec=duration_sec, min_drop_points=min_drop)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=retention_df["position_pct"], y=retention_df["retention_pct"],
        mode="lines", name="Retention", line=dict(color="#3b82f6", width=2),
    ))
    for z in zones:
        fig.add_vrect(
            x0=z.start_pct, x1=z.end_pct,
            fillcolor="red", opacity=0.15, line_width=0,
        )
    fig.update_layout(
        xaxis_title="Video position (%)",
        yaxis_title="Audience retention (%)",
        height=400,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    if not zones:
        st.info("No steep drop zones detected at this sensitivity — try lowering the threshold in the sidebar.")
    else:
        st.subheader(f"3. Autopsy Report — {len(zones)} drop zone(s) flagged")
        segments = parse_transcript(transcript_raw)

        for idx, z in enumerate(zones, start=1):
            with st.spinner(f"Diagnosing drop {idx}/{len(zones)}..."):
                diag = diagnose_zone(z, segments, api_key=api_key, use_llm=True)

            m0, m1 = divmod(int(z.start_sec), 60)
            m2, m3 = divmod(int(z.end_sec), 60)
            st.markdown(f"### 🩹 Drop {idx}: {m0}:{m1:02d} → {m2}:{m3:02d}  "
                        f"(−{z.drop_amount:.1f} pts, {z.retention_before:.1f}% → {z.retention_after:.1f}%)")
            c1, c2 = st.columns([1, 2])
            with c1:
                st.metric("Category", diag["category"].replace("_", " ").title())
            with c2:
                st.write(f"**Why:** {diag['explanation']}")
                st.write(f"**Suggested fix:** {diag['suggested_fix']}")
            with st.expander("Transcript snippet used"):
                st.write(diag.get("transcript_snippet", "(none)"))
            st.divider()
else:
    st.info("Upload both a retention CSV and a transcript (or click **Load demo data** in the sidebar) to run an autopsy.")

st.divider()
st.caption(
    "Retention CSVs come from YouTube Studio → Analytics → Engagement → Audience retention → Export. "
    "This tool doesn't call the YouTube API — it works entirely from files you already have."
)