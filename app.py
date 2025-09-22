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

# --- Compress events (time ranges) ---
def compress_events(df):
    if df.empty:
        return df
    df = df.sort_values("timestamp").reset_index(drop=True)
    compressed = []
    start_row = df.iloc[0]
    start_time = start_row["timestamp"]
    end_time = start_time
    start_event = start_row["event"]
    start_bat = start_row["battery"]

    for i in range(1, len(df)):
        row = df.iloc[i]
        if row["event"] == start_event and row["camera"] == start_row["camera"]:
            end_time = row["timestamp"]
        else:
            compressed.append({
                "Camera": start_row["camera"],
                "Event": start_event,
                "StartTime": start_time,
                "EndTime": end_time,
                "BatteryRange": f"{start_bat}% → {row['battery']}%",
            })
            start_row = row
            start_event = row["event"]
            start_time = row["timestamp"]
            end_time = row["timestamp"]
            start_bat = row["battery"]

    compressed.append({
        "Camera": start_row["camera"],
        "Event": start_event,
        "StartTime": start_time,
        "EndTime": end_time,
        "BatteryRange": f"{start_bat}%" if start_time == end_time else f"{start_bat}% → {row['battery']}%",
    })
    return pd.DataFrame(compressed)

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

        # Ensure all dates appear on x-axis
        all_dates = pd.date_range(df["timestamp"].dt.date.min(), df["timestamp"].dt.date.max()).strftime("%Y-%m-%d").tolist()

        # --- 1. Charging Sessions ---
        st.subheader("🔌 Charging Sessions")
        charging_df = df[df["event"].str.contains("Charging", case=False, na=False)]
        if not charging_df.empty:
            charging_df["date"] = charging_df["timestamp"].dt.strftime("%Y-%m-%d")
            charging_df["time"] = charging_df["timestamp"].dt.strftime("%H:%M:%S")

            fig1 = go.Figure()
            for date, g in charging_df.groupby("date"):
                g = g.sort_values("timestamp")
                if len(g) > 1:
                    start = g.iloc[0]
                    end = g.iloc[-1]
                    fig1.add_trace(go.Bar(
                        x=[date],
                        y=[(end["timestamp"] - start["timestamp"]).total_seconds()/3600],
                        name="Charging",
                        marker_color="lightblue",
                        hovertemplate=(
                            f"<b>Date:</b> {date}<br>"
                            f"<b>Start:</b> {start['time']} ({start['battery']}%)<br>"
                            f"<b>Stop:</b> {end['time']} ({end['battery']}%)<br>"
                            f"<b>Duration:</b> {{y:.2f}} hours<extra></extra>"
                        )
                    ))
            fig1.update_layout(
                xaxis=dict(title="Date", categoryorder="array", categoryarray=all_dates),
                yaxis=dict(title="Charging Duration (hours)"),
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig1, use_container_width=True)
            st.write("**Summary:** Shows when charging started and stopped. Bars represent total charging hours per day.")

        # --- 2. Power On/Off ---
        st.subheader("⚡ Power On / Off Status")
        power_df = df[df["event"].str.contains("Power On|Power Off", case=False, na=False)]
        if not power_df.empty:
            power_df["date"] = power_df["timestamp"].dt.strftime("%Y-%m-%d")

            fig2 = go.Figure()
            for date, g in power_df.groupby("date"):
                g = g.sort_values("timestamp")
                if len(g) > 1:
                    start = g.iloc[0]
                    end = g.iloc[-1]
                    fig2.add_trace(go.Bar(
                        x=[date],
                        y=[(end["timestamp"] - start["timestamp"]).total_seconds()/3600],
                        name="Power On",
                        marker_color="lightgreen",
                        hovertemplate=(
                            f"<b>Date:</b> {date}<br>"
                            f"<b>Power On:</b> {start['timestamp']} ({start['battery']}%)<br>"
                            f"<b>Power Off:</b> {end['timestamp']} ({end['battery']}%)<br>"
                            f"<b>Duration:</b> {{y:.2f}} hours<extra></extra>"
                        )
                    ))
            fig2.update_layout(
                xaxis=dict(title="Date", categoryorder="array", categoryarray=all_dates),
                yaxis=dict(title="Usage Duration (hours)"),
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig2, use_container_width=True)
            st.write("**Summary:** Shows how long the camera was powered on each day.")

        # --- 3. Recording Sessions ---
        st.subheader("🎥 Recording / Pre-Recording")
        rec_df = df[df["event"].str.contains("Record", case=False, na=False)]
        if not rec_df.empty:
            rec_df["date"] = rec_df["timestamp"].dt.strftime("%Y-%m-%d")

            fig3 = go.Figure()
            for date, g in rec_df.groupby("date"):
                g = g.sort_values("timestamp")
                if len(g) > 1:
                    start = g.iloc[0]
                    end = g.iloc[-1]
                    fig3.add_trace(go.Bar(
                        x=[date],
                        y=[(end["timestamp"] - start["timestamp"]).total_seconds()/3600],
                        name="Recording",
                        marker_color="lightcoral",
                        hovertemplate=(
                            f"<b>Date:</b> {date}<br>"
                            f"<b>Start:</b> {start['timestamp']} ({start['battery']}%)<br>"
                            f"<b>Stop:</b> {end['timestamp']} ({end['battery']}%)<br>"
                            f"<b>Duration:</b> {{y:.2f}} hours<extra></extra>"
                        )
                    ))
            fig3.update_layout(
                xaxis=dict(title="Date", categoryorder="array", categoryarray=all_dates),
                yaxis=dict(title="Recording Duration (hours)"),
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig3, use_container_width=True)
            st.write("**Summary:** Shows how long the camera recorded per day, with start and stop battery levels.")

        # --- Low Battery Alerts ---
        low_battery = df[df["battery"] < 20]
        if not low_battery.empty:
            st.subheader("⚠️ Low Battery Alerts (<20%)")
            st.dataframe(low_battery[["timestamp", "camera", "event", "battery"]])

        # --- Compressed Event Table ---
        st.subheader("📋 Event Table (Compressed)")
        st.dataframe(compress_events(df), use_container_width=True)

else:
    st.info("Upload one or more log files to get started.")
