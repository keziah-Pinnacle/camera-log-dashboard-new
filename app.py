import streamlit as st
import pandas as pd
import re
from datetime import datetime
import plotly.graph_objects as go

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("📊 Camera Log Monitoring Dashboard")

# --- Parse logs ---
def parse_logs(uploaded_files):
    rows = []
    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        text = uploaded_file.read().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) #ID:(\d{6}-\d{6}) #(.*?) - Battery Level -\s*(\d+)%", line)
            if m:
                ts, cam, event, bat = m.groups()
                rows.append({
                    "timestamp": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                    "camera": cam,
                    "event": event.strip(),
                    "battery": int(bat),
                    "file": filename
                })
    return pd.DataFrame(rows)

# --- Compress events into start-stop ranges ---
def build_sessions(df, keywords):
    df = df[df["event"].str.contains(keywords, case=False, na=False)].copy()
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values("timestamp")
    sessions = []
    session_start = None
    start_bat = None
    for i, row in df.iterrows():
        if session_start is None:
            session_start = row["timestamp"]
            start_bat = row["battery"]
            last_event = row["event"]
        else:
            if "stop" in row["event"].lower() or "off" in row["event"].lower():
                sessions.append({
                    "date": session_start.date(),
                    "start": session_start,
                    "end": row["timestamp"],
                    "duration_h": (row["timestamp"] - session_start).total_seconds()/3600,
                    "start_bat": start_bat,
                    "end_bat": row["battery"],
                    "event": last_event + " → " + row["event"]
                })
                session_start = None
    return pd.DataFrame(sessions)

# --- Upload logs ---
uploaded_files = st.file_uploader("Upload camera log files (.txt)", type="txt", accept_multiple_files=True)

