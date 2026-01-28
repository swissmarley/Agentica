import streamlit as st
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
from PyPDF2 import PdfReader
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# --- CONFIGURATION ---
# Load environment variables from .env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")

# Initialize Gemini
if not GEMINI_API_KEY:
    st.error("Missing GEMINI_API_KEY in environment. Set it in .env and restart the app.")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# --- JOB DESCRIPTION (The "Context" for the Agent) ---
JOB_DESCRIPTION = """
Job Title: Senior Python Automation Engineer
Requirements:
- 4+ years of experience with Python.
- Proven experience building AI Agents or using LLMs (OpenAI, Gemini, Mistral).
- Familiarity with workflow automation tools (n8n, Zapier) is a plus.
- Ability to write clean, documented code.
"""

# --- HELPER FUNCTIONS ---

def get_google_sheet():
    """Authenticates and returns the Google Sheet object."""
    if not GOOGLE_SHEETS_CREDENTIALS or not SPREADSHEET_NAME:
        st.error("Missing GOOGLE_SHEETS_CREDENTIALS or SPREADSHEET_NAME in environment.")
        return None
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
    client = gspread.authorize(creds)
    
    try:
        sheet = client.open(SPREADSHEET_NAME).sheet1
        return sheet
    except gspread.SpreadsheetNotFound:
        st.error(f"Spreadsheet '{SPREADSHEET_NAME}' not found. Please create it and share with the service account.")
        return None

def extract_text_from_pdf(uploaded_file):
    """Replaces Mistral OCR Node: Extracts text using PyPDF2."""
    try:
        reader = PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        return f"Error reading PDF: {e}"

def analyze_cv_with_gemini(cv_text, job_desc):
    """Replaces AI Analysis Node: Sends text to Gemini for scoring."""
    
    # Prompt Engineering (System Instruction)
    prompt = f"""
    Act as an expert HR Recruitment Officer. Analyze the candidate's CV text below against the Job Description.
    
    JOB DESCRIPTION:
    {job_desc}
    
    CANDIDATE CV:
    {cv_text}
    
    Task:
    1. Evaluate the candidate's fit (0-100 score).
    2. Provide a concise explanation for the score.
    
    OUTPUT FORMAT:
    You must output strictly valid JSON with no markdown formatting.
    {{
        "score": <number>,
        "reasoning": "<string>"
    }}
    """
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    
    # Cleaning response to ensure valid JSON (removing potential markdown backticks)
    clean_text = response.text.replace("```json", "").replace("```", "").strip()
    
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        return {"score": 0, "reasoning": "Error parsing AI response."}

# --- MAIN AGENT WORKFLOW ---

def main():
    st.set_page_config(page_title="AI Hiring Agent", page_icon="🤖")
    
    st.title("🤖 AI-Powered CV Screener")
    st.markdown("Submit your application below. Our AI Agent will analyze your fit instantly.")
    if not GEMINI_API_KEY:
        st.warning("Set GEMINI_API_KEY in .env to enable AI analysis.")
        st.stop()

    # 1. The Application Form (Replaces Form Trigger)
    with st.form("application_form"):
        name = st.text_input("Full Name")
        email = st.text_input("Email Address")
        uploaded_file = st.file_uploader("Upload CV (PDF)", type=["pdf"])
        submitted = st.form_submit_button("Submit Application")

    if submitted:
        if not uploaded_file or not name or not email:
            st.warning("Please fill in all fields and upload a CV.")
            return

        st.info("🔄 Processing Application...")
        
        # 2. Initial Logging (Replaces 'Log Candidate' Node)
        sheet = get_google_sheet()
        if sheet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # We log basic info first so we don't lose the lead if AI fails
            try:
                sheet.append_row([timestamp, name, email, "Processing...", "Pending", "Pending"])
                st.success("✅ Application Received & Logged.")
            except Exception as e:
                st.error(f"Database Error: {e}")

        # 3. CV Text Extraction (Replaces Mistral OCR Node)
        with st.spinner("📄 Extracting text from CV..."):
            cv_text = extract_text_from_pdf(uploaded_file)
            if len(cv_text) < 50:
                st.error("Could not extract sufficient text. Please upload a text-based PDF, not a scanned image.")
                return

        # 4. AI Analysis (Replaces Gemini & Output Parser Nodes)
        with st.spinner("🧠 AI Analyst is reviewing profile..."):
            analysis = analyze_cv_with_gemini(cv_text, JOB_DESCRIPTION)
            score = analysis.get("score", 0)
            reasoning = analysis.get("reasoning", "N/A")

        # 5. Display Results to User (Optional Feedback Loop)
        st.markdown("### 📋 Application Status")
        col1, col2 = st.columns(2)
        col1.metric("Fit Score", f"{score}/100")
        st.write(f"**AI Analysis:** {reasoning}")

        # 6. Final Record Update (Replaces Final Record Node)
        if sheet:
            try:
                # In a real app, we would update the row we just created. 
                # For simplicity here, we append a final "Analyzed" row or you can implement row update logic.
                sheet.append_row([timestamp, name, email, "Analyzed", score, reasoning])
                st.toast("Database updated with AI Score!", icon="🎉")
            except Exception as e:
                st.error(f"Failed to update database: {e}")

if __name__ == "__main__":
    main()
