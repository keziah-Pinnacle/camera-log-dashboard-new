import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import re

# Page config
st.set_page_config(page_title="Camera Log Dashboard", layout="wide")

# Color function for battery health
def get_color(bat):
    if bat <= 20:
        return 'red'
    elif bat <= 60:
        return 'orange'
    else:
        return 'green'

# Title
st.title("Camera Log Dashboard")

# File uploader
uploaded_files = st.file_uploader("Upload log files (.txt from cameras)", type="txt", accept_multiple_files=True)

if len(uploaded_files) > 0:
    # Parse logs
    all_data = []
    unique_cameras = set()
    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        log_content = uploaded_file.read().decode('utf-8')
        lines = log_content.strip().split('\n')
        
        camera_match = re.search(r'(\d{6})', filename)
        default_camera = camera_match.group(1) if camera_match else 'Unknown'
        
        for line in lines:
            line = line.strip()
            if not line or '#' not in line:
                continue
            try:
                parts = line.split('#')
                timestamp_str = parts[0].strip()
                event_parts = [p.strip() for p in parts[2:] if p.strip()]
                full_event = ' '.join(event_parts) if event_parts else 'Unknown'
                
                normalized_event = full_event.split(' - Battery Level - ')[0].strip() if ' - Battery Level - ' in full_event else full_event
                
                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                
                battery = None
                if 'Battery Level -' in full_event:
                    battery_str = full_event.split('Battery Level -')[-1].strip().rstrip('%').strip()
                    battery = int(battery_str) if battery_str.isdigit() else None
                
                id_match = re.search(r'#ID:(\d{6})-\d{6}', line)
                camera = id_match.group(1) if id_match else default_camera
                unique_cameras.add(camera)
                
                all_data.append({
                    'timestamp': dt,
                    'event': full_event,
                    'normalized_event': normalized_event,
                    'battery': battery,
                    'camera': camera
                })
            except:
                continue
    
    if not all_data:
        st.error("No valid log entries. Check format.")
    else:
        df = pd.DataFrame(all_data)
        df = df.sort_values('timestamp')
        
        # Date range filter
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=df['timestamp'].min().date())
        with col2:
            end_date = st.date_input("End Date", value=df['timestamp'].max().date())
        date_mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
        filtered_df = df[date_mask]
        
        # Camera filter
        selected_cameras = st.multiselect("Choose Camera ID", options=sorted(list(unique_cameras)), default=list(unique_cameras))
        filtered_df = filtered_df[filtered_df['camera'].isin(selected_cameras)]
        
        # Graph 1: Charging Times per Day
        st.subheader("Charging Times per Day")
        charging_df = filtered_df[filtered_df['normalized_event'].str.contains('Battery Charging', na=False)].copy()
        if not charging_df.empty:
            charging_df['date'] = charging_df['timestamp'].dt.date
            charging_groups = charging_df.groupby('date').agg({
                'timestamp': ['min', 'max'],
                'battery': 'last'
            }).reset_index()
            charging_groups.columns = ['date', 'start_time', 'end_time', 'end_battery']
            charging_groups['duration_hours'] = (charging_groups['end_time'] - charging_groups['start_time']).dt.total_seconds() / 3600
            
            fig1 = go.Figure()
            fig1.add_trace(go.Bar(
                x=charging_groups['date'],
                y=charging_groups['duration_hours'],
                name='Charge Duration',
                marker_color='blue',
                hovertemplate='<b>Charge Duration</b>: %{y:.1f}h<br>Date: %{x}<br>End Battery: %{customdata}%<extra></extra>',
                customdata=charging_groups['end_battery']
            ))
            
            fig1.update_layout(
                xaxis_title="Date",
                yaxis_title="Charge Duration (Hours, 00:00 - 24:00)",
                yaxis=dict(range=[0, 24], tickvals=[0, 6, 12, 18, 24], ticktext=["00:00", "06:00", "12:00", "18:00", "24:00"]),
                template='plotly_white',
                height=400,
                font=dict(size=11, family="Arial"),
                hovermode='x unified',
                barmode='stack'
            )
            
            st.plotly_chart(fig1, use_container_width=True)
            
            # Summary for Graph 1
            st.subheader("Summary for Charging Graph")
            st.text("This graph shows the total duration of charging sessions per day (blue bars). It helps identify how long the camera was charged each day, with bars stacking to reflect multiple charge sessions. Longer or frequent charges may suggest battery health concerns.")
        
        # Graph 2: Power On/Off Timeline
        st.subheader("Power On/Off Timeline")
        power_df = filtered_df[filtered_df['normalized_event'].str.contains('Power On|Power Off', na=False)].copy()
        if not power_df.empty:
            power_df['date'] = power_df['timestamp'].dt.date
            power_df['time'] = power_df['timestamp'].dt.time
            power_df['type'] = power_df['normalized_event'].apply(lambda x: 'Power On' if 'Power On' in x else 'Power Off')
            
            fig2 = go.Figure()
            for typ in ['Power On', 'Power Off']:
                typ_df = power_df[power_df['type'] == typ].groupby('date').agg({'time': 'mean', 'battery': 'mean'}).reset_index()
                typ_df['time_hours'] = typ_df['time'].apply(lambda t: t.hour + t.minute/60 + t.second/3600)
                fig2.add_trace(go.Bar(
                    x=typ_df['date'],
                    y=typ_df['time_hours'],
                    name=typ,
                    marker_color='green' if typ == 'Power On' else 'red',
                    hovertemplate='<b>%{data.name}</b><br>Date: %{x}<br>Avg Time: %{y|%H:%M}<br>Avg Battery: %{customdata:.1f}%<extra></extra>',
                    customdata=typ_df['battery']
                ))
            
            fig2.update_layout(
                xaxis_title="Date",
                yaxis_title="Average Time (00:00 - 24:00)",
                yaxis=dict(tickvals=list(range(0, 25)), ticktext=[f"{h:02d}:00" for h in range(0, 25)]),
                template='plotly_white',
                height=400,
                font=dict(size=11, family="Arial"),
                hovermode='x unified',
                barmode='group'
            )
            
            st.plotly_chart(fig2, use_container_width=True)
            
            # Summary for Graph 2
            st.subheader("Summary for Power On/Off Graph")
            st.text("This graph shows the average time of power on (green bars) and power off (red bars) per day. Hover to see average battery levels at these events. It helps track daily usage patterns and battery status, with multiple events indicating frequent use.")
            avg_on_bat = power_df[power_df['type'] == 'Power On']['battery'].mean()
            avg_off_bat = power_df[power_df['type'] == 'Power Off']['battery'].mean()
            st.text(f"Average battery at power on: {avg_on_bat:.1f}% \nAverage battery at power off: {avg_off_bat:.1f}%")
        
        # Graph 3: Recording Status Timeline
        st.subheader("Recording Status Timeline")
        recording_df = filtered_df[filtered_df['normalized_event'].str.contains('Start Record|Stop Record|Pre-Record', na=False)].copy()
        if not recording_df.empty:
            recording_df['date'] = recording_df['timestamp'].dt.date
            recording_df['time'] = recording_df['timestamp'].dt.time
            recording_df['type'] = recording_df['normalized_event'].apply(lambda x: 'Pre-Record' if 'Pre-Record' in x else 'Record' if 'Start Record' in x or 'Stop Record' in x else 'Stop Record')
            recording_df['color'] = recording_df['battery'].apply(get_color)
            
            fig3 = go.Figure()
            for typ in ['Pre-Record', 'Record']:
                typ_df = recording_df[recording_df['type'] == typ].groupby('date').agg({'time': 'mean', 'battery': 'mean'}).reset_index()
                typ_df['time_hours'] = typ_df['time'].apply(lambda t: t.hour + t.minute/60 + t.second/3600)
                fig3.add_trace(go.Bar(
                    x=typ_df['date'],
                    y=typ_df['time_hours'],
                    name=typ,
                    marker_color=typ_df['color'],
                    hovertemplate='<b>%{data.name}</b><br>Date: %{x}<br>Avg Time: %{y|%H:%M}<br>Avg Battery: %{customdata:.1f}%<extra></extra>',
                    customdata=typ_df['battery']
                ))
            
            fig3.update_layout(
                xaxis_title="Date",
                yaxis_title="Average Time (00:00 - 12:00)",
                yaxis=dict(tickvals=list(range(0, 13)), ticktext=[f"{h:02d}:00" for h in range(0, 13)]),
                template='plotly_white',
                height=400,
                font=dict(size=11, family="Arial"),
                hovermode='x unified',
                barmode='group'
            )
            
            st.plotly_chart(fig3, use_container_width=True)
            
            # Summary for Graph 3
            st.subheader("Summary for Recording Graph")
            st.text("This graph shows average times for pre-record (lightblue bars) and recording (blue bars) per day, with colors indicating battery health (green >60%, amber 20-60%, red <20%). Hover for battery levels. It helps assess battery life during 8-12 hour shifts and health from 100%.")
            avg_rec_bat = recording_df['battery'].mean()
            st.text(f"Average battery during recording: {avg_rec_bat:.1f}%")
else:
    st.info("Upload .txt log files to start.")