# Agentica 🤖✨

Agentica is a modern control room for managing your AI agents. It lets you **inspect, edit, launch, and monitor** agents from one UI, and includes **Agentica Builder** for creating new agents manually or with an AI assistant.

---

## 🌟 What's Inside

### ✅ Agentica (Main App)
- **Agent list** with agent details and README rendering
- **File explorer & editor** with create, upload, and delete capabilities
- **Secrets manager** for encrypted environment variables
- **Setup tools**: create `.venv` and install requirements
- **Run & monitor** agents with live logs, health checks, and stop/restart controls
- **Agent management** for renaming and deleting agents
- **Automation** with schedules, triggers, and webhooks

### ✅ Agentica Builder
- **Manual creation**: build agents from scratch
- **AI Builder (GPT‑5.2)**: generate files from a prompt
- **Auto profile creation** for run commands
- **README generation** in both modes

---

## 📂 Folder Structure

```
Agentica/
├─ app.py                    # Main application
├─ agent_builder_app.py      # Agent builder app
├─ assets/
│  ├─ agentica_logo.png
│  └─ logo_agentbuilder.png
├─ config/
│  ├─ settings.json          # App settings
│  ├─ agent_profiles.json    # Run profiles per agent
│  ├─ agent_triggers.json    # Automation rules
│  ├─ agent_health.json      # Health probe settings
│  └─ secrets.db             # Encrypted secrets (SQLite)
├─ logs/
│  ├─ agent_manager_state.json    # Running processes
│  ├─ agent_health_state.json     # Health status
│  ├─ agent_trigger_state.json    # Trigger history
│  └─ agent_snapshots/            # Version snapshots
└─ AGENTS/
   ├─ <agent_1>/
   ├─ <agent_2>/
   └─ ...
```

---

## ⚡ Quick Start

1) **Install dependencies**
```bash
pip install -r requirements.txt
```

2) **Run Agentica**
```bash
streamlit run app.py
```

3) **Create agents**
Click **Create Agent** in the top right to launch **Agentica Builder**.

---

## 📁 File Management (Files Tab)

- **Browse & Edit**: View and edit any file in the agent folder
- **➕ Create File**: Click to add new files with custom content
- **📤 Upload File**: Drag & drop or select files to upload (supports multiple files)
- **🗑️ Delete File**: Remove files with confirmation

---

## 🔧 Agent Management (Sidebar)

Located in the sidebar under "Manage Agents":

- **Rename Agent**: Change the agent's folder name and update all related configurations
- **Delete Agent**: Permanently remove an agent with all its settings
  - ⚠️ Requires typing the exact agent name to confirm
  - Automatically cleans up: profiles, triggers, health config, secrets, and state

---

## 🚀 Run Profiles (Agent Commands)

Run profiles define how agents are launched. Stored in:
```
config/agent_profiles.json
```

Example profile structure:
```json
{
  "my_agent": [
    {
      "label": "streamlit",
      "command": "streamlit run app.py --server.port 8510 --server.headless true",
      "streamlit_port": 8510
    },
    {
      "label": "backend",
      "command": "python3 main.py",
      "streamlit_port": null
    }
  ]
}
```

---

## ⏱️ Schedules & Triggers (Automation)

Automation rules are stored in:
```
config/agent_triggers.json
```

Supported automations:
- **Hourly / Daily** schedules
- **Cron-like** schedules (5-field: minute hour day month weekday)
- **File events**: new file or file change in a folder
- **Webhooks**: generic webhook or GitHub push

Webhook listener:
```
http://localhost:8625/hook/<trigger_id>
```

Each automation runs a selected **run profile** for its agent.

---

## 🩺 Health & Monitoring

Each run profile can have:
- **Health probes** (HTTP ping or custom command)
- **Auto‑restart on crash**
- **Status, uptime, last log line time, restart count**

Health settings are stored in:
```
config/agent_health.json
```

Runtime health state is stored in:
```
logs/agent_health_state.json
```

---

## 🧠 Agentica Builder Modes

### 🧩 Templates & Starter Kits
- Hiring Agent
- Multi Agent
- News Scraper Agent
- Security Agent
- WhatsApp Supportbot
- One-click create with run profiles + README
- Templates live under `templates/` and can be customized.

### 🛠 Manual Mode
- Enter agent name
- Write **README.md**, **requirements.txt**, **.env**
- Add Python files
- Define **Run Profiles**

### ✨ AI Builder Mode (GPT‑5.2)
- Enter agent name and prompt
- AI generates files including:
  - `README.md`
  - `requirements.txt`
  - `.env`
  - `.py` files
- Review & edit before saving
- Define run profiles

> API Key: If `OPENAI_API_KEY` exists in `.env`, it auto-fills in the builder.

---

## 🛍️ Agent Marketplace / Registry

Agentica can export/import agents as bundles:
- Bundles include metadata (name, version, tags, requirements) and run profiles
- Import bundles to create agents from files + manifest
- Publish bundles to an internal registry (`registry/`)
- Publish bundles to an external registry endpoint (with optional API key)
- Push agents to GitHub repositories
- Bundles seed env keys (values are never exported)

Marketplace controls live in the **Marketplace** tab per agent.

---

## 🧾 Workspace Versioning & Rollback

Create lightweight snapshots of an agent's files + run profiles, view diffs, and revert safely.
- Snapshots stored under `logs/agent_snapshots/`
- Includes run profiles and agent metadata
- Diff viewer and one‑click rollback available in the **Versioning** tab

---

## ⚙️ Settings

Settings are stored in:
```
config/settings.json
```

You can change the **Agents root folder** from the sidebar in Agentica.
Default:
```
./AGENTS
```

---

### 🧪 Setup Tab (per Agent)

- ✅ Create `.venv`
- ✅ Install requirements (from `requirements.txt`)

This allows each agent to manage its own virtual environment.

---

## 🔐 Environment Variables

Secrets are managed securely in the **Environments** tab:
- Values are encrypted at rest using a local key
- Stored in SQLite with hashed values (`config/secrets.db`)
- Masked by default in the UI
- Legacy `.env` files can be migrated into secrets

---

## 🖼 Branding

- Main app logo: `assets/agentica_logo.png`
- Builder logo: `assets/logo_agentbuilder.png`

---

## 🧩 Requirements

Main dependencies:
- `streamlit`
- `openai`
- `cryptography`

Install with:
```bash
pip install -r requirements.txt
```

---

## ✅ Notes

- If a Streamlit app doesn't open in a new tab, use the **Open Streamlit UI** button shown in Run & Monitor.
- Use **Stop Agent Builder** (with confirmation) to close the builder manually.
- Running agents are tracked across page refreshes and restarts.
- Newly started processes have a 10-second grace period before health validation.

---

## 📘 Extra Docs

- `ADDING_AGENTS.md` — detailed guide for adding agents and profiles

---

Agentica is built to scale with your agents. Happy building! 🚀

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
