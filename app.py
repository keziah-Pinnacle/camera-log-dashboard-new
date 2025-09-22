# app.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime, time
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("Camera Log Monitoring Dashboard")

# --------------------------
# Utilities
# --------------------------
TIME_GAP_SECONDS = 600  # 10 minutes: gap threshold to split charging sessions

def parse_logs(uploaded_files):
    """Parse uploaded .txt/.log files into DataFrame with timestamp,camera,event,battery,file."""
    rows = []
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+#ID:(\d{6}-\d{6})\s+#(.*?)\s*-.*Battery Level\s*-\s*(\d+)%", re.IGNORECASE)
    for uploaded in uploaded_files:
        filename = uploaded.name
        raw = uploaded.read().decode("utf-8", errors="ignore")
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            m = pattern.search(line)
            if m:
                ts_s, cam, event, bat = m.groups()
                try:
                    ts = datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                rows.append({
                    "timestamp": ts,
                    "camera": cam,
                    "event": event.strip(),
                    "battery": int(bat),
                    "file": filename
                })
    return pd.DataFrame(rows)

def hour_of_day(dt):
    """Return fractional hour of day for a datetime (0-24)."""
    return dt.hour + dt.minute/60 + dt.second/3600

def time_ticks():
    """Return tick positions and labels for y-axis (time-of-day)."""
    ticks = list(range(0,25,2))  # every 2 hours
    labels = [f"{h:02d}:00" for h in ticks]
    return ticks, labels

# --------------------------
# Session builders
# --------------------------
def build_charging_sessions(df):
    """
    Group contiguous charging log entries per camera into sessions using a time gap threshold.
    Each session = start_time, end_time, start_bat, end_bat, camera, duration_hours.
    """
    rows = []
    dfc = df[df["event"].str.contains("charging", case=False, na=False)].copy()
    if dfc.empty:
        return pd.DataFrame(rows)
    dfc = dfc.sort_values(["camera","timestamp"])
    for cam, g in dfc.groupby("camera"):
        g = g.reset_index(drop=True)
        session_start = g.loc[0,"timestamp"]
        start_bat = g.loc[0,"battery"]
        last_time = session_start
        last_bat = start_bat
        for i in range(1, len(g)):
            cur = g.loc[i,"timestamp"]
            cur_bat = g.loc[i,"battery"]
            if (cur - last_time).total_seconds() <= TIME_GAP_SECONDS:
                # continue session
                last_time = cur
                last_bat = cur_bat
            else:
                # close previous session
                rows.append({
                    "camera": cam,
                    "start": session_start,
                    "end": last_time,
                    "start_bat": start_bat,
                    "end_bat": last_bat,
                    "duration_h": (last_time - session_start).total_seconds()/3600.0
                })
                # new session
                session_start = cur
                start_bat = cur_bat
                last_time = cur
                last_bat = cur_bat
        # close final session for this camera
        rows.append({
            "camera": cam,
            "start": session_start,
            "end": last_time,
            "start_bat": start_bat,
            "end_bat": last_bat,
            "duration_h": (last_time - session_start).total_seconds()/3600.0
        })
    return pd.DataFrame(rows)

def build_pair_sessions(df, start_keyword, stop_keyword, event_label):
    """
    Build sessions by finding explicit start and stop events.
    For example: Power On / Power Off, Start Record / Stop Record, Pre-Record Start / Stop.
    We scan logs per camera in chronological order and pair first start then next stop.
    """
    rows = []
    dfx = df[df["event"].str.contains(start_keyword + "|" + stop_keyword, case=False, na=False)].copy()
    if dfx.empty:
        return pd.DataFrame(rows)
    dfx = dfx.sort_values(["camera","timestamp"])
    for cam, g in dfx.groupby("camera"):
        pending_start = None
        start_bat = None
        for _, r in g.iterrows():
            ev = r["event"].lower()
            if start_keyword in ev:
                pending_start = r["timestamp"]
                start_bat = r["battery"]
            elif stop_keyword in ev and pending_start is not None:
                end_time = r["timestamp"]
                rows.append({
                    "camera": cam,
                    "start": pending_start,
                    "end": end_time,
                    "start_bat": start_bat,
                    "end_bat": r["battery"],
                    "duration_h": (end_time - pending_start).total_seconds()/3600.0,
                    "event": f"{event_label} (start->stop)"
                })
                pending_start = None
                start_bat = None
        # incomplete pairs are ignored (no stop)
    return pd.DataFrame(rows)

