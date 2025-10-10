import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="🎥 Real Monitoring Dashboard", layout="wide")

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

# ---------- File upload ----------
files = st.file_uploader("Upload Log Files", type=["txt", "log"], accept_multiple_files=True)
if not files:
    st.stop()

# ---------- Parse logs ----------
def parse_logs(files):
    data = []
    for file in files:
        for line in file:
            line = line.decode("utf-8", errors="ignore").strip()
            if not line or "#" not in line:
                continue
            try:
                ts_str = line.split("#")[0].strip()
                dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                cam_id = line.split("#ID:")[1].split("-")[0]
                event = line.split("#")[-1].strip()
                battery = None
                if "Battery Level" in line:
                    battery = int(line.split("Battery Level -")[-1].replace("%", "").strip())
                data.append({"timestamp": dt, "camera": cam_id, "event": event, "battery": battery})
            except Exception:
                continue
    return pd.DataFrame(data)

df = parse_logs(files)
if df.empty:
    st.error("No valid entries found.")
    st.stop()

# ---------- Camera filter ----------
cam = st.selectbox("Select Camera", sorted(df["camera"].unique()))
df = df[df["camera"] == cam].sort_values("timestamp")

# ---------- Helper ----------
def get_duration(start, end):
    diff = (end - start).total_seconds()
    if diff < 60:
        return f"{int(diff)} sec"
    elif diff < 3600:
        return f"{int(diff//60)} min"
    else:
        h, m = divmod(int(diff//60), 60)
        return f"{h}h {m}m"

def export_btn(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    st.download_button(f"📥 Download {name}", buf, f"{name}.xlsx", use_container_width=False)

# ---------- CHARGING ----------
charge_sessions = []
charge_start = None
for _, row in df.iterrows():
    if "Battery Charging" in row["event"] and not charge_start:
        charge_start = row
    elif "Battery Charging" not in row["event"] and charge_start:
        charge_sessions.append({
            "Camera": cam,
            "Start": charge_start["timestamp"],
            "End": row["timestamp"],
            "Start Battery": charge_start["battery"],
            "End Battery": row["battery"],
            "Duration": get_duration(charge_start["timestamp"], row["timestamp"])
        })
        charge_start = None

tab1, tab2, tab3 = st.tabs(["⚡ Charging", "🔌 Power On/Off", "🎥 Recording"])

# ---------- CHARGING GRAPH ----------
with tab1:
    st.subheader("⚡ Charging Sessions")
    if charge_sessions:
        chg = pd.DataFrame(charge_sessions)
        fig = go.Figure()
        for _, r in chg.iterrows():
            fig.add_trace(go.Bar(
                x=[(r["End"] - r["Start"]).seconds / 3600],
                y=[r["Start"].strftime("%Y-%m-%d %H:%M")],
                orientation='h',
                name="Charge",
                marker=dict(color="lightgreen", line=dict(color="green", width=2)),
                hovertemplate=(
                    f"<b>Start:</b> {r['Start']}<br>"
                    f"<b>End:</b> {r['End']}<br>"
                    f"<b>Battery:</b> {r['Start Battery']}%-{r['End Battery']}%<br>"
                    f"<b>Duration:</b> {r['Duration']}"
                )
            ))
        fig.update_layout(xaxis_title="Charging Hours", yaxis_title="Session Start Time",
                          template="plotly_white", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(chg[["Camera", "Start", "End", "Start Battery", "End Battery", "Duration"]])
        export_btn(chg, "Charging_Summary")
    else:
        st.info("No charging sessions found.")

# ---------- POWER GRAPH ----------
with tab2:
    st.subheader("🔌 Power On/Off Events")
    power_on = df[df["event"].str.contains("Power On", case=False, na=False)]
    power_off = df[df["event"].str.contains("Power Off", case=False, na=False)]
    if not power_on.empty or not power_off.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=power_on["timestamp"], y=[1]*len(power_on),
            mode="markers", marker=dict(color="green", size=10),
            name="Power On",
            hovertemplate="<b>Power On:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=power_on["battery"]
        ))
        fig.add_trace(go.Scatter(
            x=power_off["timestamp"], y=[0]*len(power_off),
            mode="markers", marker=dict(color="red", size=10, symbol="x"),
            name="Power Off",
            hovertemplate="<b>Power Off:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=power_off["battery"]
        ))
        fig.update_layout(template="plotly_white", xaxis_title="Time", yaxis_title="Status",
                          yaxis=dict(tickvals=[0,1], ticktext=["Off","On"]),
                          showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(pd.concat([power_on[["timestamp","battery"]].rename(columns={"timestamp":"Power On"}), 
                                power_off[["timestamp","battery"]].rename(columns={"timestamp":"Power Off"})], axis=1))
        export_btn(power_on, "Power_Events")
    else:
        st.info("No Power On/Off events found.")

# ---------- RECORDING GRAPH ----------
with tab3:
    st.subheader("🎥 Recording Events")
    rec_on = df[df["event"].str.contains("Start Record", case=False, na=False)]
    rec_off = df[df["event"].str.contains("Stop Record", case=False, na=False)]
    if not rec_on.empty or not rec_off.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=rec_on["timestamp"], y=[1]*len(rec_on),
            mode="markers", marker=dict(color="blue", size=10),
            name="Start Record",
            hovertemplate="<b>Start:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=rec_on["battery"]
        ))
        fig.add_trace(go.Scatter(
            x=rec_off["timestamp"], y=[0]*len(rec_off),
            mode="markers", marker=dict(color="darkred", size=10, symbol="x"),
            name="Stop Record",
            hovertemplate="<b>Stop:</b> %{x}<br><b>Battery:</b> %{customdata}%",
            customdata=rec_off["battery"]
        ))
        fig.update_layout(template="plotly_white", xaxis_title="Time", yaxis_title="Status",
                          yaxis=dict(tickvals=[0,1], ticktext=["Stopped","Recording"]),
                          showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(pd.concat([rec_on[["timestamp","battery"]].rename(columns={"timestamp":"Start Record"}), 
                                rec_off[["timestamp","battery"]].rename(columns={"timestamp":"Stop Record"})], axis=1))
        export_btn(rec_on, "Recording_Events")
    else:
        st.info("No Recording events found.")
