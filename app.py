# app.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

st.set_page_config(page_title="Camera Log Dashboard", layout="wide")
st.title("Camera Log Monitoring Dashboard")

# ---------------------------
# Helpers
# ---------------------------
def parse_logs(uploaded_files):
    rows = []
    pat = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+#ID:(\d{6}-\d{6})\s+#(.*?)\s*-\s*Battery Level\s*-\s*(\d+)%")
    for f in uploaded_files:
        text = f.read().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            m = pat.search(line.strip())
            if m:
                ts, cam, ev, bat = m.groups()
                rows.append({
                    "timestamp": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                    "camera": cam,
                    "event": ev.strip(),
                    "battery": int(bat)
                })
    return pd.DataFrame(rows)

def compress_events(df):
    out = []
    df = df.sort_values(["camera","timestamp"]).reset_index(drop=True)
    if df.empty: return pd.DataFrame()
    cur_cam, cur_ev = df.loc[0,"camera"], df.loc[0,"event"]
    start, start_bat = df.loc[0,"timestamp"], df.loc[0,"battery"]
    end, end_bat = start, start_bat
    for i in range(1,len(df)):
        r = df.loc[i]
        if r["camera"]==cur_cam and r["event"]==cur_ev:
            end, end_bat = r["timestamp"], r["battery"]
        else:
            out.append([cur_cam, cur_ev, start, end, start_bat, end_bat])
            cur_cam, cur_ev = r["camera"], r["event"]
            start, start_bat = r["timestamp"], r["battery"]
            end, end_bat = start, start_bat
    out.append([cur_cam, cur_ev, start, end, start_bat, end_bat])
    df2 = pd.DataFrame(out, columns=["Camera","Event","Start","End","StartBat","EndBat"])
    df2["Duration_h"] = (df2["End"]-df2["Start"]).dt.total_seconds()/3600
    return df2

def plot_sessions(df, title, color):
    """df must have Camera, Start, End, StartBat, EndBat"""
    if df.empty:
        st.info(f"No {title.lower()} sessions found.")
        return
    fig = go.Figure()
    for cam, g in df.groupby("Camera"):
        for _,r in g.iterrows():
            fig.add_trace(go.Bar(
                x=[(r["End"]-r["Start"]).total_seconds()/3600],
                y=[f"{cam} {r['Start'].date()}"],
                orientation="h",
                base=(r["Start"].hour+r["Start"].minute/60),
                marker_color=color,
                hovertemplate=(
                    f"Camera: {cam}<br>"
                    f"Start: {r['Start']} ({r['StartBat']}%)<br>"
                    f"End: {r['End']} ({r['EndBat']}%)<br>"
                    f"Duration: {r['Duration_h']:.2f}h<extra></extra>"
                )
            ))
    fig.update_layout(
        title=title,
        xaxis_title="Duration (hours)",
        yaxis_title="Camera/Date",
        barmode="stack",
        bargap=0.2,
        template="plotly_white",
        height=400
    )
    st.plotly_chart(fig, width="stretch")

def download_df(df, name):
    # CSV
    st.download_button(f"Download {name} CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{name.lower().replace(' ','_')}.csv",
        mime="text/csv"
    )
    # Excel with openpyxl
    towrite = BytesIO()
    with pd.ExcelWriter(towrite, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=name)
    towrite.seek(0)
    st.download_button(f"Download {name} Excel",
        data=towrite,
        file_name=f"{name.lower().replace(' ','_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ---------------------------
# Main
# ---------------------------
files = st.file_uploader("Upload log files", type=["txt","log"], accept_multiple_files=True)
if not files: st.stop()
df = parse_logs(files)
if df.empty: 
    st.error("No valid log entries.")
    st.stop()

# Compressed table
comp = compress_events(df)
st.subheader("Event Table (compressed)")
st.dataframe(comp, width="stretch")
download_df(comp,"Event Table")

# Charging
charging = comp[comp["Event"].str.contains("Charging",case=False,na=False)]
st.subheader("Charging Sessions")
plot_sessions(charging,"Charging Sessions","lightblue")

# Power
power = comp[comp["Event"].str.contains("Power",case=False,na=False)]
st.subheader("Power Sessions")
plot_sessions(power,"Power On/Off","lightgreen")

# Recording
rec = comp[comp["Event"].str.contains("Record",case=False,na=False)]
st.subheader("Recording Sessions")
plot_sessions(rec,"Recording/Pre-Recording","lightcoral")

# Daily summary
if not comp.empty:
    comp["Date"] = comp["Start"].dt.date
    summary = comp.groupby(["Camera","Date"]).agg(
        Total_Charging_h=("Duration_h", lambda x: x[comp["Event"].str.contains("Charging")].sum()),
        Total_Power_h=("Duration_h", lambda x: x[comp["Event"].str.contains("Power")].sum()),
        Total_Record_h=("Duration_h", lambda x: x[comp["Event"].str.contains("Record")].sum())
    ).reset_index()
    st.subheader("Daily Summary")
    st.dataframe(summary, width="stretch")
    download_df(summary,"Daily Summary")

# Low battery
low = df[df["battery"]<20]
if not low.empty:
    st.subheader("Low Battery Alerts")
    st.dataframe(low, width="stretch")