# --------------------------
# Compressed event table (merge repeated events into ranges)
# --------------------------
def compress_event_table(df):
    """
    Compress repeated or consecutive identical events per camera into ranges.
    Returns rows with Camera, Event, StartTime, EndTime, StartBattery, EndBattery.
    """
    if df.empty:
        return pd.DataFrame(columns=["Camera","Event","StartTime","EndTime","StartBattery","EndBattery","Duration_h"])
    df = df.sort_values(["camera","timestamp"]).reset_index(drop=True)
    out = []
    cur = df.iloc[0].to_dict()
    start_time = cur["timestamp"]
    end_time = cur["timestamp"]
    start_bat = cur["battery"]
    end_bat = cur["battery"]
    cur_event = cur["event"]
    cur_cam = cur["camera"]
    for i in range(1, len(df)):
        r = df.iloc[i].to_dict()
        if r["event"] == cur_event and r["camera"] == cur_cam:
            # continue same event
            end_time = r["timestamp"]
            end_bat = r["battery"]
        else:
            out.append({
                "Camera": cur_cam,
                "Event": normalize_event_name(cur_event),
                "StartTime": start_time,
                "EndTime": end_time,
                "StartBattery": start_bat,
                "EndBattery": end_bat,
                "Duration_h": (end_time - start_time).total_seconds()/3600.0
            })
            cur_event = r["event"]
            cur_cam = r["camera"]
            start_time = r["timestamp"]
            end_time = r["timestamp"]
            start_bat = r["battery"]
            end_bat = r["battery"]
    # append last
    out.append({
        "Camera": cur_cam,
        "Event": normalize_event_name(cur_event),
        "StartTime": start_time,
        "EndTime": end_time,
        "StartBattery": start_bat,
        "EndBattery": end_bat,
        "Duration_h": (end_time - start_time).total_seconds()/3600.0
    })
    return pd.DataFrame(out)

def normalize_event_name(ev):
    """Map technical event strings to simple plain-language phrases."""
    ev_l = ev.lower()
    ev = ev.replace("usb command", "USB disconnected").replace("usb remove", "USB removed").replace("auto", "automatic")
    # replacements - exact mapping
    ev_map = {
        "power on": "Powered On",
        "power off": "Powered Off",
        "system power off - auto": "Automatic Shutdown",
        "system power off - usb remove": "Shutdown (USB removed)",
        "battery charging": "Charging",
        "battery changing done": "Charging Completed",
        "start record": "Recording Started",
        "stop record": "Recording Stopped",
        "start pre record": "Pre-record Started",
        "stop pre record": "Pre-record Stopped",
        "low battery": "Low Battery"
    }
    for k,v in ev_map.items():
        if k in ev_l:
            return v
    # fallback: title case the raw event
    return ev.title()

# --------------------------
# UI / Main
# --------------------------
uploaded_files = st.file_uploader("Upload camera log files (.txt, .log)", type=["txt","log"], accept_multiple_files=True)

if not uploaded_files:
    st.info("Upload one or more log files (camera logs) to start. Files must contain lines like `2025-09-09 00:01:44 #ID:007446-000000 #Battery Charging - Battery Level - 66%`.")
    st.stop()

# parse
df = parse_logs(uploaded_files)
if df.empty:
    st.error("No valid log entries found. Please upload logs and ensure their format matches the sample.")
    st.stop()

df = df.sort_values("timestamp").reset_index(drop=True)

# date and camera filters
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date", value=df["timestamp"].dt.date.min())
with col2:
    end_date = st.date_input("End Date", value=df["timestamp"].dt.date.max())
mask = (df["timestamp"].dt.date >= start_date) & (df["timestamp"].dt.date <= end_date)
df = df[mask]

cameras = sorted(df["camera"].unique())
selected_cams = st.multiselect("Select camera(s)", cameras, default=cameras)
df = df[df["camera"].isin(selected_cams)]

# prepare time ticks
ticks, ticklabels = time_ticks()

