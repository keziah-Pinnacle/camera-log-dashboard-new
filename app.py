# app.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("Camera Log Monitoring Dashboard")

# ------- Configuration -------
GAP_SECONDS = 1  # small visual gap between adjacent sessions

# Human friendly event rename mapping (input substrings -> display name)
EVENT_NORMALIZE = {
    "DC Connect": "DC Connect",
    "DC Remove": "DC Remove",
    "Battery Charging": "Battery Charging",
    "Battery Charge Stop": "Battery Charge Stop",
    "Battery Changing Done": "Battery Fully Charged",
    "System Power On": "Power On",
    "System Power Off": "Power Off",
    "Start Record": "Start Record",
    "Stop Record": "Stop Record",
    "Start Pre Record": "Start PreRecord",
    "Start PreRecord": "Start PreRecord",
    "Enter U Disk Status": "USB Connected",
    "USB Remove": "USB Removed",
    "USB Remove - Battery Level": "USB Removed",
    "USB Command": "USB Command",
    "USB Remote": "USB Removed",
    "Low Battery": "Low Battery",
    "Wifi Start": "WiFi Start",
    # ... add more normalizations if you need
}

# Colors for normalized events
EVENT_COLORS = {
    "Battery Charging": "#4A90E2",         # blue
    "Battery Charge Stop": "#2B7BE4",      # darker blue
    "Battery Fully Charged": "#2ECC71",    # green
    "Power On": "#2ECC71",                 # green
    "Power Off": "#E94B35",                # red
    "Start Record": "#FF7F50",             # coral
    "Stop Record": "#FFA07A",              # light coral
    "Start PreRecord": "#7B61FF",          # purple
    "Stop PreRecord": "#BDA2FF",           # light purple
    "USB Connected": "#9E9E9E",            # grey
    "USB Removed": "#6E6E6E",
    "Low Battery": "#E94B35",
    # fallback
    "default": "#999999"
}


# ------- Helpers -------
def human_event(raw):
    # pick the first matching key from EVENT_NORMALIZE
    for k in EVENT_NORMALIZE:
        if k.lower() in raw.lower():
            return EVENT_NORMALIZE[k]
    # fall back: strip and return raw short version
    return raw.split(" - ")[0].strip()


