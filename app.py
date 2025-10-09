import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime, timedelta

# ----------------------- PAGE SETTINGS -----------------------
st.set_page_config(page_title="Camera Monitoring Dashboard", layout="wide")

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
            line = line.decode("utf-8").strip()
            parts = line.split("#")
            if len(parts) < 4:
                continue
            try:
                ts = parts[0].strip()
                cam_id = parts[1].split(":")[1].strip().split("-")[0]
                event = parts[2].strip()
                bat = [p for p in parts if "Battery Level" in p]
                battery = int(bat[0].split("-")[-1].replace("%", "").strip()) if bat else None
                ts_obj = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                rows.append({"timestamp": ts_obj, "camera": cam_id, "event": event, "battery": battery})
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
    st.download_button(f"📥 Download {label}", buffer, f"{label}.xlsx")

# ----------------------- CHARGE EVENTS -----------------------
charge_events = []
charge_pairs = []
for cam, group in df.groupby("camera"):
    start, end, start_bat, end_bat = None, None, None, None
    for _, row in group.iterrows():
        if "Charging" in row["event"] and "Start" in row["event"]:
            start = row["timestamp"]
            start_bat = row["battery"]
        elif "Charging" in row["event"] and "Stop" in row["event"] and start:
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
                name="Charging",
                marker=dict(color="green", pattern_shape="/"),
                hovertext=f"Start: {row['Start']}<br>End: {row['End']}<br>Battery: {row['Start Battery']}%-{row['End Battery']}%<br>Duration: {row['Duration']}"
            ))
        fig.update_layout(title="Charging Sessions", xaxis_title="Time", yaxis_title="Camera", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(charge_df[["Camera", "Start", "End", "Duration"]])
        download_button(charge_df, "Charging Report")

with tab2:
    st.subheader("🔌 Power On/Off Overview")
    if not power_df.empty:
        fig = go.Figure()
        for _, row in power_df.iterrows():
            fig.add_trace(go.Bar(
                x=[row["Start"], row["End"]],
                y=[row["Camera"]]*2,
                orientation='h',
                name="Power",
                marker=dict(color="orange"),
                hovertext=f"On: {row['Start']}<br>Off: {row['End']}<br>Battery: {row['Start Battery']}%-{row['End Battery']}%<br>Duration: {row['Duration']}"
            ))
        fig.update_layout(title="Power Activity", xaxis_title="Time", yaxis_title="Camera", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(power_df[["Camera", "Start", "End", "Duration"]])
        download_button(power_df, "Power Report")

with tab3:
    st.subheader("🎥 Recording Activity")
    if not record_df.empty:
        fig = go.Figure()
        for _, row in record_df.iterrows():
            fig.add_trace(go.Bar(
                x=[row["Start"], row["End"]],
                y=[row["Camera"]]*2,
                orientation='h',
                name="Recording",
                marker=dict(color="lightgreen"),
                hovertext=f"Start: {row['Start']}<br>End: {row['End']}<br>Battery: {row['Start Battery']}%-{row['End Battery']}%<br>Duration: {row['Duration']}"
            ))
        fig.update_layout(title="Recording Sessions", xaxis_title="Time", yaxis_title="Camera", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(record_df[["Camera", "Start", "End", "Duration"]])
        download_button(record_df, "Recording Report")

with tab4:
    st.subheader("📊 Daily Summary")
    all_summary = []
    for cam, group in df.groupby("camera"):
        total_charge = charge_df[charge_df["Camera"] == cam]["Duration"].count()
        avg_bat = group["battery"].dropna().mean()
        all_summary.append({
            "Camera": cam,
            "Total Charging Sessions": total_charge,
            "Average Battery %": round(avg_bat, 1)
        })
    summary_df = pd.DataFrame(all_summary)
    st.dataframe(summary_df)
    download_button(summary_df, "Daily Summary")
    for _, row in summary_df.iterrows():
        if row["Average Battery %"] > 90:
            st.success(f"Camera {row['Camera']} battery is healthy.")
        elif row["Average Battery %"] > 70:
            st.warning(f"Camera {row['Camera']} battery moderate.")
        else:
            st.error(f"Camera {row['Camera']} battery low, please inspect.")