# Build sessions
charge_sessions = build_charging_sessions(df)
power_sessions = build_pair_sessions(df, start_keyword="power on", stop_keyword="power off", event_label="Power")
# For recording we want Start Record/Stop Record and Pre-Record start/stop separately
rec_sessions = build_pair_sessions(df, start_keyword="start record", stop_keyword="stop record", event_label="Record")
pre_rec_sessions = build_pair_sessions(df, start_keyword="start pre-record|start pre record|start pre_record", stop_keyword="stop pre-record|stop pre record|stop pre_record", event_label="Pre-Record")

# Daily summary dictionary per camera+date
daily = {}
def add_daily(camera, day, kind, hours):
    key = (camera, day)
    if key not in daily:
        daily[key] = {"Camera": camera, "Date": day, "Total Charging (h)": 0.0, "Total Powered On (h)": 0.0, "Total Recording (h)": 0.0}
    if kind == "charge":
        daily[key]["Total Charging (h)"] += hours
    elif kind == "power":
        daily[key]["Total Powered On (h)"] += hours
    elif kind == "rec":
        daily[key]["Total Recording (h)"] += hours

# --------------------------
# Graph 1: Charging Sessions
# --------------------------
st.subheader("Charging sessions (bars show start time → duration on y-axis)")

if not charge_sessions.empty:
    fig = go.Figure()
    legend_tracker = set()
    for _, s in charge_sessions.iterrows():
        camera = s["camera"]
        day = s["start"].date().strftime("%Y-%m-%d")
        start_hour = hour_of_day(s["start"])
        dur = s["duration_h"]
        end_hour = start_hour + dur
        # color: light by default, dark if end_bat low
        bar_color = "rgba(173,216,230,0.8)"  # lightblue
        end_marker_color = "rgba(0,100,200,0.9)" if s["end_bat"] >= 20 else "rgba(139,0,0,0.95)"  # dark if low
        legend_key = (camera, "charging")
        showlegend = legend_key not in legend_tracker
        legend_tracker.add(legend_key)
        fig.add_trace(go.Bar(
            x=[day],
            y=[dur],
            base=[start_hour],
            name=f"{camera} charge" if showlegend else None,
            legendgroup=f"{camera}-charge",
            marker_color=bar_color,
            hovertemplate=(
                f"Camera: {camera}<br>"
                f"Start: {s['start'].strftime('%H:%M:%S')}<br>"
                f"Stop: {s['end'].strftime('%H:%M:%S')}<br>"
                f"Battery: {s['start_bat']}% → {s['end_bat']}%<br>"
                f"Duration: {dur:.2f} hours<br>"
                f"Date: {day}<extra></extra>"
            ),
            showlegend=showlegend
        ))
        # end marker for clarity
        fig.add_trace(go.Scatter(
            x=[day],
            y=[end_hour],
            mode="markers",
            marker=dict(size=8, color=end_marker_color),
            hoverinfo="skip",
            showlegend=False
        ))
        # daily summary entry
        add_daily(camera, day, "charge", dur)

    fig.update_layout(
        xaxis=dict(title="Date", categoryorder="array", categoryarray=[d.strftime("%Y-%m-%d") for d in pd.date_range(df["timestamp"].dt.date.min(), df["timestamp"].dt.date.max())]),
        yaxis=dict(title="Time of day (hours)", tickvals=ticks, ticktext=ticklabels, range=[0,24]),
        barmode="stack",
        bargap=0.2,
        template="plotly_white",
        height=420
    )
    st.plotly_chart(fig, use_container_width=True)
    # summary: exact per-day text
    st.markdown("**Charging summary (exact, from data):**")
    for cam_day, vals in sorted(daily.items()):
        cam, day = cam_day
        st.write(f"{day} - Camera {cam}: Charged {vals['Total Charging (h)']:.2f} hours")
else:
    st.info("No charging sessions found in the selected logs/date range.")

# --------------------------
# Graph 2: Power On/Off
# --------------------------
st.subheader("Power On / Off timeline (bars: powered-on period)")