def parse_logs(uploaded_files):
    """
    Parse uploaded log files. returns DataFrame with columns:
      timestamp (datetime), camera (string), raw_event (string), event (normalized), battery (int), source_file
    """
    rows = []
    # Pattern that captures timestamp, ID, event, battery (keeps tolerant spaces)
    pat = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+#ID:([0-9\-A-Za-z]+)\s+#(.*?)\s*(?:-.*Battery Level\s*-\s*(\d+)%\s*)?$")
    for f in uploaded_files:
        name = f.name
        raw = f.read().decode("utf-8", errors="ignore")
        for line in raw.splitlines():
            if not line.strip():
                continue
            m = pat.search(line.strip())
            if not m:
                continue
            ts_str, cam, raw_event, bat = m.groups()
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                # try alternate formats, if any
                continue
            battery = int(bat) if bat and bat.isdigit() else None
            normalized = human_event(raw_event)
            rows.append({
                "timestamp": ts,
                "camera": cam,
                "raw_event": raw_event.strip(),
                "event": normalized,
                "battery": battery,
                "source_file": name
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["camera", "timestamp"]).reset_index(drop=True)
    return df


def compress_sessions(df):
    """
    Compress consecutive identical events for same camera into session rows.
    Add a small gap (GAP_SECONDS) for visual separation between sessions.
    Returns DataFrame with Camera, Event, Start, End, StartBat, EndBat, Duration_h
    """
    out = []
    if df.empty:
        return pd.DataFrame(columns=["Camera", "Event", "Start", "End", "StartBat", "EndBat", "Duration_h"])
    grouped = df.groupby("camera", sort=True)
    for cam, g in grouped:
        g = g.reset_index(drop=True)
        cur_ev = g.loc[0, "event"]
        start = g.loc[0, "timestamp"]
        start_bat = g.loc[0, "battery"]
        end = start
        end_bat = start_bat
        for i in range(1, len(g)):
            r = g.loc[i]
            if r["event"] == cur_ev:
                end = r["timestamp"]
                end_bat = r["battery"]
            else:
                # append current session
                out.append([cam, cur_ev, start, end, start_bat, end_bat])
                # set next session start with small gap
                cur_ev = r["event"]
                start = r["timestamp"] + timedelta(seconds=GAP_SECONDS)
                start_bat = r["battery"]
                end = start
                end_bat = start_bat
        # append last
        out.append([cam, cur_ev, start, end, start_bat, end_bat])

    out_df = pd.DataFrame(out, columns=["Camera", "Event", "Start", "End", "StartBat", "EndBat"])
    out_df["Duration_h"] = (out_df["End"] - out_df["Start"]).dt.total_seconds() / 3600.0
    # Also add Date column for grouping
    out_df["Date"] = out_df["Start"].dt.date
    return out_df


def format_hhmm(hours_decimal):
    """Return 'Hh Mm' string from decimal hours (float)."""
    if pd.isna(hours_decimal):
        return "0h 0m"
    total_minutes = int(round(hours_decimal * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h}h {m}m"


def download_buttons(df, name):
    # CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(f"Download {name} CSV", data=csv_bytes, file_name=f"{name.replace(' ','_').lower()}.csv", mime="text/csv")
    # Excel
    towrite = BytesIO()
    with pd.ExcelWriter(towrite, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=name[:31])
    towrite.seek(0)
    st.download_button(f"Download {name} Excel", data=towrite, file_name=f"{name.replace(' ','_').lower()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------- Plot helpers -------
def plot_timeline_segments(df_sessions, title, filter_events=None, event_color_map=None, hide_duplicate_legend=True):
    """
    df_sessions: compressed sessions with Camera, Event, Start, End, StartBat, EndBat, Date
    filter_events: list or None to filter which events to plot
    event_color_map: dict event -> color
    """
    if df_sessions.empty:
        st.info(f"No {title} found.")
        return

    plot_df = df_sessions.copy()
    if filter_events is not None:
        plot_df = plot_df[plot_df["Event"].isin(filter_events)]
    if plot_df.empty:
        st.info(f"No {title} found after filtering.")
        return

    # Create one row per camera/date so plotting is readable.
    # We'll use y = "Camera (Date)" label so multiple sessions for same camera+date are on same row.
    plot_df["y_label"] = plot_df["Camera"].astype(str) + " | " + plot_df["Date"].astype(str)

    fig = go.Figure()
    used_labels = set()

    # Plot each session as a horizontal line between Start and End (Scatter with lines)
    for i, r in plot_df.iterrows():
        color = event_color_map.get(r["Event"], EVENT_COLORS.get(r["Event"], EVENT_COLORS["default"]))
        legend_name = r["Event"]
        showlegend = False
        if hide_duplicate_legend:
            if legend_name not in used_labels:
                showlegend = True
                used_labels.add(legend_name)
        else:
            showlegend = True

        hover = (
            f"Camera: {r['Camera']}<br>"
            f"Event: {r['Event']}<br>"
            f"Start: {r['Start'].strftime('%Y-%m-%d %H:%M:%S')} ({'' if pd.isna(r['StartBat']) else str(r['StartBat'])+'%'})<br>"
            f"End: {r['End'].strftime('%Y-%m-%d %H:%M:%S')} ({'' if pd.isna(r['EndBat']) else str(r['EndBat'])+'%'})<br>"
            f"Duration: {format_hhmm(r['Duration_h'])}"
        )

        fig.add_trace(go.Scatter(
            x=[r["Start"], r["End"]],
            y=[r["y_label"], r["y_label"]],
            mode="lines+markers",
            line=dict(color=color, width=12),
            marker=dict(size=6),
            name=legend_name,
            showlegend=showlegend,
            hovertemplate=hover
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title="Camera | Date",
        template="plotly_white",
        height=400 + 20 * len(plot_df["y_label"].unique()),
        legend_title_text="Event"
    )
    # improve x-axis formatting
    fig.update_xaxes(showgrid=True)
    fig.update_yaxes(automargin=True)
    st.plotly_chart(fig, width="stretch")


# ------- UI & Main flow -------
st.sidebar.header("Upload logs")
uploaded = st.sidebar.file_uploader("Upload .txt/.log (multiple allowed)", type=["txt", "log"], accept_multiple_files=True)

if not uploaded:
    st.info("Upload one or more log files from cameras to start.")
    st.stop()

# parse logs
raw_df = parse_logs(uploaded)
if raw_df.empty:
    st.error("No parsable log lines found. Confirm log format.")
    st.stop()

# compress consecutive identical events into sessions (with gaps)
sessions = compress_sessions(raw_df)

# Event Table (compressed)
st.header("Event Table (compressed)")
st.write("Consecutive identical events are merged into sessions with start/end times. Small visual gap is added between sessions.")
st.dataframe(sessions[["Camera", "Event", "Start", "End", "StartBat", "EndBat", "Duration_h"]].rename(columns={
    "StartBat": "StartBattery", "EndBat": "EndBattery", "Duration_h": "DurationHours"
}), width="stretch")
download_buttons_df = st.columns(1)[0]
download_buttons_df.write("Export:")
download_buttons(sessions[["Camera", "Event", "Start", "End", "StartBat", "EndBat", "Duration_h"]].rename(columns={
    "StartBat": "StartBattery", "EndBat": "EndBattery", "Duration_h": "DurationHours"
}), "Event Table")

# Daily Summary
st.header("Daily Summary")
# aggregate durations by camera/date and event-type buckets
if not sessions.empty:
    agg = sessions.copy()
    agg["IsCharging"] = agg["Event"].str.contains("Charging", case=False, na=False)
    agg["IsPower"] = agg["Event"].str.contains("Power", case=False, na=False)
    agg["IsRecord"] = agg["Event"].str.contains("Record", case=False, na=False) | agg["Event"].str.contains("PreRecord", case=False, na=False)

    summary = agg.groupby(["Camera", "Date"]).agg(
        Charging_h=("Duration_h", lambda s: s[agg.loc[s.index, "IsCharging"]].sum()),
        Power_h=("Duration_h", lambda s: s[agg.loc[s.index, "IsPower"]].sum()),
        Record_h=("Duration_h", lambda s: s[agg.loc[s.index, "IsRecord"]].sum())
    ).reset_index()

    # format durations to hh mm
    summary["Charging"] = summary["Charging_h"].apply(format_hhmm)
    summary["Power"] = summary["Power_h"].apply(format_hhmm)
    summary["Record"] = summary["Record_h"].apply(format_hhmm)
    summary_display = summary[["Camera", "Date", "Charging", "Power", "Record"]]

    st.dataframe(summary_display, width="stretch")
    download_buttons(summary_display, "Daily Summary")
else:
    st.info("No sessions to summarise.")

# Charts area
st.header("Timelines")
st.markdown("Hover any segment to see exact start time, end time, batteries and duration.")

# Charging timeline: include any event that mentions 'Charging'
charging_events = sessions[sessions["Event"].str.contains("Charging", case=False, na=False)]
plot_timeline_segments(
    charging_events,
    title="Charging sessions (multiple sessions shown with gaps)",
    filter_events=None,
    event_color_map=EVENT_COLORS
)

# Power timeline: specifically Power On / Power Off
power_events = sessions[sessions["Event"].str.contains("Power On|Power Off|System Power", case=False, na=False)]
plot_timeline_segments(
    power_events,
    title="Power On / Power Off timeline",
    filter_events=None,
    event_color_map=EVENT_COLORS
)

# Recording timeline: include Start/Stop and PreRecord
record_events = sessions[sessions["Event"].str.contains("Record|PreRecord", case=False, na=False)]
plot_timeline_segments(
    record_events,
    title="Recording / Pre-record timeline",
    filter_events=None,
    event_color_map=EVENT_COLORS
)

# Low battery alerts
low_battery_df = raw_df[raw_df["battery"].notna() & (raw_df["battery"] < 20)]
if not low_battery_df.empty:
    st.header("Low battery alerts (<20%)")
    st.dataframe(low_battery_df[["timestamp", "camera", "event", "battery", "source_file"]].rename(columns={
        "timestamp": "Timestamp", "camera": "Camera", "event": "Event", "battery": "Battery", "source_file": "SourceFile"
    }), width="stretch")
    download_buttons(low_battery_df[["timestamp", "camera", "event", "battery", "source_file"]].rename(columns={
        "timestamp": "Timestamp", "camera": "Camera", "event": "Event", "battery": "Battery", "source_file": "SourceFile"
    }), "Low Battery Alerts")
else:
    st.info("No low battery alerts in this dataset.")
