import json
import os
import signal
import subprocess
import time
import webbrowser
import socket
import atexit
import base64
import platform
import shlex
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


APP_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = APP_ROOT / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = CONFIG_DIR / "settings.json"
DEFAULT_AGENTS_ROOT = APP_ROOT / "AGENTS"
AGENT_PROFILES_PATH = CONFIG_DIR / "agent_profiles.json"
STATE_PATH = Path("logs/agent_manager_state.json")
LOG_DIR = Path("logs/agent_manager_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
BUILDER_PORT = 8610
BUILDER_STATE_PATH = Path("logs/agent_builder_state.json")


@dataclass(frozen=True)
class RunProfile:
    label: str
    command: str
    streamlit_port: int | None = None



def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        settings = {"agents_root": str(DEFAULT_AGENTS_ROOT)}
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
        return settings
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def get_agents_root() -> Path:
    env_root = os.getenv("AGENTS_ROOT")
    if env_root:
        return Path(env_root)
    settings = load_settings()
    root = settings.get("agents_root")
    if root:
        return Path(root)
    return DEFAULT_AGENTS_ROOT


def ensure_agents_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def format_path(path: Path) -> str:
    try:
        rel = path.relative_to(APP_ROOT)
        return f"./{rel}"
    except ValueError:
        return str(path)


def serialize_profiles(profiles: dict[str, list[RunProfile]]) -> dict:
    data = {}
    for name, items in profiles.items():
        data[name] = [
            {
                "label": item.label,
                "command": item.command,
                "streamlit_port": item.streamlit_port,
            }
            for item in items
        ]
    return data


def load_profiles() -> dict[str, list[RunProfile]]:
    if not AGENT_PROFILES_PATH.exists():
        return {}
    try:
        raw = json.loads(AGENT_PROFILES_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    profiles: dict[str, list[RunProfile]] = {}
    if not isinstance(raw, dict):
        return {}
    for name, items in raw.items():
        if not isinstance(items, list):
            continue
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            command = item.get("command")
            port = item.get("streamlit_port")
            if not label or not command:
                continue
            parsed.append(RunProfile(label, command, port))
        if parsed:
            profiles[name] = parsed
    return profiles


AGENTS_ROOT = get_agents_root()
ensure_agents_root(AGENTS_ROOT)
RUN_PROFILES = load_profiles()


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"processes": []}
    try:
        data = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"processes": []}
    return data if isinstance(data, dict) else {"processes": []}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def pgid_is_alive(pgid: int) -> bool:
    if platform.system() == "Windows":
        return False
    try:
        os.killpg(pgid, 0)
    except OSError:
        return False
    return True


def refresh_state(state: dict) -> dict:
    processes = []
    for item in state.get("processes", []):
        pid = item.get("pid")
        pgid = item.get("pgid")
        alive = False
        if pgid:
            alive = pgid_is_alive(pgid)
        elif pid:
            alive = pid_is_alive(pid)
        if alive:
            processes.append(item)
    state["processes"] = processes
    save_state(state)
    return state


def list_agents() -> list[Path]:
    agents = []
    for entry in AGENTS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry == APP_ROOT:
            continue
        agents.append(entry)
    return sorted(agents, key=lambda p: p.name.lower())


