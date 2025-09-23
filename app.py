import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import re

# Page config
st.set_page_config(page_title="Camera Log Dashboard", layout="wide")

# Color function for battery health and charging states
def get_color(bat, is_resumed=False):
    if bat <= 20:
        return 'red'
    elif bat <= 60:
        return 'orange'
    else:
        return 'darkgreen' if not is_resumed else 'lightblue'  # Different color for resumed charging

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
            charging_df['time'] = charging_df['timestamp'].dt.strftime('%H:%M:%S')
            charging_df = charging_df.sort_values('timestamp')
            charging_df['session'] = (charging_df['timestamp'].diff().dt.total_seconds() > 60).cumsum()  # New session if gap > 1 minute
            charging_groups = charging_df.groupby(['date', 'session']).agg({
                'timestamp': ['min', 'max'],
                'battery': ['first', 'last'],
                'time': ['first', 'last']
            }).reset_index()
            charging_groups.columns = ['date', 'session', 'start_time', 'end_time', 'start_battery', 'end_battery', 'start_time_str', 'end_time_str']
            charging_groups['duration_seconds'] = (charging_groups['end_time'] - charging_groups['start_time']).dt.total_seconds()
            charging_groups['duration_hours'] = charging_groups['duration_seconds'] / 3600
            
            fig1 = go.Figure()
            for _, group in charging_groups.iterrows():
                # Add charging bar (continuous)
                fig1.add_trace(go.Bar(
                    x=[group['date']],
                    y=[group['start_time_str']],
                    width=0.4,
                    marker_color=get_color(group['end_battery'], group['session'] > 0),
                    name='Charging Session',
                    hovertemplate='<b>Start Time</b>: %{y}<br><b>Stop Time</b>: %{customdata[0]}<br><b>Duration</b>: %{customdata[1]:.1f}h<br><b>Battery</b>: %{customdata[2]}% to %{customdata[3]}%<br><b>Date</b>: %{x}<extra></extra>',
                    customdata=[group['end_time_str'], group['duration_hours'], group['start_battery'], group['end_battery']]
                ))
            
            # Ensure all dates in range are shown
            all_dates = pd.date_range(start=charging_df['date'].min(), end=charging_df['date'].max(), freq='D')
            fig1.update_xaxes(type='category', categoryorder='array', categoryarray=all_dates)
            fig1.update_yaxes(
                autorange="reversed",
                tickvals=['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '24:00'],
                ticktext=['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '24:00']
            )
            
            fig1.update_layout(
                xaxis_title="Date",
                yaxis_title="Time",
                template='plotly_white',
                height=400,
                font=dict(size=11, family="Arial"),
                hovermode='x unified',
                barmode='group'
            )
            
            st.plotly_chart(fig1, use_container_width=True)
            
            # Summary for Graph 1
            st.subheader("Summary for Charging Graph")
            st.text(f"Average charging duration: {charging_groups['duration_hours'].mean():.1f} hours")
            st.text("This graph shows charging sessions per day. Hover for details.")
        
        # Graph 2: Power On/Off Timeline
        st.subheader("Power On/Off Timeline")
        power_df = filtered_df[filtered_df['normalized_event'].str.contains('Power On|Power Off', na=False)].copy()
        if not power_df.empty:
            power_df['date'] = power_df['timestamp'].dt.date
            power_df['time'] = power_df['timestamp'].dt.strftime('%H:%M:%S')
            power_df['type'] = power_df['normalized_event'].apply(lambda x: 'Power On' if 'Power On' in x else 'Power Off')
            
            fig2 = go.Figure()
            for date in power_df['date'].unique():
                date_df = power_df[power_df['date'] == date]
                on_df = date_df[date_df['type'] == 'Power On']
                off_df = date_df[date_df['type'] == 'Power Off']
                if not on_df.empty:
                    fig2.add_trace(go.Bar(
                        x=[date],
                        y=on_df['time'],
                        width=0.4,
                        marker_color='lightgreen',
                        name='Power On',
                        hovertemplate='<b>Time</b>: %{y}<br><b>Type</b>: Power On<br><b>Battery</b>: %{customdata:.1f}%<br><b>Date</b>: %{x}<extra></extra>',
                        customdata=on_df['battery']
                    ))
                if not off_df.empty:
                    fig2.add_trace(go.Bar(
                        x=[date],
                        y=off_df['time'],
                        width=0.4,
                        marker_color='lightcoral',
                        name='Power Off',
                        hovertemplate='<b>Time</b>: %{y}<br><b>Type</b>: Power Off<br><b>Battery</b>: %{customdata:.1f}%<br><b>Date</b>: %{x}<extra></extra>',
                        customdata=off_df['battery']
                    ))
            
            # Ensure all dates in range are shown
            all_dates = pd.date_range(start=power_df['date'].min(), end=power_df['date'].max(), freq='D')
            fig2.update_xaxes(type='category', categoryorder='array', categoryarray=all_dates)
            fig2.update_yaxes(
                autorange="reversed",
                tickvals=['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '24:00'],
                ticktext=['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '24:00']
            )
            
            fig2.update_layout(
                xaxis_title="Date",
                yaxis_title="Time",
                template='plotly_white',
                height=400,
                font=dict(size=11, family="Arial"),
                hovermode='x unified',
                barmode='stack'  # Stack red on green
            )
            
            st.plotly_chart(fig2, use_container_width=True)
            
            # Summary for Graph 2
            st.subheader("Summary for Power On/Off Graph")
            st.text(f"Average power on time: {avg_on_time.mean():.1f} hours")
            st.text(f"Average power off time: {avg_off_time.mean():.1f} hours")
            avg_on_bat = power_df[power_df['type'] == 'Power On']['battery'].mean()
            avg_off_bat = power_df[power_df['type'] == 'Power Off']['battery'].mean()
            st.text(f"Average battery at power on: {avg_on_bat:.1f}% \nAverage battery at power off: {avg_off_bat:.1f}%")
            st.text("This graph shows exact power on (lightgreen) and power off (lightcoral) times per day.")
        
        # Graph 3: Recording Status Timeline
        st.subheader("Recording Status Timeline")
        recording_df = filtered_df[filtered_df['normalized_event'].str.contains('Start Record|Stop Record|Pre-Record', na=False)].copy()
        if not recording_df.empty:
            recording_df['date'] = recording_df['timestamp'].dt.date
            recording_df['time'] = recording_df['timestamp'].dt.strftime('%H:%M:%S')
            recording_df['type'] = recording_df['normalized_event'].apply(lambda x: 'Pre-Record' if 'Pre-Record' in x else 'Record' if 'Start Record' in x or 'Stop Record' in x else 'Stop Record')
            
            fig3 = go.Figure()
            for date in recording_df['date'].unique():
                date_df = recording_df[recording_df['date'] == date]
                pre_df = date_df[date_df['type'] == 'Pre-Record']
                rec_df = date_df[date_df['type'] == 'Record']
                if not pre_df.empty:
                    fig3.add_trace(go.Bar(
                        x=[date],
                        y=pre_df['time'],
                        width=0.4,
                        marker_color='lightblue',
                        name='Pre-Record',
                        hovertemplate='<b>Time</b>: %{y}<br><b>Type</b>: Pre-Record<br><b>Battery</b>: %{customdata:.1f}%<br><b>Date</b>: %{x}<extra></extra>',
                        customdata=pre_df['battery']
                    ))
                if not rec_df.empty:
                    fig3.add_trace(go.Bar(
                        x=[date],
                        y=rec_df['time'],
                        width=0.4,
                        marker_color='blue',
                        name='Record',
                        hovertemplate='<b>Time</b>: %{y}<br><b>Type</b>: Record<br><b>Battery</b>: %{customdata:.1f}%<br><b>Date</b>: %{x}<extra></extra>',
                        customdata=rec_df['battery']
                    ))
            
            # Ensure all dates in range are shown
            all_dates = pd.date_range(start=recording_df['date'].min(), end=recording_df['date'].max(), freq='D')
            fig3.update_xaxes(type='category', categoryorder='array', categoryarray=all_dates)
            fig3.update_yaxes(
                autorange="reversed",
                tickvals=['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '24:00'],
                ticktext=['00:00', '03:00', '06:00', '09:00', '12:00', '15:00', '18:00', '21:00', '24:00']
            )
            
            fig3.update_layout(
                xaxis_title="Date",
                yaxis_title="Time",
                template='plotly_white',
                height=400,
                font=dict(size=11, family="Arial"),
                hovermode='x unified',
                barmode='stack'
            )
            
            st.plotly_chart(fig3, use_container_width=True)
            
            # Summary for Graph 3
            st.subheader("Summary for Recording Graph")
            avg_pre_time = recording_df[recording_df['type'] == 'Pre-Record']['timestamp'].dt.hour + recording_df[recording_df['type'] == 'Pre-Record']['timestamp'].dt.minute / 60
            avg_rec_time = recording_df[recording_df['type'] == 'Record']['timestamp'].dt.hour + recording_df[recording_df['type'] == 'Record']['timestamp'].dt.minute / 60
            st.text(f"Average pre-record time: {avg_pre_time.mean():.1f} hours")
            st.text(f"Average record time: {avg_rec_time.mean():.1f} hours")
            avg_rec_bat = recording_df['battery'].mean()
            st.text(f"Average battery during recording: {avg_rec_bat:.1f}%")
            st.text("This graph shows exact pre-record (lightblue) and record (blue) times per day.")

else:
    st.info("Upload .txt log files to start.")