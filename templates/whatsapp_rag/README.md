# WhatsApp Supportbot

A customer support agent that replies to WhatsApp messages using a Google Docs knowledge base. It includes a FastAPI backend and a Streamlit monitoring dashboard.

Key features:
- FastAPI webhook for WhatsApp messages
- Gemini-based responses grounded in a Google Doc
- Google Sheets logging of conversations
- Streamlit dashboard for live monitoring

Run:
- Backend: `uvicorn agent:app --reload`
- Dashboard: `streamlit run dashboard.py`

Notes:
- Configure `GOOGLE_API_KEY`, `GOOGLE_DOC_ID`, `GOOGLE_SHEET_ID`, and WhatsApp credentials in `.env`.