def list_files(agent_path: Path) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {".venv", "__pycache__", ".git", ".mypy_cache", ".pytest_cache"}
    for root, dirs, filenames in os.walk(agent_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for filename in filenames:
            if filename.startswith(".env"):
                continue
            path = Path(root) / filename
            if path.is_file():
                files.append(path)
    return sorted(files, key=lambda p: str(p).lower())

def venv_python_path(agent_path: Path) -> Path:
    if platform.system() == "Windows":
        return agent_path / ".venv" / "Scripts" / "python.exe"
    return agent_path / ".venv" / "bin" / "python"

def build_windows_command(profile: RunProfile, agent_path: Path) -> tuple[list[str] | None, str | None]:
    venv_python = venv_python_path(agent_path)
    if not venv_python.exists():
        return None, "Missing .venv\\Scripts\\python.exe. Create venv first."
    command = profile.command.strip()
    if command.startswith("streamlit "):
        rest = shlex.split(command[len("streamlit "):].strip(), posix=False)
        return [str(venv_python), "-m", "streamlit", *rest], None
    if command.startswith("python3 "):
        rest = shlex.split(command[len("python3 "):].strip(), posix=False)
        return [str(venv_python), *rest], None
    if command.startswith("python "):
        rest = shlex.split(command[len("python "):].strip(), posix=False)
        return [str(venv_python), *rest], None
    if command.startswith("uvicorn "):
        rest = shlex.split(command[len("uvicorn "):].strip(), posix=False)
        return [str(venv_python), "-m", "uvicorn", *rest], None
    return shlex.split(command, posix=False), None


def start_process(agent: str, profile: RunProfile, agent_path: Path) -> dict:
    log_path = LOG_DIR / f"{agent}_{profile.label}.log"
    log_handle = open(log_path, "wb", buffering=0)
    log_handle.write(f"[agentica] Launching {profile.label}\n".encode("utf-8"))
    if os.name == "nt" or platform.system() == "Windows":
        command, error = build_windows_command(profile, agent_path)
        if error:
            log_handle.write(f"[agentica] {error}\n".encode("utf-8"))
            log_handle.flush()
            return {
                "agent": agent,
                "label": profile.label,
                "pid": None,
                "pgid": None,
                "command": profile.command,
                "streamlit_port": profile.streamlit_port,
                "cwd": str(agent_path),
                "log_path": str(log_path),
                "started_at": time.time(),
            }
        log_handle.write(
            f"[agentica] Command: {' '.join(command)}\n".encode("utf-8")
        )
        process = subprocess.Popen(
            command,
            cwd=agent_path,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        pgid = None
    else:
        command = f"source .venv/bin/activate && {profile.command}"
        log_handle.write(f"[agentica] Command: {command}\n".encode("utf-8"))
        process = subprocess.Popen(
            ["bash", "-lc", command],
            cwd=agent_path,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            pgid = os.getpgid(process.pid)
        except AttributeError:
            pgid = None
    return {
        "agent": agent,
        "label": profile.label,
        "pid": process.pid,
        "pgid": pgid,
        "command": profile.command,
        "streamlit_port": profile.streamlit_port,
        "cwd": str(agent_path),
        "log_path": str(log_path),
        "started_at": time.time(),
    }


def stop_process(pid: int, pgid: int | None) -> None:
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    for _ in range(25):
        alive = pgid_is_alive(pgid) if pgid else pid_is_alive(pid)
        if not alive:
            return
        time.sleep(0.2)
    try:
        if pgid:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def tail_log(path: Path, max_lines: int = 80) -> str:
    if not path.exists():
        return ""
    try:
        content = path.read_text(errors="ignore")
    except OSError:
        return ""
    lines = content.splitlines()
    return "\n".join(lines[-max_lines:])


def open_streamlit_tab(port: int) -> None:
    url = f"http://localhost:{port}"
    components.html(
        f"""
        <script>
        window.open("{url}", "_blank");
        </script>
        """,
        height=0,
    )


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def launch_builder_app() -> None:
    if not port_is_open(BUILDER_PORT):
        if platform.system() == "Windows":
            process = subprocess.Popen(
                [
                    "streamlit",
                    "run",
                    "agent_builder_app.py",
                    "--server.port",
                    str(BUILDER_PORT),
                    "--server.headless",
                    "true",
                ],
                cwd=APP_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(
                [
                    "bash",
                    "-lc",
                    f"streamlit run agent_builder_app.py --server.port {BUILDER_PORT} --server.headless true",
                ],
                cwd=APP_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        BUILDER_STATE_PATH.write_text(json.dumps({"pid": process.pid}))
    open_streamlit_tab(BUILDER_PORT)


def stop_builder() -> None:
    if not BUILDER_STATE_PATH.exists():
        return
    try:
        data = json.loads(BUILDER_STATE_PATH.read_text())
    except json.JSONDecodeError:
        return
    pid = data.get("pid")
    if not pid:
        return
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    finally:
        try:
            BUILDER_STATE_PATH.unlink()
        except OSError:
            pass


def load_env_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    counter = 0
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        rows.append({"id": counter, "key": key, "value": value})
        counter += 1
    return rows


def write_env_file(path: Path, rows: list[dict]) -> None:
    content = "\n".join(f"{row['key']}={row['value']}" for row in rows)
    path.write_text(content + ("\n" if content else ""))


def venv_activate_path(agent_path: Path) -> Path:
    if platform.system() == "Windows":
        return agent_path / ".venv" / "Scripts" / "activate"
    return agent_path / ".venv" / "bin" / "activate"


def venv_pip_path(agent_path: Path) -> Path:
    if platform.system() == "Windows":
        return agent_path / ".venv" / "Scripts" / "pip.exe"
    return agent_path / ".venv" / "bin" / "pip"


def create_venv(agent_path: Path) -> tuple[bool, str]:
    try:
        python_cmd = "python" if platform.system() == "Windows" else "python3"
        result = subprocess.run(
            [python_cmd, "-m", "venv", ".venv"],
            cwd=agent_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return False, output.strip() or "Failed to create venv."
    return True, result.stdout.strip() or "Virtualenv created."


def install_requirements(agent_path: Path) -> tuple[bool, str]:
    pip_path = venv_pip_path(agent_path)
    if not pip_path.exists():
        return False, "pip not found in .venv. Create the virtualenv first."
    try:
        result = subprocess.run(
            [str(pip_path), "install", "-r", "requirements.txt"],
            cwd=agent_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return False, output.strip() or "Failed to install requirements."
    return True, result.stdout.strip() or "Requirements installed."


st.set_page_config(page_title="Agentica", page_icon="🤖", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
    :root {
        --bg-1: #0f1317;
        --bg-2: #161b22;
        --card: #1d232c;
	--card-2: #242b35;
        --text: #f2f5f7;
        --muted: #9aa4b2;
        --accent: #f6c36c;
        --accent-2: #7dd3fc;
        --border: rgba(255,255,255,0.08);
    }
    html, body, [class*="stApp"] {
        font-family: "Space Grotesk", sans-serif;
        background: radial-gradient(circle at top left, rgba(246,195,108,0.18), transparent 40%),
                    radial-gradient(circle at 30% 20%, rgba(125,211,252,0.16), transparent 45%),
                    linear-gradient(135deg, var(--bg-1), var(--bg-2));
        color: var(--text);
    }
    .stApp {
        background: transparent;
    }
    .app-hero {
        background: linear-gradient(120deg, rgba(246,195,108,0.12), rgba(125,211,252,0.12));
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 28px 28px 18px 28px;
        margin-bottom: 18px;
        animation: floatIn 0.8s ease;
    }
    .hero-logo {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 12px;
    }
    .hero-logo img {
        height: 160px;
    }
    .hero-subtitle {
        text-align: left;
        margin: 0;
    }
    .app-hero h1 {
        margin: 0 0 6px 0;
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .app-hero p {
        margin: 0;
        color: var(--muted);
        font-size: 1rem;
    }
    .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 18px;
        animation: floatIn 0.7s ease;
    }
    .tag {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(246,195,108,0.14);
        color: var(--accent);
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .muted {
        color: var(--muted);
        font-size: 0.9rem;
    }
    .file-path {
        font-family: "DM Mono", monospace;
        font-size: 0.85rem;
        color: var(--accent-2);
    }
    .stButton>button {
        background: var(--accent);
        color: #1a1a1a;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        padding: 0.6rem 1.1rem;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 24px rgba(0,0,0,0.2);
    }
    .stRadio div[role="radiogroup"] label,
    .stRadio div[role="radiogroup"] label span,
    .stRadio div[role="radiogroup"] label div,
    .stRadio div[role="radiogroup"] label p,
    .stRadio div[role="radiogroup"] label [data-testid="stMarkdownContainer"] {
        color: var(--text) !important;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border-bottom: 2px solid transparent;
        color: var(--muted);
        font-weight: 600;
    }
    [data-testid="stStatusWidget"] * {
        color: var(--text) !important;
    }
    .env-card label,
    .env-card span,
    .env-card p,
    .env-card [data-testid="stToggle"] label,
    .env-card [data-testid="stToggle"] span,
    .env-card [data-testid="stToggle"] div,
    .env-card [data-testid="stToggle"] p,
    .env-card [data-testid="stToggle"] * {
        color: var(--text) !important;
    }
    .env-toggle-label {
        color: var(--text);
        font-weight: 600;
        margin-top: 6px;
    }
    .env-toggle [data-testid="stWidgetLabel"] p,
    .env-toggle [data-testid="stWidgetLabel"] span,
    .env-toggle [data-testid="stWidgetLabel"] div,
    .env-toggle [data-testid="stWidgetLabel"] * {
        color: var(--text) !important;
    }
    .env-remove {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
    .env-remove button {
        height: 40px;
    }
    .env-remove button {
        padding: 0.4rem 0.6rem;
        width: 100%;
        font-size: 0.85rem;
        line-height: 1.1;
        border-radius: 10px;
        white-space: nowrap;
    }
    .stTabs [aria-selected="true"] {
        color: var(--text);
        border-color: var(--accent);
    }
    @keyframes floatIn {
        from { opacity: 0; transform: translateY(12px); }
        to { opacity: 1; transform: translateY(0); }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

logo_path = APP_ROOT / "assets" / "agentica_logo.png"
logo_data = ""
if logo_path.exists():
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")

st.markdown(
    f"""
    <div class="app-hero">
        <div class="hero-logo">
            {f'<img src="data:image/png;base64,{logo_data}" />' if logo_data else ''}
        </div>
        <h1>Orchestrate your AI agents with clarity and control</h1>
        <p class="hero-subtitle">Manage files, environments, launches, and live output from a single, focused workspace.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown("### Settings")
    current_root = format_path(get_agents_root())
    agents_root_input = st.text_input("Agents root", value=current_root)
    if st.button("Save root"):
        settings = load_settings()
        settings["agents_root"] = str(Path(agents_root_input).expanduser())
        save_settings(settings)
        st.success("Saved settings.json")
        st.rerun()

hero_left, hero_right = st.columns([0.8, 0.2])
with hero_right:
    if st.button("Create Agent"):
        launch_builder_app()
        st.session_state.builder_launched = True

    if st.session_state.get("builder_launched"):
        st.caption("If no new tab opens, use the link below.")
        st.link_button("Open Agent Builder", f"http://localhost:{BUILDER_PORT}")
        confirm_stop = st.checkbox("Confirm stop", key="confirm-stop-builder")
        if st.button("Stop Agent Builder"):
            if confirm_stop:
                stop_builder()
                st.session_state.builder_launched = False
                st.rerun()
            else:
                st.warning("Please confirm before stopping Agent Builder.")

state = refresh_state(load_state())
agents = list_agents()

if not agents:
    st.info("No agent folders found under /home/swissmarley/AGENTS.")
    st.stop()

left, right = st.columns([0.32, 0.68], gap="large")

with left:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Agents")
    agent_names = [agent.name for agent in agents]
    selected_name = st.radio("Available agents", agent_names, label_visibility="collapsed")
    selected_agent = next(agent for agent in agents if agent.name == selected_name)
    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"### {selected_agent.name}")
    st.markdown(
        f'<div class="file-path">{format_path(selected_agent)}</div>',
        unsafe_allow_html=True,
    )
    venv_exists = venv_activate_path(selected_agent).exists()
    st.markdown(
        f'<p class="muted">Virtualenv: {"Found" if venv_exists else "Missing"} · '
        f'Files: {len(list_files(selected_agent))}</p>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    overview_tab, files_tab, env_tab, setup_tab, run_tab = st.tabs(
        ["Overview", "Files", "Environments", "Setup", "Run & Monitor"]
    )

    with overview_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Agent details")
        readme_path = selected_agent / "README.md"
        if readme_path.exists():
            st.markdown(readme_path.read_text(errors="ignore"))
        else:
            st.markdown(
                "No README found. Use the Files tab to explore source and configs."
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with files_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Browse & edit files")
        file_list = list_files(selected_agent)
        if not file_list:
            st.info("No files found.")
        else:
            file_options = [str(path.relative_to(selected_agent)) for path in file_list]
            selected_rel = st.selectbox("File", file_options)
            selected_path = selected_agent / selected_rel
            file_size = selected_path.stat().st_size
            if file_size > 500_000:
                st.warning("File too large to load in editor.")
            else:
                content = selected_path.read_text(errors="ignore")
                edited = st.text_area(
                    "File content",
                    value=content,
                    height=360,
                    help="Edit and save changes directly.",
                )
                if st.button("Save file"):
                    selected_path.write_text(edited)
                    st.success("Saved.")
        st.markdown("</div>", unsafe_allow_html=True)

    with env_tab:
        st.markdown('<div class="card env-card">', unsafe_allow_html=True)
        st.markdown("#### Environment variables")
        env_path = selected_agent / ".env"

        if (
            st.session_state.get("env_agent") != selected_agent.name
            or "env_rows" not in st.session_state
        ):
            st.session_state.env_rows = load_env_file(env_path)
            st.session_state.env_next_id = len(st.session_state.env_rows)
            st.session_state.env_agent = selected_agent.name

        if not env_path.exists():
            st.info("No .env found for this agent.")
            if st.button("Create .env"):
                env_path.write_text("")
                st.session_state.env_rows = []
                st.session_state.env_next_id = 0
                st.rerun()
        else:
            col_toggle, col_label = st.columns([0.08, 0.92])
            with col_toggle:
                hide_values = st.toggle("Hide values", value=True, label_visibility="collapsed")
            with col_label:
                st.markdown('<div class="env-toggle-label">Hide values</div>', unsafe_allow_html=True)
            rows = st.session_state.env_rows

            remove_index = None
            for idx, row in enumerate(rows):
                col_key, col_val, col_remove = st.columns(
                    [0.36, 0.54, 0.18], vertical_alignment="center"
                )
                with col_key:
                    st.text_input(
                        "Key",
                        value=row.get("key", ""),
                        key=f"env-key-{row['id']}",
                        label_visibility="collapsed",
                    )
                with col_val:
                    st.text_input(
                        "Value",
                        value=row.get("value", ""),
                        key=f"env-val-{row['id']}",
                        type="password" if hide_values else "default",
                        label_visibility="collapsed",
                    )
                with col_remove:
                    st.markdown('<div class="env-remove">', unsafe_allow_html=True)
                    if st.button("Remove", key=f"env-remove-{idx}"):
                        remove_index = idx
                    st.markdown("</div>", unsafe_allow_html=True)

            if remove_index is not None:
                rows.pop(remove_index)
                st.session_state.env_rows = rows
                write_env_file(env_path, rows)
                st.rerun()

            if st.button("Add variable"):
                next_id = st.session_state.get("env_next_id", 0)
                rows.append({"id": next_id, "key": "", "value": ""})
                st.session_state.env_next_id = next_id + 1
                st.session_state.env_rows = rows
                st.rerun()

            for row in rows:
                key_val = st.session_state.get(f"env-key-{row['id']}", row.get("key", "")).strip()
                val_val = st.session_state.get(f"env-val-{row['id']}", row.get("value", ""))
                row["key"] = key_val
                row["value"] = val_val

            write_env_file(env_path, [row for row in rows if row.get("key")])
            st.caption("Saved.")

        st.markdown("</div>", unsafe_allow_html=True)

    with setup_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Virtual environment")
        venv_path = venv_activate_path(selected_agent)
        if venv_path.exists():
            st.success("Virtualenv found.")
        else:
            st.warning("Virtualenv not found.")
            if st.button("Create .venv"):
                ok, message = create_venv(selected_agent)
                if ok:
                    st.success(message)
                else:
                    st.error(message)
                st.rerun()

        st.markdown("#### Install packages")
        requirements_path = selected_agent / "requirements.txt"
        if requirements_path.exists():
            st.success("requirements.txt found.")
        else:
            st.warning("requirements.txt not found.")

        if not venv_path.exists():
            st.info("Create the virtualenv before installing packages.")
        elif not requirements_path.exists():
            st.error("Add a requirements.txt file to install packages.")
        else:
            if st.button("Install requirements"):
                ok, message = install_requirements(selected_agent)
                if ok:
                    st.success(message)
                else:
                    st.error(message)
        st.markdown("</div>", unsafe_allow_html=True)

    with run_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Launch controls")
        profiles = RUN_PROFILES.get(selected_agent.name, [])
        if not profiles:
            st.info("No run profile configured for this agent.")
        else:
            existing = [
                p for p in state["processes"] if p["agent"] == selected_agent.name
            ]
            if existing:
                st.warning("This agent has running processes.")
            if st.button("Run agent"):
                new_items = []
                for profile in profiles:
                    try:
                        item = start_process(selected_agent.name, profile, selected_agent)
                    except Exception as exc:
                        st.error(f"Failed to start {profile.label}: {exc}")
                        continue
                    if item.get("pid") is None:
                        st.error(f"{profile.label} not started. Check log for details.")
                        continue
                    new_items.append(item)
                    if profile.streamlit_port:
                        open_streamlit_tab(profile.streamlit_port)
                state["processes"].extend(new_items)
                save_state(state)
                if new_items:
                    st.success("Agent started.")
                else:
                    st.warning("No processes started. See launch logs below.")
                st.rerun()

            st.markdown("#### Running agents")
            if st.button("Refresh status"):
                refresh_state(load_state())
                st.rerun()
            running = refresh_state(load_state()).get("processes", [])
            if not running:
                st.info("No agents running.")
            else:
                for item in running:
                    log_path = Path(item["log_path"])
                    title = f"{item['agent']} · {item['label']}"
                    with st.expander(title, expanded=False):
                        st.markdown(
                            f"**PID:** {item['pid']} · **Command:** `{item['command']}`"
                        )
                        st.markdown(
                            f"**Started:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['started_at']))}"
                        )
                        if item.get("streamlit_port"):
                            url = f"http://localhost:{item['streamlit_port']}"
                            st.link_button("Open Streamlit UI", url)
                        if st.button(
                            f"Stop {item['agent']} {item['label']}",
                            key=f"stop-{item['pid']}",
                        ):
                            stop_process(item["pid"], item.get("pgid"))
                            state = load_state()
                            state["processes"] = [
                                p for p in state.get("processes", [])
                                if p.get("pid") != item["pid"]
                            ]
                            save_state(state)
                            refresh_state(state)
                            st.success("Stop signal sent.")
                            st.rerun()
                        log_tail = tail_log(log_path)
                        if log_tail:
                            st.text_area(
                                "Recent output",
                                value=log_tail,
                                height=220,
                            )
                        else:
                            st.markdown("No output yet.")

        st.markdown("</div>", unsafe_allow_html=True)