if not power_sessions.empty:
    fig2 = go.Figure()
    legend_tracker = set()
    for _, s in power_sessions.iterrows():
        camera = s["camera"]
        day = s["start"].date().strftime("%Y-%m-%d")
        start_hour = hour_of_day(s["start"])
        dur = s["duration_h"]
        end_hour = start_hour + dur
        # color: green for powered-on bars; dark orange for poweroff marker if end battery low
        bar_color = "rgba(144,238,144,0.9)"  # lightgreen
        end_marker_color = "rgba(255,140,0,0.9)" if s["end_bat"] >= 0 else "rgba(139,0,0,0.95)"
        legend_key = (camera, "power")
        showlegend = legend_key not in legend_tracker
        legend_tracker.add(legend_key)
        fig2.add_trace(go.Bar(
            x=[day],
            y=[dur],
            base=[start_hour],
            name=f"{camera} powered on" if showlegend else None,
            legendgroup=f"{camera}-power",
            marker_color=bar_color,
            hovertemplate=(
                f"Camera: {camera}<br>On: {s['start'].strftime('%H:%M:%S')}<br>Off: {s['end'].strftime('%H:%M:%S')}<br>"
                f"Battery: {s['start_bat']}% → {s['end_bat']}%<br>Duration: {dur:.2f} hours<extra></extra>"
            ),
            showlegend=showlegend
        ))
        fig2.add_trace(go.Scatter(
            x=[day], y=[end_hour], mode="markers", marker=dict(size=8, color=end_marker_color), showlegend=False
        ))
        add_daily(camera, day, "power", dur)

    fig2.update_layout(
        xaxis=dict(title="Date", categoryorder="array", categoryarray=[d.strftime("%Y-%m-%d") for d in pd.date_range(df["timestamp"].dt.date.min(), df["timestamp"].dt.date.max())]),
        yaxis=dict(title="Time of day (hours)", tickvals=ticks, ticktext=ticklabels, range=[0,24]),
        barmode="stack",
        bargap=0.2,
        template="plotly_white",
        height=420
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.markdown("**Power summary (exact):**")
    for cam_day, vals in sorted(daily.items()):
        cam, day = cam_day
        st.write(f"{day} - Camera {cam}: Powered on {vals['Total Powered On (h)']:.2f} hours")
else:
    st.info("No power on/off sessions found in the selected logs/date range.")

# --------------------------
# Graph 3: Recording / Pre-record
# --------------------------
st.subheader("Recording / Pre-record timeline")

if not rec_sessions.empty or not pre_rec_sessions.empty:
    fig3 = go.Figure()
    legend_tracker = set()
    # recording sessions
    for _, s in rec_sessions.iterrows():
        camera = s["camera"]
        day = s["start"].date().strftime("%Y-%m-%d")
        start_hour = hour_of_day(s["start"])
        dur = s["duration_h"]
        end_hour = start_hour + dur
        bar_color = "rgba(100,149,237,0.8)"  # light cornflower
        end_marker_color = "rgba(25,25,112,0.9)"  # dark
        legend_key = (camera, "record")
        showlegend = legend_key not in legend_tracker
        legend_tracker.add(legend_key)
        fig3.add_trace(go.Bar(
            x=[day],
            y=[dur],
            base=[start_hour],
            name=f"{camera} recording" if showlegend else None,
            legendgroup=f"{camera}-record",
            marker_color=bar_color,
            hovertemplate=(
                f"Camera: {camera}<br>Start: {s['start'].strftime('%H:%M:%S')}<br>Stop: {s['end'].strftime('%H:%M:%S')}<br>"
                f"Battery: {s['start_bat']}% → {s['end_bat']}%<br>Duration: {dur:.2f} hours<extra></extra>"
            ),
            showlegend=showlegend
        ))
        fig3.add_trace(go.Scatter(x=[day], y=[end_hour], mode="markers", marker=dict(size=8, color=end_marker_color), showlegend=False))
        add_daily(camera, day, "rec", dur)

    # pre-record sessions (different color)
    for _, s in pre_rec_sessions.iterrows():
        camera = s["camera"]
        day = s["start"].date().strftime("%Y-%m-%d")
        start_hour = hour_of_day(s["start"])
        dur = s["duration_h"]
        end_hour = start_hour + dur
        bar_color = "rgba(255,182,193,0.8)"  # lightpink
        end_marker_color = "rgba(219,112,147,0.9)"
        legend_key = (camera, "pre_record")
        showlegend = legend_key not in legend_tracker
        legend_tracker.add(legend_key)
        fig3.add_trace(go.Bar(
            x=[day],
            y=[dur],
            base=[start_hour],
            name=f"{camera} pre-record" if showlegend else None,
            legendgroup=f"{camera}-pre",
            marker_color=bar_color,
            hovertemplate=(
                f"Camera: {camera}<br>Start: {s['start'].strftime('%H:%M:%S')}<br>Stop: {s['end'].strftime('%H:%M:%S')}<br>"
                f"Battery: {s['start_bat']}% → {s['end_bat']}%<br>Duration: {dur:.2f} hours<extra></extra>"
            ),
            showlegend=showlegend
        ))
        fig3.add_trace(go.Scatter(x=[day], y=[end_hour], mode="markers", marker=dict(size=8, color=end_marker_color), showlegend=False))
        add_daily(camera, day, "rec", dur)

    fig3.update_layout(
        xaxis=dict(title="Date", categoryorder="array", categoryarray=[d.strftime("%Y-%m-%d") for d in pd.date_range(df["timestamp"].dt.date.min(), df["timestamp"].dt.date.max())]),
        yaxis=dict(title="Time of day (hours)", tickvals=ticks, ticktext=ticklabels, range=[0,24]),
        barmode="stack",
        bargap=0.2,
        template="plotly_white",
        height=420
    )
    st.plotly_chart(fig3, use_container_width=True)
    st.markdown("**Recording summary (exact):**")
    for cam_day, vals in sorted(daily.items()):
        cam, day = cam_day
        st.write(f"{day} - Camera {cam}: Recorded {vals['Total Recording (h)']:.2f} hours")
else:
    st.info("No recording sessions found in the selected logs/date range.")

# --------------------------
# Low battery alerts
# --------------------------
low = df[df["battery"] < 20]
if not low.empty:
    st.subheader("Low battery alerts (<20%)")
    st.dataframe(low[["timestamp","camera","event","battery"]], use_container_width=True)

# --------------------------
# Daily summary table (DataFrame)
# --------------------------
if daily:
    summary_df = pd.DataFrame(sorted(daily.values(), key=lambda r: (r["Date"], r["Camera"])))
    st.subheader("Daily Summary (per Camera)")
    st.dataframe(summary_df, use_container_width=True)

    # Download buttons for Daily Summary CSV and Excel
    csv_bytes = summary_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download Daily Summary (CSV)", data=csv_bytes, file_name="daily_summary.csv", mime="text/csv")
    # Excel
    towrite = BytesIO()
    with pd.ExcelWriter(towrite, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="Daily Summary")
        writer.save()
    towrite.seek(0)
    st.download_button("Download Daily Summary (Excel)", data=towrite, file_name="daily_summary.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --------------------------
# Compressed event table and downloads
# --------------------------
compressed = compress_event_table(df)
if not compressed.empty:
    # rename columns for user friendly
    compressed_disp = compressed.copy()
    compressed_disp["Event"] = compressed_disp["Event"].apply(lambda x: x)  # already normalized inside compress_event_table
    compressed_disp["StartTime"] = compressed_disp["StartTime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    compressed_disp["EndTime"] = compressed_disp["EndTime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    st.subheader("Event Table (compressed)")
    st.dataframe(compressed_disp[["Camera","Event","StartTime","EndTime","StartBattery","EndBattery","Duration_h"]], use_container_width=True)

    # Download compressed event table as CSV / Excel
    csv_bytes2 = compressed_disp.to_csv(index=False).encode("utf-8")
    st.download_button("Download Event Table (CSV)", data=csv_bytes2, file_name="event_table.csv", mime="text/csv")
    towrite2 = BytesIO()
    with pd.ExcelWriter(towrite2, engine="xlsxwriter") as writer:
        compressed_disp.to_excel(writer, index=False, sheet_name="Events")
        writer.save()
    towrite2.seek(0)
    st.download_button("Download Event Table (Excel)", data=towrite2, file_name="event_table.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("No events to show in compressed table after processing.")

# final note for users
st.markdown("**Notes:**\n- Hover any bar to see start time, stop time, battery levels and exact duration in hours.\n- If a session lacks a stop event it is not shown (we require a start+stop pair for Power/Record). Charging sessions are grouped by gaps so explicit stop event is not necessary.")
