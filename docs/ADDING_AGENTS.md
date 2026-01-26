# Adding Agents to AgentManagerApp

This guide explains how to make a new agent appear in the manager UI, how to wire its run command(s), and how to show details in the Overview tab.

## 1) Create the agent folder

Place each agent as a top-level folder under:

```
./AGENTS/<agent_name>
```

Example:

```
./AGENTS/my_new_agent
```

The manager automatically scans this directory and lists every agent folder it finds (except its own app folder).

## 2) Add a virtual environment

Each agent must have its own venv:

```
./AGENTS/<agent_name>/.venv
```

The manager starts agents using:

```
source .venv/bin/activate && <your command>
```

## 3) Add a README.md (optional but recommended)

The Overview tab displays the `README.md` if it exists.

Create:

```
./AGENTS/<agent_name>/README.md
```

Keep it short and include:
- Purpose of the agent
- Key features
- How to run it
- Required env vars (if any)

## 4) Add a run profile in `agent_profiles.json`

Run profiles are stored in `./config/agent_profiles.json`. Each agent can have one or more commands.

Example (single Streamlit app):

```python
{
  "my_new_agent": [
    {
      "label": "streamlit",
      "command": "streamlit run app.py --server.port 8510 --server.headless true",
      "streamlit_port": 8510
    }
  ]
}
```

Example (Streamlit + backend):

```python
{
  "my_new_agent": [
    {
      "label": "streamlit",
      "command": "streamlit run dashboard.py --server.port 8511 --server.headless true",
      "streamlit_port": 8511
    },
    {
      "label": "backend",
      "command": "python3 main.py",
      "streamlit_port": null
    }
  ]
}
```

Notes:
- Use a unique Streamlit port per agent to avoid conflicts.
- Set `streamlit_port` to enable auto-open and quick links in the UI.
- The `label` is used in the Run & Monitor list.

## 5) Verify in the UI

Start the manager:

```
streamlit run app.py
```

Then:
- Pick the agent from the list
- Confirm the README renders in Overview
- Launch in Run & Monitor

If you need help wiring a custom agent, provide the run commands and I will add the profile for you.
