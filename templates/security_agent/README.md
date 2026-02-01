# Security Agent

A security analysis assistant with a Streamlit dashboard and a Discord bot. It can analyze user prompts and uploaded files, then produce summaries and PDF reports.

Key features:
- Streamlit chat UI with file analysis support
- PDF report generation via the agent orchestrator
- Discord bot integration for automated security checks

Run:
- Streamlit UI: `streamlit run dashboard.py`
- Discord bot: `python3 bot.py`

Notes:
- Requires environment variables for the bot and any LLM providers used in the agent.
