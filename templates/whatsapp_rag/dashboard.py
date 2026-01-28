import streamlit as st
import pandas as pd
import gspread
from google.oauth2 import service_account
import os
from dotenv import load_dotenv
import time
import requests

# Load Environment Variables
load_dotenv()

# --- CONFIGURATION ---
CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
API_URL = "http://localhost:8000"  # Address where agent.py is running

# --- SETUP PAGE ---
st.set_page_config(
    page_title="Agent Monitor",
    page_icon="🤖",
    layout="wide"
)

# --- FUNCTIONS ---

@st.cache_resource
def get_google_sheet_client():
    """Authenticates with Google only once (cached)."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=scopes
    )
    return gspread.authorize(creds)

def load_data():
    """Fetches the latest logs from Google Sheets."""
    client = get_google_sheet_client()
    sheet = client.open_by_key(SHEET_ID).sheet1
    # Get all values
    data = sheet.get_all_values()
    # Convert to DataFrame (assuming first row is headers)
    # If your sheet doesn't have headers, we manually name them
    if not data:
        return pd.DataFrame(columns=["Timestamp", "Phone", "User Message", "AI Response"])
    
    # Simple check if headers exist, otherwise use default
    if data[0][0] == "Timestamp":
        df = pd.DataFrame(data[1:], columns=data[0])
    else:
        df = pd.DataFrame(data, columns=["Timestamp", "Phone", "User Message", "AI Response"])
        
    return df

def check_api_status():
    """Pings the FastAPI backend to see if it's alive."""
    try:
        # We assume you have a GET / or /webhook endpoint allowed
        # Note: If /webhook is POST only, this might return 405, which is still 'alive'
        response = requests.get(f"{API_URL}/docs", timeout=2)
        if response.status_code == 200:
            return True
    except:
        return False
    return False

# --- UI LAYOUT ---

st.title("🤖 WhatsApp AI Agent Monitor")

# Sidebar for controls
with st.sidebar:
    st.header("Status Panel")
    if st.button("🔄 Refresh Data"):
        st.rerun()
        
    st.divider()
    
    # System Health Check
    is_alive = check_api_status()
    if is_alive:
        st.success("✅ Backend Agent is ONLINE")
    else:
        st.error("❌ Backend Agent is OFFLINE")
        st.caption("Ensure `agent.py` is running on port 8000")

# Auto-refresh logic (optional - simple manual refresh is often safer/cheaper on APIs)
# if st.toggle("Auto-refresh (every 30s)"):
#     time.sleep(30)
#     st.rerun()

# --- MAIN DASHBOARD ---

# 1. Load Data
try:
    df = load_data()
    
    # Convert Timestamp to datetime for sorting
    if not df.empty and "Timestamp" in df.columns:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors='coerce')
        df = df.sort_values(by="Timestamp", ascending=False)

    # 2. Metrics Row
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Conversations", len(df))
    
    with col2:
        # Unique users count
        unique_users = df['Phone'].nunique() if 'Phone' in df.columns else 0
        st.metric("Unique Users", unique_users)
        
    with col3:
        # Last active time
        last_active = df['Timestamp'].iloc[0] if not df.empty else "N/A"
        st.metric("Last Activity", str(last_active))

    st.divider()

    # 3. Recent Conversations Table
    st.subheader("📝 Live Conversation Logs")
    
    # Add a search filter
    search_term = st.text_input("🔍 Search logs (Phone number or Keyword)")
    
    if search_term and not df.empty:
        # Filter dataframe
        mask = df.astype(str).apply(lambda x: x.str.contains(search_term, case=False)).any(axis=1)
        display_df = df[mask]
    else:
        display_df = df

    # Display the table with nice formatting
    st.dataframe(
        display_df, 
        use_container_width=True,
        hide_index=True,
        column_config={
            "Timestamp": st.column_config.DatetimeColumn("Time", format="D MMM, HH:mm"),
            "User Message": "User Asked",
            "AI Response": "AI Answered"
        }
    )

except Exception as e:
    st.error(f"Error loading data: {e}")
    st.info("Make sure your Google Sheet is shared with the Service Account email.")
