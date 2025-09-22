import streamlit as st
import pandas as pd
import re
from datetime import datetime
import plotly.graph_objects as go

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("📊 Camera Log Monitoring Dashboard")

# --- Helper: Parse logs ---
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

        # --- 1. Charging Graph ---
        st.subheader("🔌 Charging Sessions")
        charging_df = df[df["event"].str.contains("Battery Charging", case=False, na=False)].copy()
        if not charging_df.empty:
            charging_df["date"] = charging_df["timestamp"].dt.date
            charging_df["time"] = charging_df["timestamp"].dt.strftime("%H:%M:%S")
            charging_df = charging_df.sort_values("timestamp")

            # Group into charging sessions (gap > 10 min = new session)
            charging_df["session"] = (charging_df["timestamp"].diff().dt.total_seconds() > 600).cumsum()

            fig1 = go.Figure()
            for session, g in charging_df.groupby("session"):
                fig1.add_trace(go.Scatter(
                    x=g["timestamp"],
                    y=g["battery"],
                    mode="lines+markers",
                    line=dict(color="blue"),
                    name=f"Session {session}",
                    hovertemplate=(
                        "<b>Time:</b> %{x}<br>"
                        "<b>Battery Level:</b> %{y}%<extra></extra>"
                    )
                ))

            fig1.update_layout(
                xaxis_title="Date & Time",
                yaxis_title="Battery % (Charging)",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig1, use_container_width=True)
            st.write("**Summary:** This chart shows when the cameras were put on charge and removed from charge. "
                     "Each line represents one charging session. Hover to see exact time and battery %. "
                     "Short sessions (for example 1 hour only) can be spotted here.")

        # --- 2. Power On/Off Graph ---
        st.subheader("⚡ Power On / Off Timeline")
        power_df = df[df["event"].str.contains("Power On|Power Off", case=False, na=False)].copy()
        if not power_df.empty:
            power_df["date"] = power_df["timestamp"].dt.date
            power_df["time"] = power_df["timestamp"].dt.strftime("%H:%M:%S")
            power_df["type"] = power_df["event"].apply(lambda x: "Power On" if "Power On" in x else "Power Off")

            fig2 = go.Figure()
            for typ, g in power_df.groupby("type"):
                fig2.add_trace(go.Scatter(
                    x=g["timestamp"],
                    y=g["battery"],
                    mode="markers+lines",
                    marker=dict(size=10, color="green" if typ == "Power On" else "red"),
                    name=typ,
                    hovertemplate=(
                        "<b>Event:</b> " + typ + "<br>"
                        "<b>Time:</b> %{x}<br>"
                        "<b>Battery Level:</b> %{y}%<extra></extra>"
                    )
                ))

            fig2.update_layout(
                xaxis_title="Date & Time",
                yaxis_title="Battery % at Power On/Off",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig2, use_container_width=True)
            st.write("**Summary:** This graph shows when the cameras were powered on (green) and powered off (red). "
                     "By comparing with charging sessions, you can see how long the camera stayed on and what the battery level was during operation.")

        # --- 3. Recording Graph ---
        st.subheader("🎥 Recording / Pre-Recording Timeline")
        rec_df = df[df["event"].str.contains("Record|Pre-Record", case=False, na=False)].copy()
        if not rec_df.empty:
            rec_df["date"] = rec_df["timestamp"].dt.date
            rec_df["time"] = rec_df["timestamp"].dt.strftime("%H:%M:%S")
            rec_df["type"] = rec_df["event"].apply(
                lambda x: "Pre-Record" if "Pre-Record" in x else "Recording"
            )

            fig3 = go.Figure()
            for typ, g in rec_df.groupby("type"):
                fig3.add_trace(go.Scatter(
                    x=g["timestamp"],
                    y=g["battery"],
                    mode="markers+lines",
                    marker=dict(size=10, color="blue" if typ == "Recording" else "orange"),
                    name=typ,
                    hovertemplate=(
                        "<b>Event:</b> " + typ + "<br>"
                        "<b>Time:</b> %{x}<br>"
                        "<b>Battery Level:</b> %{y}%<extra></extra>"
                    )
                ))

            fig3.update_layout(
                xaxis_title="Date & Time",
                yaxis_title="Battery % during Recording",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig3, use_container_width=True)
            st.write("**Summary:** This graph shows when the cameras started and stopped recording or pre-recording. "
                     "You can see how long recordings lasted and how the battery drained during use.")

        # --- Event Table at bottom ---
        st.subheader("📋 Full Event Table")
        st.dataframe(df, use_container_width=True)

else:
    st.info("Upload one or more log files to get started.")
