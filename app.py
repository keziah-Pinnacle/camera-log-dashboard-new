import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime, timedelta

# ----------------------- PAGE SETTINGS -----------------------
st.set_page_config(page_title="🎥 Real Monitoring Dashboard", layout="wide")

st.markdown("""
    <style>
    body { background-color: #f7faff; color: #1a1a1a; font-family: 'Segoe UI'; }
    .stButton>button { background-color: #0078D4; color: white; border-radius: 8px; font-weight: 600; }
    .stTabs [data-baseweb="tab-list"] { background-color: #eaf2fb; border-radius: 10px; }
    .stTabs [data-baseweb="tab"] { color: #004578; font-weight: 600; }
    .stDataFrame { border: 1px solid #c7d5e0; }
    </style>
""", unsafe_allow_html=True)

# ----------------------- FILE UPLOAD -----------------------
st.title("🎥 Real Monitoring Dashboard")
files = st.file_uploader("Upload Log Files", type=["txt", "log"], accept_multiple_files=True)
if not files:
    st.stop()

# ----------------------- PARSE LOGS -----------------------
def parse_logs(files):
    rows = []
    for file in files:
        for line in file:
            line = line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                parts = line.split("#")
                if len(parts) < 3:
                    continue
                ts_str = parts[0].strip().split(" ")[0] + " " + parts[0].strip().split(" ")[-1]
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                cam_id = parts[1].split(":")[1].split("-")[0].strip()
                event = parts[2].strip()
                battery = None
                if "Battery Level" in line:
                    battery = int(line.split("Battery Level -")[-1].replace("%", "").strip())
                rows.append({"timestamp": ts, "camera": cam_id, "event": event, "battery": battery})
            except Exception:
                continue
    return pd.DataFrame(rows)

df = parse_logs(files)
if df.empty:
    st.error("No valid entries found.")
    st.stop()

# ----------------------- CAMERA SELECTION -----------------------
selected_camera = st.selectbox("Select Camera", sorted(df["camera"].unique()))
df = df[df["camera"] == selected_camera]

