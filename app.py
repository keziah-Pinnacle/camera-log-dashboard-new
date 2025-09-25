# app.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("Camera Log Monitoring Dashboard")

# ---- Config ----
EVENT_NORMALIZE = {
    "Battery Charging": "Battery Charging",
    "Battery Charge Stop": "Battery Charge Stop",
    "System Power On": "Power On",
    "System Power Off": "Power Off",
    "Start Record": "Start Record",
    "Stop Record": "Stop Record",
    "Start Pre Record": "Start PreRecord",
    "Stop PreRecord": "Stop PreRecord",
    "USB Remove": "USB Removed",
    "USB Command": "USB Command",
}
EVENT_COLORS = {
    "Battery Charging": "#4A90E2",
    "Battery Charge Stop": "#2B7BE4",
    "Power On": "#2ECC71",
    "Power Off": "#E94B35",
    "Start Record": "#FF7F50",
    "Stop Record": "#E94B35",
    "Start PreRecord": "#7B61FF",
    "Stop PreRecord": "#17BECF",
    "USB Removed": "#6E6E6E",
    "USB Command": "#999999",
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
            cam_short = cam.split("-")[0]  # keep only first 6 digits
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
    df2["StartTime"] = df2["Start"].dt.time
    return df2

def format_hhmm(hours):
    m = int(round(hours*60))
    return f"{m//60}h {m%60}m"

def download_buttons(df,name):
    csv = df.to_csv(index=False).encode()
    st.download_button(f"Download {name} CSV", csv, f"{name}.csv")
    buf = BytesIO()
    with pd.ExcelWriter(buf,engine="openpyxl") as w:
        df.to_excel(w,index=False,sheet_name=name[:31])
    st.download_button(f"Download {name} Excel", buf.getvalue(), f"{name}.xlsx")

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
for _,r in sessions[sessions["Event"].str.contains("Charging")].iterrows():
    fig.add_trace(go.Bar(
        x=[r["Date"]], y=[r["Duration_h"]],
        marker_color=EVENT_COLORS.get(r["Event"],"#999"),
        name=r["Event"],
        hovertext=f"{r['Camera']}<br>{r['Start']} - {r['End']}<br>{format_hhmm(r['Duration_h'])}"
    ))
fig.update_layout(barmode="stack",yaxis_title="Hours",xaxis_title="Date",template="plotly_white")
st.plotly_chart(fig,use_container_width=True)
summary = sessions[sessions["Event"].str.contains("Charging")].groupby(["Camera","Date"])["Duration_h"].sum().reset_index()
summary["TotalCharging"] = summary["Duration_h"].apply(format_hhmm)
st.write("Charging Summary")
st.dataframe(summary[["Camera","Date","TotalCharging"]])
download_buttons(summary,"ChargingSummary")

# ---- Power ----
st.header("Power On / Off")
fig = go.Figure()
for _,r in sessions[sessions["Event"].str.contains("Power")].iterrows():
    fig.add_trace(go.Bar(
        x=[r["Date"]], y=[r["Start"].hour + r["Start"].minute/60],
        marker_color=EVENT_COLORS.get(r["Event"],"#999"),
        name=r["Event"],
        hovertext=f"{r['Camera']} {r['Event']} {r['Start']}"
    ))
fig.update_layout(yaxis_title="Time of Day (h)",xaxis_title="Date",template="plotly_white")
st.plotly_chart(fig,use_container_width=True)

# ---- Recording ----
st.header("Recording / PreRecord")
fig = go.Figure()
for _,r in sessions[sessions["Event"].str.contains("Record")].iterrows():
    fig.add_trace(go.Bar(
        x=[r["Date"]], y=[r["Start"].hour + r["Start"].minute/60],
        marker_color=EVENT_COLORS.get(r["Event"],"#999"),
        name=r["Event"],
        hovertext=f"{r['Camera']} {r['Event']} {r['Start']} ({r['StartBat']}%)"
    ))
fig.update_layout(yaxis_title="Time of Day (h)",xaxis_title="Date",template="plotly_white")
st.plotly_chart(fig,use_container_width=True)

# ---- Daily Summary (last) ----
st.header("Daily Summary")
st.write("This is the overall summary of events for the selected logs.")
daily = sessions.groupby(["Camera","Date"]).agg(
    Charging_h=("Duration_h",lambda x:x[sessions.loc[x.index,"Event"].str.contains("Charging")].sum())
).reset_index()
daily["TotalCharging"] = daily["Charging_h"].apply(format_hhmm)
st.dataframe(daily[["Camera","Date","TotalCharging"]])
download_buttons(daily,"DailySummary")
