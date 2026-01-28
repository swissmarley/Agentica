import json
import os
import re
import base64
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


APP_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = APP_ROOT / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = CONFIG_DIR / "settings.json"
DEFAULT_AGENTS_ROOT = APP_ROOT / "AGENTS"
PROFILES_PATH = CONFIG_DIR / "agent_profiles.json"
TEMPLATES_INDEX_PATH = APP_ROOT / "templates" / "templates.json"


@dataclass
class AgentFile:
    path: str
    content: str


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        settings = {"agents_root": str(DEFAULT_AGENTS_ROOT)}
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
        return settings
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_settings(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_agents_root() -> Path:
    env_root = os.getenv("AGENTS_ROOT")
    if env_root:
        return Path(env_root)
    settings = load_settings()
    root = settings.get("agents_root")
    if root:
        return Path(root)
    return DEFAULT_AGENTS_ROOT


def parse_env_file(path: Path) -> dict:
    if not path.exists():
        return {}
    values = {}
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value
    return values


def normalize_agent_name(name: str) -> str:
    normalized = name.strip().replace(" ", "_")
    return normalized


def is_valid_agent_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", name))


def safe_filename(name: str) -> bool:
    if name.startswith(("./", ".\\", "/", "\\")):
        return False
    if ".." in name.replace("\\", "/").split("/"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_./-]+", name))


def write_agent_files(agent_dir: Path, files: list[AgentFile], overwrite: bool) -> list[str]:
    written = []
    if agent_dir.exists() and not overwrite:
        raise FileExistsError("Agent folder already exists. Enable overwrite to proceed.")
    agent_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        if not safe_filename(file.path):
            raise ValueError(f"Invalid filename: {file.path}")
        target = (agent_dir / file.path).resolve()
        if agent_dir.resolve() not in target.parents and target != agent_dir.resolve():
            raise ValueError(f"Invalid filename: {file.path}")
        if target.exists() and not overwrite:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")
        written.append(str(target))
    return written


def default_system_prompt() -> str:
    return (
        "You are Agent Builder, a software engineer that generates a complete new agent project.\n"
        "Return only valid JSON with this schema:\n"
        "{\n"
        '  "agent_name": "<string>",\n'
        '  "files": [\n'
        '    {"path": "README.md", "content": "<text>"},\n'
        '    {"path": "requirements.txt", "content": "<text>"},\n'
        '    {"path": ".env", "content": "<text>"},\n'
        '    {"path": "<python_file>.py", "content": "<text>"}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Always include README.md with a clear description and run instructions.\n"
        "- Always include requirements.txt and .env (even if .env is empty).\n"
        "- Use only relative file paths without subdirectories.\n"
        "- Provide at least one .py file with a runnable entry point.\n"
        "- Keep code concise and working.\n"
    )


def call_builder(api_key: str, prompt: str) -> dict:
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK not installed. Run: pip install openai")
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model="gpt-5.2",
        input=[
            {"role": "system", "content": default_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    text = response.output_text
    return json.loads(text)


def load_profiles() -> dict:
    if not PROFILES_PATH.exists():
        return {}
    try:
        data = json.loads(PROFILES_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_profiles(data: dict) -> None:
    PROFILES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_profiles(agent_name: str, profiles: list[dict]) -> None:
    data = load_profiles()
    data[agent_name] = profiles
    save_profiles(data)


def load_templates_from_disk() -> dict[str, dict]:
    if not TEMPLATES_INDEX_PATH.exists():
        return {}
    try:
        index = json.loads(TEMPLATES_INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(index, dict):
        return {}

    def apply_vars(text: str) -> str:
        return text

    templates: dict[str, dict] = {}
    for entry in index.get("templates", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        root = entry.get("root")
        description = entry.get("description", "")
        profiles = entry.get("profiles", [])
        if not name or not root:
            continue
        root_path = (APP_ROOT / root).resolve()
        if not root_path.exists():
            continue
        files: list[AgentFile] = []
        for path in sorted(root_path.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(root_path)
            if rel.name.startswith(".DS_Store"):
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            files.append(AgentFile(str(rel), apply_vars(content)))
        rendered_profiles = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            rendered = {}
            for key, value in profile.items():
                if isinstance(value, str):
                    rendered[key] = apply_vars(value)
                else:
                    rendered[key] = value
            rendered_profiles.append(rendered)
        templates[name] = {
            "description": description,
            "files": files,
            "profiles": rendered_profiles,
        }
    return templates

def ensure_session_default(key: str, value: str) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def render_profiles(section_key: str) -> None:
    profiles_key = f"{section_key}_profiles"
    next_id_key = f"{section_key}_profile_next_id"

    if profiles_key not in st.session_state:
        st.session_state[profiles_key] = []
        st.session_state[next_id_key] = 0

    with st.expander("Run profile instructions", expanded=False):
        st.markdown(
            "- **Label**: Choose `streamlit`, `backend`, or `custom`.\n"
            "- **Streamlit**: Provide filename (e.g. `app.py`) and port (e.g. `8510`).\n"
            "- **Backend**: Provide filename (e.g. `main.py`).\n"
            "- **Custom**: Provide label and full command manually.\n"
            "- Example streamlit command: `streamlit run app.py --server.port 8510 --server.headless true`\n"
            "- Example backend command: `python3 main.py`\n"
        )

    remove_profile = None
    for idx, row in enumerate(st.session_state[profiles_key]):
        row_id = row["id"]
        col_label, col_file, col_port, col_cmd, col_remove = st.columns([0.15, 0.2, 0.15, 0.4, 0.1])

        type_key = f"{section_key}-type-{row_id}"
        label_custom_key = f"{section_key}-label-{row_id}"
        filename_key = f"{section_key}-file-{row_id}"
        port_key = f"{section_key}-port-{row_id}"
        cmd_key = f"{section_key}-cmd-{row_id}"

        with col_label:
            st.selectbox(
                "Label",
                ["streamlit", "backend", "custom"],
                key=type_key,
                label_visibility="collapsed",
            )

        label_type = st.session_state.get(type_key, "streamlit")

        with col_file:
            st.text_input(
                "Filename",
                key=filename_key,
                label_visibility="collapsed",
                placeholder="app.py" if label_type == "streamlit" else "main.py",
            )

        with col_port:
            if label_type == "streamlit":
                st.text_input(
                    "Port",
                    key=port_key,
                    label_visibility="collapsed",
                    placeholder="8510",
                )
            else:
                st.markdown("")

        filename = st.session_state.get(filename_key, "").strip()
        port_raw = st.session_state.get(port_key, "").strip()
        port_val = port_raw if port_raw else "8510"

        if label_type == "streamlit":
            default_cmd = f"streamlit run {filename or 'app.py'} --server.port {port_val} --server.headless true"
        elif label_type == "backend":
            default_cmd = f"python3 {filename or 'main.py'}"
        else:
            default_cmd = ""

        if label_type in ("streamlit", "backend"):
            st.session_state[cmd_key] = default_cmd
        else:
            ensure_session_default(cmd_key, default_cmd)

        with col_cmd:
            if label_type == "custom":
                st.text_input(
                    "Command",
                    key=cmd_key,
                    label_visibility="collapsed",
                    placeholder="your command here",
                )
                st.text_input(
                    "Custom label",
                    key=label_custom_key,
                    label_visibility="collapsed",
                    placeholder="label",
                )
            else:
                st.text_input(
                    "Command",
                    key=cmd_key,
                    label_visibility="collapsed",
                    disabled=True,
                )

        with col_remove:
            if st.button("Remove", key=f"{section_key}-prof-remove-{row_id}"):
                remove_profile = idx

    if remove_profile is not None:
        st.session_state[profiles_key].pop(remove_profile)
        st.rerun()

    if st.button("Add run profile", key=f"{section_key}-add-profile"):
        next_id = st.session_state[next_id_key]
        st.session_state[profiles_key].append({"id": next_id})
        st.session_state[next_id_key] = next_id + 1
        st.rerun()


def collect_profiles(section_key: str) -> list[dict]:
    profiles_key = f"{section_key}_profiles"
    profiles = []
    for row in st.session_state.get(profiles_key, []):
        row_id = row["id"]
        label_type = st.session_state.get(f"{section_key}-type-{row_id}", "streamlit")
        filename = st.session_state.get(f"{section_key}-file-{row_id}", "").strip()
        port_raw = st.session_state.get(f"{section_key}-port-{row_id}", "").strip()
        cmd = st.session_state.get(f"{section_key}-cmd-{row_id}", "").strip()
        label_custom = st.session_state.get(f"{section_key}-label-{row_id}", "").strip()

        if label_type == "custom":
            label = label_custom
            if not label or not cmd:
                continue
            profiles.append({"label": label, "command": cmd, "streamlit_port": None})
        elif label_type == "streamlit":
            port = int(port_raw) if port_raw.isdigit() else 8510
            command = f"streamlit run {filename or 'app.py'} --server.port {port} --server.headless true"
            profiles.append({"label": "streamlit", "command": command, "streamlit_port": port})
        else:
            command = f"python3 {filename or 'main.py'}"
            profiles.append({"label": "backend", "command": command, "streamlit_port": None})
    return profiles



st.set_page_config(page_title="Agentica Builder", page_icon="🧠", layout="wide")

logo_path = APP_ROOT / "assets" / "logo_agentbuilder.png"
logo_data = ""
if logo_path.exists():
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")

st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
        {f'<img src="data:image/png;base64,{logo_data}" style="height:120px;" />' if logo_data else ''}
        <h1 style="margin:0;">Agentica Builder</h1>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption("Create a new agent manually or with GPT-5.2. Files are written into the Agents folder.")
st.markdown(
    """
    <style>
    </style>
    """,
    unsafe_allow_html=True,
)


agents_root = get_agents_root()
with st.sidebar:
    st.markdown("### Settings")
    agents_root_input = st.text_input("Agents root", value=str(agents_root))
    if st.button("Save root"):
        settings = load_settings()
        settings["agents_root"] = agents_root_input
        save_settings(settings)
        st.success("Saved settings.json")
        st.rerun()

agents_root = Path(agents_root_input)

tab_manual, tab_builder, tab_templates = st.tabs(["Manual", "Agent Builder", "Templates"])

with tab_templates:
    st.subheader("Starter kits")
    agent_name_raw = st.text_input("Agent name", key="template-name")
    agent_name = normalize_agent_name(agent_name_raw)
    if agent_name and not is_valid_agent_name(agent_name):
        st.error("Use only letters, numbers, dashes, or underscores.")

    overwrite = st.checkbox("Overwrite existing files", value=False, key="template-overwrite")
    templates = load_templates_from_disk()
    if not templates:
        st.error("No templates found. Ensure templates/templates.json exists.")
        st.stop()
    template_name = st.selectbox("Template", list(templates.keys()))
    template = templates[template_name]
    st.caption(template["description"])

    with st.expander("Files included", expanded=False):
        for file in template["files"]:
            st.markdown(f"- {file.path}")

    if st.button("Create from template"):
        if not agent_name or not is_valid_agent_name(agent_name):
            st.error("Provide a valid agent name.")
        else:
            agent_dir = agents_root / agent_name
            try:
                written = write_agent_files(agent_dir, template["files"], overwrite)
                update_profiles(agent_name, template["profiles"])
                st.success(f"Created {agent_name} with {len(written)} files.")
            except (FileExistsError, ValueError) as exc:
                st.error(str(exc))

with tab_manual:
    st.subheader("Manual creation")
    agent_name_raw = st.text_input("Agent name")
    agent_name = normalize_agent_name(agent_name_raw)
    if agent_name and not is_valid_agent_name(agent_name):
        st.error("Use only letters, numbers, dashes, or underscores.")

    overwrite = st.checkbox("Overwrite existing files", value=False)

    requirements_content = st.text_area("requirements.txt", height=120)
    readme_content = st.text_area("README.md", height=140)
    env_content = st.text_area(".env", height=120, help="Add environment variables if needed.")

    if "manual_files" not in st.session_state:
        st.session_state.manual_files = []
        st.session_state.manual_next_id = 0

    st.markdown("#### Python files")
    remove_index = None
    for idx, row in enumerate(st.session_state.manual_files):
        col_name, col_remove = st.columns([0.85, 0.15])
        with col_name:
            st.text_input(
                "Filename",
                value=row.get("name", ""),
                key=f"manual-name-{row['id']}",
                label_visibility="collapsed",
                placeholder="main.py",
            )
        with col_remove:
            if st.button("Remove", key=f"manual-remove-{row['id']}"):
                remove_index = idx
        st.text_area(
            "Content",
            value=row.get("content", ""),
            key=f"manual-content-{row['id']}",
            height=180,
            label_visibility="collapsed",
        )

    if remove_index is not None:
        st.session_state.manual_files.pop(remove_index)
        st.rerun()

    if st.button("Add Python file"):
        next_id = st.session_state.manual_next_id
        st.session_state.manual_files.append({"id": next_id, "name": "", "content": ""})
        st.session_state.manual_next_id = next_id + 1
        st.rerun()

    st.markdown("#### Run profiles")
    render_profiles("manual")

    if st.button("Save agent"):
        if not agent_name or not is_valid_agent_name(agent_name):
            st.error("Provide a valid agent name.")
        else:
            agent_dir = agents_root / agent_name
            files: list[AgentFile] = []
            if readme_content.strip():
                files.append(AgentFile("README.md", readme_content.strip() + "\n"))
            if requirements_content.strip():
                files.append(AgentFile("requirements.txt", requirements_content.strip() + "\n"))
            if env_content.strip():
                files.append(AgentFile(".env", env_content.strip() + "\n"))

            manual_rows = []
            for row in st.session_state.manual_files:
                name = st.session_state.get(f"manual-name-{row['id']}", row.get("name", "")).strip()
                content = st.session_state.get(f"manual-content-{row['id']}", row.get("content", ""))
                if name:
                    manual_rows.append({"name": name, "content": content})

            for row in manual_rows:
                if not safe_filename(row["name"]):
                    st.error(f"Invalid filename: {row['name']}")
                    break
            else:
                for row in manual_rows:
                    files.append(AgentFile(row["name"], row["content"]))

                profiles = collect_profiles("manual")
                if not profiles:
                    st.error("Add at least one run profile.")
                else:
                    try:
                        written = write_agent_files(agent_dir, files, overwrite)
                        update_profiles(agent_name, profiles)
                        st.success(f"Saved {len(written)} files.")
                    except (FileExistsError, ValueError) as exc:
                        st.error(str(exc))

with tab_builder:
    st.subheader("Build with GPT-5.2")
    agent_name_raw = st.text_input("Agent name", key="builder-name")
    agent_name = normalize_agent_name(agent_name_raw)
    if agent_name and not is_valid_agent_name(agent_name):
        st.error("Use only letters, numbers, dashes, or underscores.")

    env_values = parse_env_file(APP_ROOT / ".env")
    default_key = env_values.get("OPENAI_API_KEY", "")
    api_key = st.text_input("OpenAI API key", value=default_key, type="password")

    prompt = st.text_area(
        "Describe the agent you want to build",
        height=180,
        placeholder="Build a Streamlit app that summarizes PDFs with a summary and keywords...",
    )

    overwrite = st.checkbox("Overwrite existing files", value=False, key="builder-overwrite")

    if st.button("Generate files"):
        if not agent_name or not is_valid_agent_name(agent_name):
            st.error("Provide a valid agent name.")
        elif not api_key:
            st.error("Provide an OpenAI API key.")
        elif not prompt.strip():
            st.error("Add a prompt for the builder.")
        else:
            try:
                result = call_builder(api_key, prompt)
            except Exception as exc:
                st.error(f"Builder error: {exc}")
            else:
                st.session_state.builder_result = result
                st.session_state.builder_files = result.get("files", [])

    if st.session_state.get("builder_files"):
        st.markdown("#### Generated files (edit before saving)")
        edited_files = []
        for idx, file in enumerate(st.session_state.builder_files):
            path = file.get("path", "")
            content = file.get("content", "")
            st.text_input("Path", value=path, key=f"builder-path-{idx}")
            st.text_area(
                "Content",
                value=content,
                key=f"builder-content-{idx}",
                height=200,
            )
            edited_files.append(
                AgentFile(
                    st.session_state.get(f"builder-path-{idx}", path),
                    st.session_state.get(f"builder-content-{idx}", content),
                )
            )

        st.markdown("#### Run profiles")
        render_profiles("builder")

        if st.button("Save generated agent"):
            if not agent_name or not is_valid_agent_name(agent_name):
                st.error("Provide a valid agent name.")
            else:
                agent_dir = agents_root / agent_name
                profiles = collect_profiles("builder")
                if not profiles:
                    st.error("Add at least one run profile.")
                else:
                    try:
                        written = write_agent_files(agent_dir, edited_files, overwrite)
                        update_profiles(agent_name, profiles)
                        st.success(f"Saved {len(written)} files.")
                    except (FileExistsError, ValueError) as exc:
                        st.error(str(exc))
