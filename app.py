import streamlit as st
import pandas as pd
import re
from datetime import datetime
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("Camera Log Monitoring Dashboard")

# ---- Config ----
EVENT_NORMALIZE = {
    "Battery Charging": "Start Charge",
    "Battery Charge Stop": "Stop Charge",
    "System Power On": "Power On",
    "System Power Off": "Power Off",
    "Start Record": "Start Record",
    "Stop Record": "Stop Record",
    "Start Pre Record": "Start PreRecord",
    "Stop PreRecord": "Stop PreRecord",
}
EVENT_COLORS = {
    "Start Charge": "#4A90E2",
    "Stop Charge": "#2ECC71",
    "Power On": "#2ECC71",
    "Power Off": "#E94B35",
    "Start Record": "#90EE90",
    "Stop Record": "#FF7F7F",
    "Start PreRecord": "#87CEFA",
    "Stop PreRecord": "#00008B",
}
def human_event(raw):
    for k in EVENT_NORMALIZE:
        if k.lower() in raw.lower():
            return EVENT_NORMALIZE[k]
    return raw.strip()

def parse_logs(files):
    pat = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+#ID:([0-9\-A-Za-z]+)\s+#(.*?)\s*(?:-.*Battery Level\s*-\s*(\d+)%\s*)?$")
    rows = []
    for f in files:
        text = f.read().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            m = pat.search(line.strip())
            if not m:
                continue
            ts, cam, ev, bat = m.groups()
            ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            cam_short = cam.split("-")[0]  # only first 6 digits
            rows.append({
                "timestamp": ts,
                "camera": cam_short,
                "event": human_event(ev),
                "battery": int(bat) if bat else None
            })
    return pd.DataFrame(rows).sort_values(["camera", "timestamp"])

def compress_sessions(df):
    out = []
    for cam, g in df.groupby("camera"):
        g = g.reset_index(drop=True)
        start, ev, bat = g.loc[0, "timestamp"], g.loc[0, "event"], g.loc[0, "battery"]
        for i in range(1, len(g)):
            if g.loc[i, "event"] != ev:
                out.append([cam, ev, start, g.loc[i-1, "timestamp"], bat, g.loc[i-1, "battery"]])
                start, ev, bat = g.loc[i, "timestamp"], g.loc[i, "event"], g.loc[i, "battery"]
        out.append([cam, ev, start, g.loc[len(g)-1, "timestamp"], bat, g.loc[len(g)-1, "battery"]])
    df2 = pd.DataFrame(out, columns=["Camera","Event","Start","End","StartBat","EndBat"])
    df2["Duration_h"] = (df2["End"]-df2["Start"]).dt.total_seconds()/3600
    df2["Date"] = df2["Start"].dt.date
    return df2

def format_duration(hours):
    mins = int(hours*60)
    if mins < 60:
        return f"{mins}m"
    return f"{mins//60}h {mins%60}m"

def download_buttons(df,name):
    csv = df.to_csv(index=False).encode()
    st.download_button(f"⬇ {name} CSV", csv, f"{name}.csv", key=f"{name}_csv")
    buf = BytesIO()
    with pd.ExcelWriter(buf,engine="openpyxl") as w:
        df.to_excel(w,index=False,sheet_name=name[:31])
    st.download_button(f"⬇ {name} Excel", buf.getvalue(), f"{name}.xlsx", key=f"{name}_xls")

# ---- UI ----
files = st.sidebar.file_uploader("Upload logs",type=["txt","log"],accept_multiple_files=True)
if not files: st.stop()
df = parse_logs(files)
if df.empty: st.error("No data"); st.stop()
sessions = compress_sessions(df)

# Date filter
min_d,max_d = df["timestamp"].min().date(), df["timestamp"].max().date()
date_range = st.sidebar.date_input("Select Date Range", [min_d,max_d], min_value=min_d, max_value=max_d)
if len(date_range)==2:
    start,end = date_range
    sessions = sessions[(sessions["Date"]>=start)&(sessions["Date"]<=end)]

