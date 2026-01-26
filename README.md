# Agentica 🤖✨

Agentica is a modern control room for managing your AI agents. It lets you **inspect, edit, launch, and monitor** agents from one UI, and includes **Agentica Builder** for creating new agents manually or with an AI assistant.

---

## 🌟 What’s Inside

### ✅ Agentica (Main App)
- **Agent list** with agent details and README rendering
- **File explorer & editor** (safe editing, `.env` hidden)
- **Environment manager** for `.env` variables
- **Setup tools**: create `.venv` and install requirements
- **Run & monitor** agents with live logs and stop controls

### ✅ Agentica Builder
- **Manual creation**: build agents from scratch
- **AI Builder (GPT‑5.2)**: generate files from a prompt
- **Auto profile creation** for run commands
- **README generation** in both modes

---

## 📂 Folder Structure

```
Agentica/
├─ app.py
├─ agent_builder_app.py
├─ assets/
│  ├─ agentica_logo.png
│  └─ logo_agentbuilder.png
├─ config/
│  ├─ settings.json
│  └─ agent_profiles.json
├─ logs/
└─ AGENTS/
   ├─ <agent_1>/
   ├─ <agent_2>/
   └─ ...
```

---

## ⚡ Quick Start

1) **Install dependencies**
```
pip install -r requirements.txt
```

2) **Run Agentica**
```
streamlit run app.py
```

3) **Create agents**  
Click **Create Agent** in the top right to launch **Agentica Builder**.

---

## 🧠 Agentica Builder Modes

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

## 🚀 Run Profiles (Agent Commands)

Run profiles are stored in:
```
config/agent_profiles.json
```

Example:
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

In each agent:
- `.env` is managed in the **Environments** tab
- Variables are editable and saved automatically

---

## 🖼 Branding

- Main app logo: `assets/agentica_logo.png`
- Builder logo: `assets/logo_agentbuilder.png`

---

## 🧩 Requirements

Main dependencies:
- `streamlit`
- `openai`

Install with:
```
pip install -r requirements.txt
```

---

## ✅ Notes

- If a Streamlit app doesn’t open in a new tab, use the **Open Streamlit UI** button shown in Run & Monitor.
- Use **Stop Agent Builder** (with confirmation) to close the builder manually.

---

## 📘 Extra Docs

- `ADDING_AGENTS.md` — detailed guide for adding agents and profiles

---

Agentica is built to scale with your agents. Happy building! 🚀

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.