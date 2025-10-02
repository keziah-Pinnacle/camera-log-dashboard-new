# app.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime
import plotly.graph_objects as go
from io import BytesIO
import traceback

# ---- Streamlit Config ----
st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.markdown("""
    <style>
    body { background-color: #1E1E1E; color: #F0F0F0; font-family: 'Segoe UI', sans-serif; }
    h1, h2, h3 { color: #00BFFF; }
    .stButton>button { background-color: #00BFFF; color: white; border-radius: 8px; }
    .stDownloadButton>button { background-color: #1ABC9C; color: white; border-radius: 8px; font-size: 13px; padding: 0.3em 1em; }
    .stDataFrame { background-color: #2A2A2A; }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1>📹 Real-Time Camera Monitoring Dashboard</h1>", unsafe_allow_html=True)

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
    "Stop Pre Record": "Stop PreRecord",
}
EVENT_COLORS = {
    "Start Charge": "#3498DB",
    "Stop Charge": "#1ABC9C",
    "Power On": "#2ECC71",
    "Power Off": "#E74C3C",
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

# ---- Parsing ----
def parse_logs(files):
    pat = re.compile(
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+#ID:([0-9A-Za-z\-]+)\s+#(.*?)\s*(?:-.*Battery Level\s*-\s*(\d+)%\s*)?$"
    )
    rows = []
    for f in files:
        text = f.read().decode("utf-8", errors="ignore")
        for ln in text.splitlines():
            m = pat.search(ln.strip())
            if not m: continue
            ts_s, cam_raw, ev_raw, bat = m.groups()
            try: ts = datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S")
            except: continue
            cam_short = cam_raw.split("-")[0]
            rows.append({
                "timestamp": ts,
                "camera": cam_short,
                "event": human_event(ev_raw),
                "battery": int(bat) if bat else None
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["camera", "timestamp"]).reset_index(drop=True)
    return df

def compress_sessions(df):
    out = []
    for cam, g in df.groupby("camera"):
        g = g.reset_index(drop=True)
        cur_ev, cur_start, cur_bat = g.loc[0,"event"], g.loc[0,"timestamp"], g.loc[0,"battery"]
        for i in range(1,len(g)):
            if g.loc[i,"event"]!=cur_ev:
                out.append([cam, cur_ev, cur_start, g.loc[i-1,"timestamp"], cur_bat, g.loc[i-1,"battery"]])
                cur_ev, cur_start, cur_bat = g.loc[i,"event"], g.loc[i,"timestamp"], g.loc[i,"battery"]
        out.append([cam, cur_ev, cur_start, g.loc[len(g)-1,"timestamp"], cur_bat, g.loc[len(g)-1,"battery"]])
    df2 = pd.DataFrame(out, columns=["Camera","Event","Start","End","StartBat","EndBat"])
    df2["Duration_h"] = (df2["End"]-df2["Start"]).dt.total_seconds()/3600
    df2["Date"] = df2["Start"].dt.date
    return df2

def fmt_duration(h):
    m=int(h*60)
    return f"{m}m" if m<60 else f"{m//60}h {m%60}m"

def download(df,name,key):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇ {name} CSV", csv, f"{name}.csv", key=f"{name}_csv_{key}")
    buf = BytesIO()
    with pd.ExcelWriter(buf,engine="openpyxl") as w: df.to_excel(w,index=False,sheet_name=name[:31])
    st.download_button(f"⬇ {name} Excel", buf.getvalue(), f"{name}.xlsx", key=f"{name}_xls_{key}")

# ---- UI ----
files = st.sidebar.file_uploader("📂 Upload logs", type=["txt","log"], accept_multiple_files=True)
if not files: st.stop()
df = parse_logs(files)
if df.empty: st.error("No data parsed"); st.stop()
sessions = compress_sessions(df)

# filters
min_d,max_d = df["timestamp"].min().date(), df["timestamp"].max().date()
date_range = st.sidebar.date_input("📅 Date Range", [min_d,max_d], min_value=min_d, max_value=max_d)
start,end = date_range
cams = sessions["Camera"].unique().tolist()
sel_cams = st.sidebar.multiselect("🎥 Cameras", cams, default=cams)
sessions = sessions[sessions["Camera"].isin(sel_cams)]
sessions = sessions[(sessions["Date"]>=start)&(sessions["Date"]<=end)]

# ---- Tabs ----
tab1,tab2,tab3,tab4,tab5 = st.tabs(["Overview","Charging","Power","Recording","Daily Summary"])

with tab1:
    st.subheader("📊 Overview")
    st.metric("Total Cameras", len(sel_cams))
    st.metric("Sessions", len(sessions))

with tab2:
    st.subheader("🔋 Charging")
    sel = sessions[sessions["Event"].str.contains("Charge")]
    if not sel.empty:
        fig = go.Figure()
        used=set()
        for _,r in sel.iterrows():
            show = r["Event"] not in used
            used.add(r["Event"])
            fig.add_trace(go.Bar(
                x=[r["Start"]], y=[r["Duration_h"]],
                marker_color=EVENT_COLORS[r["Event"]],
                name=r["Event"] if show else None,
                hovertext=f"{r['Camera']} | {r['Start']} → {r['End']} | {fmt_duration(r['Duration_h'])}"
            ))
        fig.update_layout(barmode="stack", yaxis_title="Hours", xaxis_title="DateTime", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True, key="charge")
        # summary: merge start/stop into one row called Charge Time
        summary = sel.copy()
        summary["Duration"] = summary["Duration_h"].apply(fmt_duration)
        charge_tbl = summary.groupby(["Camera","Date"]).agg(Start=("Start","min"),End=("End","max"),Duration=("Duration_h","sum")).reset_index()
        charge_tbl["Duration"] = charge_tbl["Duration"].apply(fmt_duration)
        st.dataframe(charge_tbl[["Camera","Date","Start","End","Duration"]])
        download(charge_tbl,"ChargeSummary","charge")

with tab3:
    st.subheader("⚡ Power")
    sel = sessions[sessions["Event"].str.contains("Power")]
    if not sel.empty:
        fig = go.Figure()
        used=set()
        for _,r in sel.iterrows():
            show = r["Event"] not in used
            used.add(r["Event"])
            fig.add_trace(go.Bar(
                x=[r["Start"]], y=[r["Duration_h"]*60],
                marker_color=EVENT_COLORS[r["Event"]],
                name=r["Event"] if show else None,
                hovertext=f"{r['Camera']} | {r['Start']} → {r['End']} | {fmt_duration(r['Duration_h'])}"
            ))
        fig.update_layout(barmode="stack", yaxis_title="Minutes", xaxis_title="DateTime", template="plotly_dark")
        st.plotly_chart(fig,use_container_width=True,key="power")
        power_tbl = sel.copy()
        power_tbl["Duration"] = power_tbl["Duration_h"].apply(fmt_duration)
        st.dataframe(power_tbl[["Camera","Event","Start","End","Duration"]])
        download(power_tbl,"PowerSummary","power")

with tab4:
    st.subheader("🎬 Recording / PreRecord")
    sel = sessions[sessions["Event"].str.contains("Record")]
    if not sel.empty:
        fig = go.Figure()
        used=set()
        for _,r in sel.iterrows():
            show = r["Event"] not in used
            used.add(r["Event"])
            fig.add_trace(go.Bar(
                x=[r["Start"]], y=[r["Duration_h"]*60],
                marker_color=EVENT_COLORS[r["Event"]],
                name=r["Event"] if show else None,
                hovertext=f"{r['Camera']} | {r['Start']} → {r['End']} | {fmt_duration(r['Duration_h'])}"
            ))
        fig.update_layout(barmode="stack", yaxis_title="Minutes", xaxis_title="DateTime", template="plotly_dark")
        st.plotly_chart(fig,use_container_width=True,key="rec")
        rec_tbl = sel.copy()
        rec_tbl["Duration"] = rec_tbl["Duration_h"].apply(fmt_duration)
        st.dataframe(rec_tbl[["Camera","Event","Start","End","Duration"]])
        download(rec_tbl,"RecordingSummary","rec")

with tab5:
    st.subheader("📑 Daily Summary")
    daily = sessions.groupby(["Camera","Date"]).apply(lambda g: pd.Series({
        "Charging_h": g.loc[g["Event"].str.contains("Charge"),"Duration_h"].sum(),
        "Power_h": g.loc[g["Event"].str.contains("Power"),"Duration_h"].sum(),
        "Record_h": g.loc[g["Event"].str.contains("Record"),"Duration_h"].sum()
    })).reset_index()
    daily["Charging"] = daily["Charging_h"].apply(fmt_duration)
    daily["Power"] = daily["Power_h"].apply(fmt_duration)
    daily["Record"] = daily["Record_h"].apply(fmt_duration)
    st.dataframe(daily[["Camera","Date","Charging","Power","Record"]])
    download(daily,"DailySummary","daily")
