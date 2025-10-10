import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="🎥 Real Monitoring Dashboard", layout="wide")

# ---------- Theme & Style ----------
st.markdown("""
<style>
body {background-color:#f9fbfd; color:#1a1a1a; font-family:'Segoe UI';}
.stButton>button {background-color:#0078D4; color:white; border-radius:6px; font-weight:600;}
.stTabs [data-baseweb="tab-list"] {background-color:#eef3fa; border-radius:10px;}
.stTabs [data-baseweb="tab"] {color:#004578; font-weight:600;}
table {font-size:14px;}
</style>
""", unsafe_allow_html=True)

st.title("🎥 Real Monitoring Dashboard")

# ---------- Upload ----------
files = st.file_uploader("Upload Log Files", type=["txt", "log"], accept_multiple_files=True)
if not files:
    st.stop()

# ---------- Parse Logs ----------
def parse_logs(files):
    rows = []
    for file in files:
        for line in file:
            line = line.decode("utf-8", errors="ignore").strip()
            if not line or "#" not in line:
                continue
            try:
                ts_str = line.split("#")[0].strip()
                timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                cam_id = line.split("#ID:")[1].split("-")[0]
                event = line.split("#")[-1].strip()
                battery = None
                if "Battery Level" in line:
                    battery = int(line.split("Battery Level -")[-1].replace("%", "").strip())
                rows.append({"timestamp": timestamp, "camera": cam_id, "event": event, "battery": battery})
            except Exception:
                continue
    return pd.DataFrame(rows)

df = parse_logs(files)
if df.empty:
    st.error("No valid entries found.")
    st.stop()

# ---------- Camera Selection ----------
cam = st.selectbox("Select Camera", sorted(df["camera"].unique()))
df = df[df["camera"] == cam].sort_values("timestamp")

# ---------- Helpers ----------
def duration_fmt(start, end):
    delta = (end - start).total_seconds()
    if delta < 60:
        return f"{int(delta)} sec"
    elif delta < 3600:
        return f"{int(delta//60)} min"
    else:
        h, m = divmod(int(delta//60), 60)
        return f"{h}h {m}m"

def export_excel(dataframe, name):
    buf = BytesIO()
    dataframe.to_excel(buf, index=False)
    buf.seek(0)
    st.download_button(f"📥 {name}", buf, f"{name}.xlsx", use_container_width=False)

# ---------- Tabs ----------
tab1, tab2, tab3 = st.tabs(["⚡ Charging", "🔌 Power", "🎥 Recording"])

# ---------- CHARGING ----------
with tab1:
    st.subheader("⚡ Charging Sessions")
    charge_sessions = []
    charge_start = None

    for _, row in df.iterrows():
        event_text = str(row["event"])
        if "Battery Charging" in event_text and charge_start is None:
            charge_start = row
        elif "Battery Charging" not in event_text and charge_start is not None:
            charge_sessions.append({
                "Camera": cam,
                "Start": charge_start["timestamp"],
                "End": row["timestamp"],
                "Start Battery": charge_start["battery"],
                "End Battery": row["battery"],
                "Duration": duration_fmt(charge_start["timestamp"], row["timestamp"])
            })
            charge_start = None

    if charge_sessions:
        chg = pd.DataFrame(charge_sessions)
        fig = go.Figure()
        for _, r in chg.iterrows():
            fig.add_trace(go.Bar(
                x=[(r["End"] - r["Start"]).seconds / 3600],
                y=[r["Start"].strftime("%Y-%m-%d %H:%M")],
                orientation='h',
                name="Charging",
                marker=dict(color="lightgreen", line=dict(color="green", width=2)),
                hovertemplate=(
                    f"<b>Start:</b> {r['Start']}<br>"
                    f"<b>End:</b> {r['End']}<br>"
                    f"<b>Battery:</b> {r['Start Battery']}%-{r['End Battery']}%<br>"
                    f"<b>Duration:</b> {r['Duration']}"
                )
            ))
        fig.update_layout(
            xaxis_title="Charging Hours",
            yaxis_title="Start Time",
            template="plotly_white",
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(chg)
        export_excel(chg, "Charging_Summary.xlsx")
    else:
        st.info("No Charging Sessions found.")

# ---------- POWER ----------
with tab2:
    st.subheader("🔌 Power On / Off")
    power_on = df[df["event"].str.contains("Power On", case=False, na=False)]
    power_off = df[df["event"].str.contains("Power Off", case=False, na=False)]

    if not power_on.empty or not power_off.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=power_on["timestamp"],
            y=[1]*len(power_on),
            mode="markers",
            marker=dict(color="green", size=10),
            name="Power On",
            hovertemplate="<b>Power On:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=power_on["battery"]
        ))
        fig.add_trace(go.Scatter(
            x=power_off["timestamp"],
            y=[0]*len(power_off),
            mode="markers",
            marker=dict(color="red", size=10, symbol="x"),
            name="Power Off",
            hovertemplate="<b>Power Off:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=power_off["battery"]
        ))
        fig.update_layout(
            xaxis_title="Time",
            yaxis=dict(tickvals=[0,1], ticktext=["Off","On"]),
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)

        summary = pd.concat([
            power_on[["timestamp", "battery"]].rename(columns={"timestamp":"Power On", "battery":"Battery On"}),
            power_off[["timestamp", "battery"]].rename(columns={"timestamp":"Power Off", "battery":"Battery Off"})
        ], axis=1)
        st.dataframe(summary)
        export_excel(summary, "Power_Summary.xlsx")
    else:
        st.info("No Power On/Off Events found.")

# ---------- RECORDING ----------
with tab3:
    st.subheader("🎥 Recording Sessions")
    rec_on = df[df["event"].str.contains("Start Record", case=False, na=False)]
    rec_off = df[df["event"].str.contains("Stop Record", case=False, na=False)]

    if not rec_on.empty or not rec_off.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=rec_on["timestamp"],
            y=[1]*len(rec_on),
            mode="markers",
            marker=dict(color="blue", size=10),
            name="Start Record",
            hovertemplate="<b>Start:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=rec_on["battery"]
        ))
        fig.add_trace(go.Scatter(
            x=rec_off["timestamp"],
            y=[0]*len(rec_off),
            mode="markers",
            marker=dict(color="darkred", size=10, symbol="x"),
            name="Stop Record",
            hovertemplate="<b>Stop:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=rec_off["battery"]
        ))
        fig.update_layout(
            xaxis_title="Time",
            yaxis=dict(tickvals=[0,1], ticktext=["Stopped","Recording"]),
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)

        rec_summary = pd.concat([
            rec_on[["timestamp", "battery"]].rename(columns={"timestamp":"Start Record", "battery":"Battery Start"}),
            rec_off[["timestamp", "battery"]].rename(columns={"timestamp":"Stop Record", "battery":"Battery Stop"})
        ], axis=1)
        st.dataframe(rec_summary)
        export_excel(rec_summary, "Recording_Summary.xlsx")
    else:
        st.info("No Recording Events found.")