# ---- Charging ----
st.header("Charging Sessions")
fig = go.Figure()
used=set()
for _,r in sessions[sessions["Event"].str.contains("Charge")].iterrows():
    showlegend = r["Event"] not in used
    used.add(r["Event"])
    fig.add_trace(go.Bar(
        x=[r["Date"]], y=[r["Duration_h"]],
        marker_color=EVENT_COLORS[r["Event"]],
        name=r["Event"],
        showlegend=showlegend,
        hovertext=f"{r['Camera']} {r['Event']}<br>{r['Start']} - {r['End']}<br>Duration: {format_duration(r['Duration_h'])}"
    ))
fig.update_layout(barmode="stack",yaxis_title="Hours",xaxis_title="Date",template="plotly_white")
st.plotly_chart(fig,use_container_width=True)
summary = sessions[sessions["Event"].str.contains("Charge")].groupby(["Camera","Date"])["Duration_h"].sum().reset_index()
summary["TotalCharging"] = summary["Duration_h"].apply(format_duration)
st.dataframe(summary[["Camera","Date","TotalCharging"]])
download_buttons(summary,"ChargingSummary")

# ---- Power ----
st.header("Power On / Off")
fig = go.Figure()
used=set()
for _,r in sessions[sessions["Event"].str.contains("Power")].iterrows():
    showlegend = r["Event"] not in used
    used.add(r["Event"])
    fig.add_trace(go.Bar(
        x=[r["Date"]], y=[r["Duration_h"]*60], # minutes
        marker_color=EVENT_COLORS[r["Event"]],
        name=r["Event"],
        showlegend=showlegend,
        hovertext=f"{r['Camera']} {r['Event']}<br>{r['Start']} - {r['End']}<br>Duration: {format_duration(r['Duration_h'])}"
    ))
fig.update_layout(barmode="stack",yaxis_title="Duration (minutes/hours)",xaxis_title="Date",template="plotly_white")
st.plotly_chart(fig,use_container_width=True)
summary = sessions[sessions["Event"].str.contains("Power")].groupby(["Camera","Date","Event"])["Duration_h"].sum().reset_index()
summary["Duration"] = summary["Duration_h"].apply(format_duration)
st.dataframe(summary[["Camera","Date","Event","Duration"]])
download_buttons(summary,"PowerSummary")

# ---- Recording ----
st.header("Recording / PreRecord")
fig = go.Figure()
used=set()
for _,r in sessions[sessions["Event"].str.contains("Record")].iterrows():
    showlegend = r["Event"] not in used
    used.add(r["Event"])
    fig.add_trace(go.Bar(
        x=[r["Date"]], y=[r["Duration_h"]*60],
        marker_color=EVENT_COLORS[r["Event"]],
        name=r["Event"],
        showlegend=showlegend,
        hovertext=f"{r['Camera']} {r['Event']}<br>{r['Start']} - {r['End']}<br>Duration: {format_duration(r['Duration_h'])}"
    ))
fig.update_layout(barmode="stack",yaxis_title="Duration (minutes/hours)",xaxis_title="Date",template="plotly_white")
st.plotly_chart(fig,use_container_width=True)
summary = sessions[sessions["Event"].str.contains("Record")].groupby(["Camera","Date","Event"])["Duration_h"].sum().reset_index()
summary["Duration"] = summary["Duration_h"].apply(format_duration)
st.dataframe(summary[["Camera","Date","Event","Duration"]])
download_buttons(summary,"RecordingSummary")

# ---- Daily Summary ----
st.header("Daily Summary")
st.write("This is the overall summary of events for the selected logs.")
daily = sessions.groupby(["Camera","Date"]).agg(
    Charging_h=("Duration_h",lambda x:x[sessions.loc[x.index,"Event"].str.contains("Charge")].sum()),
    Power_h=("Duration_h",lambda x:x[sessions.loc[x.index,"Event"].str.contains("Power")].sum()),
    Record_h=("Duration_h",lambda x:x[sessions.loc[x.index,"Event"].str.contains("Record")].sum())
).reset_index()
daily["Charging"] = daily["Charging_h"].apply(format_duration)
daily["Power"] = daily["Power_h"].apply(format_duration)
daily["Record"] = daily["Record_h"].apply(format_duration)
st.dataframe(daily[["Camera","Date","Charging","Power","Record"]])
download_buttons(daily,"DailySummary")