# ----------------------- HELPER FUNCTIONS -----------------------
def calc_duration(start, end):
    delta = (end - start).total_seconds() / 60
    if delta < 60:
        return f"{int(delta)} min"
    else:
        h = int(delta // 60)
        m = int(delta % 60)
        return f"{h}h {m}m"

def download_button(df, label):
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    st.download_button(f"📥 {label}", buffer, f"{label}.xlsx", use_container_width=False)

# ----------------------- CHARGING EVENTS -----------------------
charge_pairs = []
for cam, group in df.groupby("camera"):
    start, end, start_bat, end_bat = None, None, None, None
    for _, row in group.iterrows():
        if "Charging" in row["event"] and "Enter" not in row["event"]:
            if start is None:
                start = row["timestamp"]
                start_bat = row["battery"]
            else:
                end = row["timestamp"]
                end_bat = row["battery"]
                charge_pairs.append({
                    "Camera": cam,
                    "Start": start,
                    "End": end,
                    "Start Battery": start_bat,
                    "End Battery": end_bat,
                    "Duration": calc_duration(start, end)
                })
                start = None

charge_df = pd.DataFrame(charge_pairs)

# ----------------------- POWER EVENTS -----------------------
power_pairs = []
for cam, group in df.groupby("camera"):
    start, end, start_bat, end_bat = None, None, None, None
    for _, row in group.iterrows():
        if "Power On" in row["event"]:
            start = row["timestamp"]
            start_bat = row["battery"]
        elif "Power Off" in row["event"] and start:
            end = row["timestamp"]
            end_bat = row["battery"]
            power_pairs.append({
                "Camera": cam,
                "Start": start,
                "End": end,
                "Start Battery": start_bat,
                "End Battery": end_bat,
                "Duration": calc_duration(start, end)
            })
            start = None

power_df = pd.DataFrame(power_pairs)

# ----------------------- RECORDING EVENTS -----------------------
record_pairs = []
for cam, group in df.groupby("camera"):
    start, end, start_bat, end_bat = None, None, None, None
    for _, row in group.iterrows():
        if "Start Recording" in row["event"]:
            start = row["timestamp"]
            start_bat = row["battery"]
        elif "Stop Recording" in row["event"] and start:
            end = row["timestamp"]
            end_bat = row["battery"]
            record_pairs.append({
                "Camera": cam,
                "Start": start,
                "End": end,
                "Start Battery": start_bat,
                "End Battery": end_bat,
                "Duration": calc_duration(start, end)
            })
            start = None

record_df = pd.DataFrame(record_pairs)

# ----------------------- PLOTS -----------------------
tab1, tab2, tab3, tab4 = st.tabs(["⚡ Charging", "🔌 Power", "🎥 Recording", "📊 Summary"])

with tab1:
    st.subheader("⚡ Charging Overview")
    if not charge_df.empty:
        fig = go.Figure()
        for _, row in charge_df.iterrows():
            fig.add_trace(go.Bar(
                x=[row["Start"], row["End"]],
                y=[row["Camera"]]*2,
                orientation='h',
                marker=dict(color="lightgreen", line=dict(color="green", width=2)),
                hovertext=f"<b>Start:</b> {row['Start']}<br><b>End:</b> {row['End']}<br><b>Battery:</b> {row['Start Battery']}%-{row['End Battery']}%<br><b>Duration:</b> {row['Duration']}"
            ))
        fig.update_layout(title="Charging Sessions", xaxis_title="Time", yaxis_title="Camera", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(charge_df[["Camera", "Start", "End", "Duration"]])
        download_button(charge_df, "Charging_Report")

with tab2:
    st.subheader("🔌 Power On/Off Overview")
    if not power_df.empty:
        fig = go.Figure()
        for _, row in power_df.iterrows():
            fig.add_trace(go.Bar(
                x=[row["Start"], row["End"]],
                y=[row["Camera"]]*2,
                orientation='h',
                marker=dict(color="orange", line=dict(color="darkorange", width=2)),
                hovertext=f"<b>On:</b> {row['Start']}<br><b>Off:</b> {row['End']}<br><b>Battery:</b> {row['Start Battery']}%-{row['End Battery']}%<br><b>Duration:</b> {row['Duration']}"
            ))
        fig.update_layout(title="Power Activity", xaxis_title="Time", yaxis_title="Camera", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(power_df[["Camera", "Start", "End", "Duration"]])
        download_button(power_df, "Power_Report")

with tab3:
    st.subheader("🎥 Recording Overview")
    if not record_df.empty:
        fig = go.Figure()
        for _, row in record_df.iterrows():
            fig.add_trace(go.Bar(
                x=[row["Start"], row["End"]],
                y=[row["Camera"]]*2,
                orientation='h',
                marker=dict(color="lightblue", line=dict(color="blue", width=2)),
                hovertext=f"<b>Start:</b> {row['Start']}<br><b>End:</b> {row['End']}<br><b>Battery:</b> {row['Start Battery']}%-{row['End Battery']}%<br><b>Duration:</b> {row['Duration']}"
            ))
        fig.update_layout(title="Recording Sessions", xaxis_title="Time", yaxis_title="Camera", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(record_df[["Camera", "Start", "End", "Duration"]])
        download_button(record_df, "Recording_Report")

with tab4:
    st.subheader("📊 Daily Summary")
    summary = []
    for cam, group in df.groupby("camera"):
        avg_bat = group["battery"].dropna().mean()
        total_chg = charge_df[charge_df["Camera"] == cam].shape[0]
        summary.append({
            "Camera": cam,
            "Total Charging Sessions": total_chg,
            "Average Battery %": round(avg_bat, 1)
        })
    summary_df = pd.DataFrame(summary)
    st.dataframe(summary_df)
    download_button(summary_df, "Daily_Summary")
    for _, row in summary_df.iterrows():
        if row["Average Battery %"] > 90:
            st.success(f"Camera {row['Camera']} battery is healthy and performs well.")
        elif row["Average Battery %"] > 70:
            st.warning(f"Camera {row['Camera']} battery moderate, monitor usage.")
        else:
            st.error(f"Camera {row['Camera']} battery low, consider replacement.")
