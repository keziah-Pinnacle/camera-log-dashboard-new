# app.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime
import plotly.graph_objects as go
from io import BytesIO
import traceback

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.markdown("<h1 style='color:#1f77b4;'>📹 Camera Log Monitoring Dashboard</h1>", unsafe_allow_html=True)

# ------ Config ------
EVENT_NORMALIZE = {
    "Battery Charging": "Start Charge",
    "Battery Charge Stop": "Stop Charge",
    "System Power On": "Power On",
    "System Power Off": "Power Off",
    "Start Record": "Start Record",
    "Stop Record": "Stop Record",
    "Start Pre Record": "Start PreRecord",
    "Stop PreRecord": "Stop PreRecord",
    "Stop Pre Record": "Stop PreRecord",  # some logs use space
}
# Colors tuned to be light + clear; start vs stop marker colors differ for clarity
EVENT_COLORS = {
    "Start Charge": "#4A90E2",       # blue
    "Stop Charge": "#1ABC9C",        # teal
    "Power On": "#2ECC71",           # green
    "Power Off": "#E74C3C",          # red
    "Start Record": "#90EE90",       # light green
    "Stop Record": "#FF7F7F",        # light red
    "Start PreRecord": "#87CEFA",    # light blue
    "Stop PreRecord": "#00008B",     # dark blue
}
def human_event(raw):
    for k in EVENT_NORMALIZE:
        if k.lower() in raw.lower():
            return EVENT_NORMALIZE[k]
    return raw.strip()

# ------ Parsing ------
def parse_logs(files):
    """
    Parse uploaded log files. Returns DataFrame with timestamp, camera, event, battery.
    Camera is shortened to first segment before '-' like 007446 (we keep that).
    """
    pat = re.compile(
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+#ID:([0-9A-Za-z\-]+)\s+#(.*?)\s*(?:-.*Battery Level\s*-\s*(\d+)%\s*)?$"
    )
    rows = []
    for f in files:
        text = f.read().decode("utf-8", errors="ignore")
        for ln in text.splitlines():
            m = pat.search(ln.strip())
            if not m:
                continue
            ts_s, cam_raw, ev_raw, bat = m.groups()
            try:
                ts = datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S")
            except Exception:
                # skip unparsable timestamps
                continue
            cam_short = cam_raw.split("-")[0]
            rows.append({
                "timestamp": ts,
                "camera": cam_short,
                "event": human_event(ev_raw),
                "battery": int(bat) if bat else None,
                "raw_line": ln.strip()
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["camera", "timestamp"]).reset_index(drop=True)
    return df

# compress sequential identical events into start/end sessions (per camera)
def compress_sessions(df):
    out = []
    if df.empty:
        return pd.DataFrame(columns=["Camera","Event","Start","End","StartBat","EndBat","Duration_h","Date"])
    for cam, g in df.groupby("camera"):
        g = g.reset_index(drop=True)
        cur_event = None
        cur_start = None
        cur_start_bat = None
        for idx, row in g.iterrows():
            if cur_event is None:
                cur_event = row["event"]
                cur_start = row["timestamp"]
                cur_start_bat = row["battery"]
                last_ts = row["timestamp"]
                last_bat = row["battery"]
                continue
            # If same event, extend
            if row["event"] == cur_event:
                last_ts = row["timestamp"]
                last_bat = row["battery"]
                continue
            # event changed -> close previous session
            out.append([cam, cur_event, cur_start, last_ts, cur_start_bat, last_bat])
            # start new
            cur_event = row["event"]
            cur_start = row["timestamp"]
            cur_start_bat = row["battery"]
            last_ts = row["timestamp"]
            last_bat = row["battery"]
        # close final open
        if cur_event is not None:
            out.append([cam, cur_event, cur_start, last_ts, cur_start_bat, last_bat])
    df2 = pd.DataFrame(out, columns=["Camera","Event","Start","End","StartBat","EndBat"])
    if not df2.empty:
        df2["Duration_h"] = (df2["End"] - df2["Start"]).dt.total_seconds() / 3600.0
        df2["Date"] = df2["Start"].dt.date
    else:
        df2["Duration_h"] = []
        df2["Date"] = []
    return df2

def fmt_duration(hours):
    mins = int(round(hours * 60))
    if mins < 60:
        return f"{mins}m"
    return f"{mins//60}h {mins%60}m"

def download_csv_xlsx(df, name, key_suffix):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇ {name} CSV", csv, f"{name}.csv", key=f"{name}_csv_{key_suffix}", help=f"Download {name} as CSV")
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=name[:31])
    st.download_button(f"⬇ {name} Excel", buf.getvalue(), f"{name}.xlsx", key=f"{name}_xls_{key_suffix}", help=f"Download {name} as Excel")

