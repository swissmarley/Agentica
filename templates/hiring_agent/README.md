# Hiring Agent

An AI-powered CV screener built with Streamlit. Candidates upload a PDF resume, the app extracts text, evaluates fit against a fixed job description, and writes results to Google Sheets.

Key features:
- PDF parsing with PyPDF2
- Gemini-based scoring and reasoning
- Google Sheets logging for applications and scores

Run:
- `streamlit run hiring_agent.py`

Notes:
- Copy `example.env` to `.env` and set `GEMINI_API_KEY`, `GOOGLE_SHEETS_CREDENTIALS`, and `SPREADSHEET_NAME`.