if uploaded_files:
    df = parse_logs(uploaded_files)
    if df.empty:
        st.error("No valid entries found in the logs.")
    else:
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Filters
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=df["timestamp"].min().date())
        with col2:
            end_date = st.date_input("End Date", value=df["timestamp"].max().date())

        mask = (df["timestamp"].dt.date >= start_date) & (df["timestamp"].dt.date <= end_date)
        df = df[mask]

        selected_cameras = st.multiselect("Select Camera(s)", sorted(df["camera"].unique()), default=list(df["camera"].unique()))
        df = df[df["camera"].isin(selected_cameras)]

        all_dates = pd.date_range(df["timestamp"].dt.date.min(), df["timestamp"].dt.date.max()).strftime("%Y-%m-%d").tolist()

        daily_summary = {}

        # --- 1. Charging Sessions ---
        st.subheader("🔌 Charging Sessions")
        charge_sessions = build_sessions(df, "Charging")
        if not charge_sessions.empty:
            fig1 = go.Figure()
            for i, row in charge_sessions.iterrows():
                fig1.add_trace(go.Bar(
                    x=[row["date"].strftime("%Y-%m-%d")],
                    y=[row["duration_h"]],
                    marker_color="lightblue" if row["end_bat"] > 20 else "darkred",
                    name=row["event"],
                    hovertemplate=(
                        f"<b>Date:</b> {row['date']}<br>"
                        f"<b>Start:</b> {row['start']} ({row['start_bat']}%)<br>"
                        f"<b>Stop:</b> {row['end']} ({row['end_bat']}%)<br>"
                        f"<b>Duration:</b> {row['duration_h']:.2f} hours<extra></extra>"
                    )
                ))
            fig1.update_layout(
                xaxis=dict(title="Date", categoryorder="array", categoryarray=all_dates),
                yaxis=dict(title="Charging Duration (hours)"),
                barmode="stack",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig1, use_container_width=True)

            summary_txt = []
            for d, g in charge_sessions.groupby("date"):
                hrs = g["duration_h"].sum()
                summary_txt.append(f"{d}: charged {hrs:.2f} hours in {len(g)} session(s)")
                daily_summary.setdefault(d, {"charge": 0, "use": 0, "rec": 0})
                daily_summary[d]["charge"] += hrs
            st.write("**Summary:** " + "; ".join(summary_txt))

        # --- 2. Power On/Off ---
        st.subheader("⚡ Power On / Off Status")
        power_sessions = build_sessions(df, "Power")
        if not power_sessions.empty:
            fig2 = go.Figure()
            for i, row in power_sessions.iterrows():
                fig2.add_trace(go.Bar(
                    x=[row["date"].strftime("%Y-%m-%d")],
                    y=[row["duration_h"]],
                    marker_color="lightgreen" if "On" in row["event"] else "orange",
                    name=row["event"],
                    hovertemplate=(
                        f"<b>Date:</b> {row['date']}<br>"
                        f"<b>Power On:</b> {row['start']} ({row['start_bat']}%)<br>"
                        f"<b>Power Off:</b> {row['end']} ({row['end_bat']}%)<br>"
                        f"<b>Duration:</b> {row['duration_h']:.2f} hours<extra></extra>"
                    )
                ))
            fig2.update_layout(
                xaxis=dict(title="Date", categoryorder="array", categoryarray=all_dates),
                yaxis=dict(title="Usage Duration (hours)"),
                barmode="stack",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig2, use_container_width=True)

            summary_txt = []
            for d, g in power_sessions.groupby("date"):
                hrs = g["duration_h"].sum()
                summary_txt.append(f"{d}: powered on {hrs:.2f} hours in {len(g)} session(s)")
                daily_summary.setdefault(d, {"charge": 0, "use": 0, "rec": 0})
                daily_summary[d]["use"] += hrs
            st.write("**Summary:** " + "; ".join(summary_txt))

        # --- 3. Recording Sessions ---
        st.subheader("🎥 Recording / Pre-Recording")
        rec_sessions = build_sessions(df, "Record")
        if not rec_sessions.empty:
            fig3 = go.Figure()
            for i, row in rec_sessions.iterrows():
                fig3.add_trace(go.Bar(
                    x=[row["date"].strftime("%Y-%m-%d")],
                    y=[row["duration_h"]],
                    marker_color="lightcoral" if "Start" in row["event"] else "lightsalmon",
                    name=row["event"],
                    hovertemplate=(
                        f"<b>Date:</b> {row['date']}<br>"
                        f"<b>Start:</b> {row['start']} ({row['start_bat']}%)<br>"
                        f"<b>Stop:</b> {row['end']} ({row['end_bat']}%)<br>"
                        f"<b>Duration:</b> {row['duration_h']:.2f} hours<extra></extra>"
                    )
                ))
            fig3.update_layout(
                xaxis=dict(title="Date", categoryorder="array", categoryarray=all_dates),
                yaxis=dict(title="Recording Duration (hours)"),
                barmode="stack",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig3, use_container_width=True)

            summary_txt = []
            for d, g in rec_sessions.groupby("date"):
                hrs = g["duration_h"].sum()
                summary_txt.append(f"{d}: recorded {hrs:.2f} hours in {len(g)} session(s)")
                daily_summary.setdefault(d, {"charge": 0, "use": 0, "rec": 0})
                daily_summary[d]["rec"] += hrs
            st.write("**Summary:** " + "; ".join(summary_txt))

        # --- Low Battery Alerts ---
        low_battery = df[df["battery"] < 20]
        if not low_battery.empty:
            st.subheader(⚠️ Low Battery Alerts (<20%)")
            st.dataframe(low_battery[["timestamp", "camera", "event", "battery"]])

        # --- Daily Summary Table ---
        if daily_summary:
            st.subheader("📅 Daily Summary (Auto-Generated)")
            summary_df = pd.DataFrame([
                {"Date": d, 
                 "Total Charging (h)": v["charge"], 
                 "Total Usage (h)": v["use"], 
                 "Total Recording (h)": v["rec"]}
                for d, v in daily_summary.items()
            ])
            st.dataframe(summary_df, use_container_width=True)

        # --- Compressed Event Table (Non-technical names) ---
        st.subheader("📋 Event Table (Compressed)")
        compressed = df.copy()
        compressed["event"] = compressed["event"].replace({
            "Power On": "Powered On",
            "Power Off": "Powered Off",
            "Start Record": "Recording Started",
            "Stop Record": "Recording Stopped",
            "Battery Charging": "Charging",
            "Pre-Record": "Pre-Recording"
        }, regex=True)
        st.dataframe(compressed[["timestamp","camera","event","battery"]], use_container_width=True)

else:
    st.info("Upload one or more log files to get started.")
