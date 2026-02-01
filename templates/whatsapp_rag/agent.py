import os
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from dotenv import load_dotenv
import requests
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build

# LangChain Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# Load environment variables
load_dotenv()

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- CONFIGURATION ---
CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
DOC_ID = os.getenv("GOOGLE_DOC_ID")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets"
]

# --- HELPER SERVICES ---

def get_google_creds():
    return service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=SCOPES
    )

def fetch_knowledge_base(doc_id: str) -> str:
    """Reads the raw text from the Google Doc."""
    creds = get_google_creds()
    service = build('docs', 'v1', credentials=creds)
    document = service.documents().get(documentId=doc_id).execute()
    
    text_content = ""
    for content in document.get('body').get('content'):
        if 'paragraph' in content:
            elements = content.get('paragraph').get('elements')
            for elem in elements:
                if 'textRun' in elem:
                    text_content += elem.get('textRun').get('content')
    return text_content

def log_conversation(phone: str, user_msg: str, ai_msg: str):
    """Logs the interaction to Google Sheets."""
    try:
        creds = get_google_creds()
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, phone, user_msg, ai_msg])
    except Exception as e:
        logger.error(f"Failed to log to sheets: {e}")

def send_whatsapp_message(to_number: str, message: str):
    """Sends the response back via Meta Cloud API."""
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        logger.error(f"WhatsApp API Error: {response.text}")

# --- THE AGENTIC CORE ---

async def run_agent(user_message: str, phone_number: str):
    """
    The Core Agent Logic:
    1. Fetches Context (Doc)
    2. Calculates Date
    3. Prompts LLM
    4. Executes Action (Send & Log)
    """
    
    # 1. Retrieve Knowledge
    # Note: In production, cache this content to avoid hitting Google API limits on every msg
    knowledge_text = fetch_knowledge_base(DOC_ID)
    
    # 2. Get Current Context
    current_time = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    
    # 3. Setup AI Model (Gemini Pro)
    llm = ChatGoogleGenerativeAI(
        model="gemini-pro",
        google_api_key=GOOGLE_API_KEY,
        temperature=0.3
    )
    
    # 4. Construct System Prompt
    system_prompt = """
    You are a helpful customer support assistant for a business.
    
    Here is the company's internal knowledge base:
    <knowledge_base>
    {doc_content}
    </knowledge_base>
    
    Current Date and Time: {current_time}
    
    Instructions:
    1. Answer the user's question purely based on the knowledge base provided.
    2. If the answer is not in the document, apologize and say you cannot help with that specific query.
    3. Pay close attention to dates. If the document mentions a closing date, compare it to the 'Current Date' provided above to see if we are currently open or closed.
    4. Keep the tone friendly and concise.
    
    User Question: {question}
    """
    
    prompt = ChatPromptTemplate.from_template(system_prompt)
    chain = prompt | llm
    
    # 5. Generate Response
    response = chain.invoke({
        "doc_content": knowledge_text,
        "current_time": current_time,
        "question": user_message
    })
    
    ai_response_text = response.content
    
    # 6. Perform Actions (Send & Log)
    send_whatsapp_message(phone_number, ai_response_text)
    log_conversation(phone_number, user_message, ai_response_text)

# --- WEBHOOK ENDPOINTS ---

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Verifies the webhook for Meta."""
    verify_token = "YOUR_CUSTOM_VERIFY_TOKEN" # Set this in Meta App Dashboard
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == verify_token:
            return int(challenge)
        else:
            raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """Receives messages from WhatsApp."""
    data = await request.json()
    
    try:
        # Extract message details (Meta JSON structure is deeply nested)
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        
        if 'messages' in value:
            message_data = value['messages'][0]
            phone_number = message_data['from']
            
            if message_data['type'] == 'text':
                user_message = message_data['text']['body']
                
                # Run agent in background to prevent timeout on the webhook
                background_tasks.add_task(run_agent, user_message, phone_number)
                
    except Exception as e:
        logger.error(f"Error parsing webhook: {e}")
        
    return {"status": "ok"}

# To run: uvicorn agent:app --reload
