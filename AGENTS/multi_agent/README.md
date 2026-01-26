# Multi Agent

An agentic workflow orchestrator that chains multiple roles to complete a build request. It supports both a Streamlit UI and a CLI flow.

Pipeline:
- Research -> Plan -> Implement -> Publish

Key components:
- `MCPManager` connects tool servers
- Anthropic client powers the agent roles
- Streamlit UI streams progress logs

Run:
- UI: `streamlit run app.py`
- CLI: `python3 main.py`

Notes:
- Requires `ANTHROPIC_API_KEY` and optional `GITHUB_TOKEN` in `.env`.