# ------ UI: sidebar controls ------
st.sidebar.header("Upload & Filters")
files = st.sidebar.file_uploader("Upload log files (.txt/.log)", type=["txt","log"], accept_multiple_files=True)
if not files:
    st.sidebar.info("Upload one or more log files to start.")
    st.stop()

try:
    df_raw = parse_logs(files)
except Exception as e:
    st.error("Failed to parse uploaded files. See traceback below.")
    st.text(traceback.format_exc())
    st.stop()

if df_raw.empty:
    st.error("No valid log entries were parsed from uploaded files.")
    st.stop()

sessions = compress_sessions(df_raw)

# date pickers
min_date = df_raw["timestamp"].min().date()
max_date = df_raw["timestamp"].max().date()
date_range = st.sidebar.date_input("Select date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
# ensure start/end always defined (fixes NameError)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

# cameras select
all_cams = sorted(df_raw["camera"].unique().tolist())
selected_cams = st.sidebar.multiselect("Select camera(s)", options=all_cams, default=all_cams)

# filter sessions according to selection
sessions = sessions[sessions["Camera"].isin(selected_cams)]
if not sessions.empty:
    sessions = sessions[(sessions["Start"].dt.date >= start_date) & (sessions["Start"].dt.date <= end_date)]

# ------ Layout (tabs) ------
tabs = st.tabs(["Overview", "Charging", "Power", "Recording", "Daily Summary"])

# ===== Overview =====
with tabs[0]:
    st.subheader("Overview")
    c1, c2, c3 = st.columns(3)
    c1.metric("Cameras in view", len(selected_cams))
    c2.metric("Date range", f"{start_date} → {end_date}")
    c3.metric("Total sessions", len(sessions))
    st.markdown("**Notes:** horizontal bars show a session's start -> end time. Hover to see exact start, end, duration and battery.")

# Helper to draw horizontal session lines per camera
def draw_horizontal_sessions(df_sessions, filter_event_substr, title, key):
    """
    df_sessions: DataFrame with Camera, Event, Start, End, Duration_h, StartBat, EndBat
    filter_event_substr: substring to filter sessions (like 'Charge' or 'Power' or 'Record')
    key: unique key used for Streamlit components
    """
    sel = df_sessions[df_sessions["Event"].str.contains(filter_event_substr, na=False)].copy()
    if sel.empty:
        st.info(f"No {title} sessions found for selected cameras / date range.")
        return None, sel

    # build mapping camera -> y index for categorical y axis (so each camera gets its own row)
    cameras = sorted(sel["Camera"].unique().tolist())
    cam_to_y = {cam: i for i, cam in enumerate(cameras)}

    fig = go.Figure()
    # For legend dedup
    legend_shown = set()
    for _, row in sel.iterrows():
        cam = row["Camera"]
        y = cam_to_y[cam]
        start = row["Start"]
        end = row["End"]
        dur_h = row.get("Duration_h", 0.0)
        event = row["Event"]
        color = EVENT_COLORS.get(event, "#888888")
        # horizontal line from start to end (two points)
        fig.add_trace(go.Scatter(
            x=[start, end],
            y=[y, y],
            mode="lines+markers",
            line=dict(color=color, width=8),
            marker=dict(size=8, symbol="circle"),
            name=event if event not in legend_shown else None,
            hovertemplate=(
                "<b>Camera</b>: %{text}<br>"
                "<b>Event</b>: " + event + "<br>"
                "<b>Start</b>: %{x|%Y-%m-%d %H:%M:%S}<br>"
                "<b>End</b>: %{customdata[0]|%Y-%m-%d %H:%M:%S}<br>"
                "<b>Duration</b>: %{customdata[1]}<br>"
                "<b>Battery</b>: %{customdata[2]}%"
                "<extra></extra>"
            ),
            text=[cam, cam],
            customdata=[[end, fmt_duration(dur_h), (row["EndBat"] if pd.notna(row["EndBat"]) else "")],
                        [end, fmt_duration(dur_h), (row["EndBat"] if pd.notna(row["EndBat"]) else "")]]
        ))
        legend_shown.add(event)

    fig.update_layout(
        template="plotly_white",
        height=350 + 30 * len(cameras),
        yaxis=dict(
            tickmode="array",
            tickvals=list(cam_to_y.values()),
            ticktext=list(cam_to_y.keys()),
            title="Camera"
        ),
        xaxis=dict(title="Time (start → end)"),
        margin=dict(l=80, r=20, t=40, b=80),
        showlegend=True
    )

    st.plotly_chart(fig, use_container_width=True, key=f"plot_{key}")

    # summary table: one line per session (Start, End, Duration, Camera, StartBat, EndBat)
    summary = sel.copy()
    summary["Duration"] = summary["Duration_h"].apply(fmt_duration)
    summary = summary[["Camera", "Event", "Start", "End", "Duration", "StartBat", "EndBat"]].sort_values(["Camera", "Start"])
    st.dataframe(summary, key=f"table_{key}")
    download_csv_xlsx(summary, f"{title}_Summary", key)
    return fig, summary

# ===== Charging Tab =====
with tabs[1]:
    st.subheader("Charging (start → stop)")
    try:
        ch_fig, ch_summary = draw_horizontal_sessions(sessions, "Charge", "Charging", "charging")
    except Exception:
        st.error("Error rendering Charging chart.")
        st.text(traceback.format_exc())

# ===== Power Tab =====
with tabs[2]:
    st.subheader("Power On / Off (start → stop)")
    try:
        p_fig, p_summary = draw_horizontal_sessions(sessions, "Power", "Power", "power")
    except Exception:
        st.error("Error rendering Power chart.")
        st.text(traceback.format_exc())

# ===== Recording Tab =====
with tabs[3]:
    st.subheader("Recording / PreRecord (start → stop)")
    try:
        r_fig, r_summary = draw_horizontal_sessions(sessions, "Record", "Recording", "recording")
    except Exception:
        st.error("Error rendering Recording chart.")
        st.text(traceback.format_exc())

# ===== Daily Summary (last) =====
with tabs[4]:
    st.subheader("Daily Summary (last)")
    if sessions.empty:
        st.info("No session data to summarize.")
    else:
        daily = sessions.groupby(["Camera", "Date"]).apply(lambda g: pd.Series({
            "Charging_h": g.loc[g["Event"].str.contains("Charge", na=False), "Duration_h"].sum(),
            "Power_h": g.loc[g["Event"].str.contains("Power", na=False), "Duration_h"].sum(),
            "Record_h": g.loc[g["Event"].str.contains("Record", na=False), "Duration_h"].sum()
        })).reset_index()
        daily["Charging"] = daily["Charging_h"].apply(fmt_duration)
        daily["Power"] = daily["Power_h"].apply(fmt_duration)
        daily["Record"] = daily["Record_h"].apply(fmt_duration)
        st.dataframe(daily[["Camera", "Date", "Charging", "Power", "Record"]], use_container_width=True, key="daily_table")
        download_csv_xlsx(daily[["Camera", "Date", "Charging", "Power", "Record"]], "DailySummary", "daily")
