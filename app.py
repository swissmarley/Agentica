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
import threading
import uuid
import fnmatch
import hashlib
import hmac
from datetime import datetime
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
TRIGGERS_PATH = CONFIG_DIR / "agent_triggers.json"
TRIGGER_STATE_PATH = Path("logs/agent_trigger_state.json")
TRIGGER_LOG_PATH = LOG_DIR / "agent_scheduler.log"
BUILDER_PORT = 8610
BUILDER_STATE_PATH = Path("logs/agent_builder_state.json")
WEBHOOK_PORT = 8625


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


def save_profiles(profiles: dict[str, list[RunProfile]]) -> None:
    AGENT_PROFILES_PATH.write_text(json.dumps(serialize_profiles(profiles), indent=2))


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


def load_triggers() -> dict[str, list[dict]]:
    if not TRIGGERS_PATH.exists():
        return {}
    try:
        data = json.loads(TRIGGERS_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_triggers(data: dict[str, list[dict]]) -> None:
    TRIGGERS_PATH.write_text(json.dumps(data, indent=2))


def load_trigger_state() -> dict:
    if not TRIGGER_STATE_PATH.exists():
        return {"last_run": {}, "file_snapshots": {}, "cron_last_minute": {}}
    try:
        data = json.loads(TRIGGER_STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"last_run": {}, "file_snapshots": {}, "cron_last_minute": {}}
    if not isinstance(data, dict):
        return {"last_run": {}, "file_snapshots": {}, "cron_last_minute": {}}
    data.setdefault("last_run", {})
    data.setdefault("file_snapshots", {})
    data.setdefault("cron_last_minute", {})
    return data


def save_trigger_state(data: dict) -> None:
    TRIGGER_STATE_PATH.write_text(json.dumps(data, indent=2))


def append_trigger_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    TRIGGER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRIGGER_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line)


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


def parse_cron_field(field: str, min_value: int, max_value: int) -> set[int] | None:
    field = field.strip()
    if field == "*":
        return None
    values: set[int] = set()
    parts = field.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            return set()
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError:
                return set()
            if step <= 0:
                return set()
            values.update(range(min_value, max_value + 1, step))
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            try:
                start = int(start_str)
                end = int(end_str)
            except ValueError:
                return set()
            if start > end:
                return set()
            values.update(range(start, end + 1))
            continue
        try:
            values.add(int(part))
        except ValueError:
            return set()
    return {v for v in values if min_value <= v <= max_value}


def cron_matches(expression: str, dt: datetime) -> bool:
    parts = expression.split()
    if len(parts) != 5:
        return False
    minute_vals = parse_cron_field(parts[0], 0, 59)
    hour_vals = parse_cron_field(parts[1], 0, 23)
    day_vals = parse_cron_field(parts[2], 1, 31)
    month_vals = parse_cron_field(parts[3], 1, 12)
    weekday_vals = parse_cron_field(parts[4], 0, 7)
    if minute_vals is not None and dt.minute not in minute_vals:
        return False
    if hour_vals is not None and dt.hour not in hour_vals:
        return False
    if day_vals is not None and dt.day not in day_vals:
        return False
    if month_vals is not None and dt.month not in month_vals:
        return False
    if weekday_vals is not None:
        if 7 in weekday_vals:
            weekday_vals = set(weekday_vals)
            weekday_vals.add(0)
        cron_weekday = (dt.weekday() + 1) % 7
        if cron_weekday not in weekday_vals:
            return False
    return True


def scan_files(path: Path, recursive: bool, pattern: str | None) -> set[str]:
    if not path.exists() or not path.is_dir():
        return set()
    files: set[str] = set()
    if recursive:
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                if pattern and not fnmatch.fnmatch(filename, pattern):
                    continue
                files.add(str(Path(root) / filename))
    else:
        for entry in path.iterdir():
            if not entry.is_file():
                continue
            if pattern and not fnmatch.fnmatch(entry.name, pattern):
                continue
            files.add(str(entry))
    return files


class TriggerManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._webhook_server: ThreadingHTTPServer | None = None
        self._webhook_thread: threading.Thread | None = None
        self._triggers: dict[str, list[dict]] = {}
        self._triggers_mtime: float = 0.0
        self._state = load_trigger_state()

    def ensure_started(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._start_webhook_server()

    def stop(self) -> None:
        self._stop_event.set()
        if self._webhook_server:
            try:
                self._webhook_server.shutdown()
            except Exception:
                pass

    def _start_webhook_server(self) -> None:
        if self._webhook_thread and self._webhook_thread.is_alive():
            return

        manager = self

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length)
                path = urlparse(self.path).path
                status, message = manager.handle_webhook(path, self.headers, body)
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(message.encode("utf-8"))

            def log_message(self, format: str, *args) -> None:
                return

        try:
            server = ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), WebhookHandler)
        except OSError as exc:
            append_trigger_log(f"Webhook server failed to start: {exc}")
            return
        self._webhook_server = server
        self._webhook_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._webhook_thread.start()
        append_trigger_log(f"Webhook server listening on port {WEBHOOK_PORT}.")

    def _reload_triggers_if_needed(self) -> None:
        try:
            mtime = TRIGGERS_PATH.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime == self._triggers_mtime:
            return
        self._triggers = load_triggers()
        self._triggers_mtime = mtime

    def reload_triggers(self) -> None:
        self._triggers = load_triggers()
        try:
            self._triggers_mtime = TRIGGERS_PATH.stat().st_mtime
        except OSError:
            self._triggers_mtime = 0.0

    def _run_loop(self) -> None:
        append_trigger_log("Scheduler loop started.")
        while not self._stop_event.is_set():
            try:
                self._reload_triggers_if_needed()
                self._check_schedules()
                self._check_file_triggers()
            except Exception as exc:
                append_trigger_log(f"Scheduler error: {exc}")
            self._stop_event.wait(10)

    def _check_schedules(self) -> None:
        now = datetime.now()
        for agent_name, rules in self._triggers.items():
            for rule in rules:
                if not rule.get("enabled", True):
                    continue
                if rule.get("kind") != "schedule":
                    continue
                schedule_type = rule.get("schedule_type")
                rule_id = rule.get("id")
                if not rule_id:
                    continue
                if schedule_type == "hourly":
                    minute = int(rule.get("minute", 0))
                    if now.minute != minute:
                        continue
                    last_run = self._state["last_run"].get(rule_id)
                    if last_run and datetime.fromtimestamp(last_run).hour == now.hour and datetime.fromtimestamp(last_run).date() == now.date():
                        continue
                    self._trigger_rule(rule, agent_name, "hourly schedule")
                elif schedule_type == "daily":
                    minute = int(rule.get("minute", 0))
                    hour = int(rule.get("hour", 0))
                    if now.hour != hour or now.minute != minute:
                        continue
                    last_run = self._state["last_run"].get(rule_id)
                    if last_run and datetime.fromtimestamp(last_run).date() == now.date():
                        continue
                    self._trigger_rule(rule, agent_name, "daily schedule")
                elif schedule_type == "cron":
                    expression = rule.get("cron", "").strip()
                    if not expression:
                        continue
                    minute_key = now.strftime("%Y-%m-%d %H:%M")
                    if self._state["cron_last_minute"].get(rule_id) == minute_key:
                        continue
                    if cron_matches(expression, now):
                        self._trigger_rule(rule, agent_name, f"cron {expression}")
                        self._state["cron_last_minute"][rule_id] = minute_key
                        save_trigger_state(self._state)

    def _check_file_triggers(self) -> None:
        for agent_name, rules in self._triggers.items():
            for rule in rules:
                if not rule.get("enabled", True):
                    continue
                if rule.get("kind") != "event":
                    continue
                event_type = rule.get("event_type")
                if event_type not in {"file_new", "file_change"}:
                    continue
                rule_id = rule.get("id")
                folder = Path(rule.get("path", ""))
                if not rule_id or not folder.exists():
                    continue
                recursive = bool(rule.get("recursive", False))
                pattern = rule.get("pattern") or None
                snapshot = scan_files(folder, recursive, pattern)
                prev_snapshot = set(self._state["file_snapshots"].get(rule_id, []))
                if event_type == "file_new":
                    if not prev_snapshot:
                        self._state["file_snapshots"][rule_id] = list(snapshot)
                        save_trigger_state(self._state)
                        continue
                    new_files = snapshot - prev_snapshot
                    if new_files:
                        self._trigger_rule(rule, agent_name, f"new files in {folder}")
                        self._state["file_snapshots"][rule_id] = list(snapshot)
                        save_trigger_state(self._state)
                else:
                    last_scan = self._state["last_run"].get(rule_id, 0)
                    if not last_scan:
                        self._state["last_run"][rule_id] = time.time()
                        save_trigger_state(self._state)
                        continue
                    changed = False
                    for file_path in snapshot:
                        try:
                            mtime = Path(file_path).stat().st_mtime
                        except OSError:
                            continue
                        if mtime > last_scan:
                            changed = True
                            break
                    if changed:
                        self._trigger_rule(rule, agent_name, f"file change in {folder}")

    def handle_webhook(self, path: str, headers: dict, body: bytes) -> tuple[int, str]:
        self._reload_triggers_if_needed()
        matched = []
        for agent_name, rules in self._triggers.items():
            for rule in rules:
                if not rule.get("enabled", True):
                    continue
                if rule.get("kind") != "event":
                    continue
                event_type = rule.get("event_type")
                if event_type not in {"webhook", "github_push"}:
                    continue
                hook_path = rule.get("webhook_path")
                if hook_path != path:
                    continue
                matched.append((agent_name, rule))

        if not matched:
            return 404, "No trigger registered for this path."

        for agent_name, rule in matched:
            event_type = rule.get("event_type")
            if event_type == "github_push":
                if headers.get("X-GitHub-Event") != "push":
                    continue
                secret = rule.get("secret")
                if secret:
                    signature = headers.get("X-Hub-Signature-256") or ""
                    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                    expected = f"sha256={digest}"
                    if not hmac.compare_digest(signature, expected):
                        append_trigger_log("GitHub webhook signature mismatch.")
                        return 401, "Invalid signature."
            else:
                secret = rule.get("secret")
                if secret:
                    header_name = rule.get("secret_header") or "X-Agentica-Token"
                    provided = headers.get(header_name, "")
                    if not hmac.compare_digest(provided, secret):
                        append_trigger_log("Webhook secret mismatch.")
                        return 401, "Invalid token."
            self._trigger_rule(rule, agent_name, f"webhook {path}")
        return 200, "OK"

    def _trigger_rule(self, rule: dict, agent_name: str, reason: str) -> None:
        profile_label = rule.get("profile_label")
        if not profile_label:
            append_trigger_log(f"Trigger skipped for {agent_name}: missing profile label.")
            return
        with self._lock:
            state = refresh_state(load_state())
            if rule.get("skip_if_running", True):
                for item in state.get("processes", []):
                    if item.get("agent") == agent_name and item.get("label") == profile_label:
                        append_trigger_log(
                            f"Skipped trigger for {agent_name}:{profile_label} (already running)."
                        )
                        return
            profiles = load_profiles()
            profile = None
            for p in profiles.get(agent_name, []):
                if p.label == profile_label:
                    profile = p
                    break
            if not profile:
                append_trigger_log(
                    f"Trigger failed for {agent_name}:{profile_label} (profile not found)."
                )
                return
            agent_path = next((p for p in list_agents() if p.name == agent_name), None)
            if not agent_path:
                append_trigger_log(f"Trigger failed for {agent_name} (agent path not found).")
                return
            try:
                item = start_process(agent_name, profile, agent_path)
            except Exception as exc:
                append_trigger_log(
                    f"Trigger failed for {agent_name}:{profile_label} ({exc})."
                )
                return
            if item.get("pid") is None:
                append_trigger_log(
                    f"Trigger failed for {agent_name}:{profile_label} (process not started)."
                )
                return
            state["processes"].append(item)
            save_state(state)
            self._state["last_run"][rule.get("id")] = time.time()
            save_trigger_state(self._state)
            append_trigger_log(
                f"Triggered {agent_name}:{profile_label} via {reason}."
            )

    def trigger_now(self, agent_name: str, rule_id: str) -> None:
        self._reload_triggers_if_needed()
        rule = None
        for item in self._triggers.get(agent_name, []):
            if item.get("id") == rule_id:
                rule = item
                break
        if not rule:
            append_trigger_log(f"Manual trigger failed: rule {rule_id} not found.")
            return
        self._trigger_rule(rule, agent_name, "manual trigger")


TRIGGER_MANAGER = TriggerManager()
atexit.register(TRIGGER_MANAGER.stop)


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


def ensure_session_default(key: str, value: str) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def render_profile_editor(section_key: str) -> None:
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
        col_label, col_file, col_port, col_cmd, col_remove = st.columns(
            [0.18, 0.24, 0.12, 0.36, 0.1], vertical_alignment="center"
        )

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
            st.markdown('<div class="profile-remove">', unsafe_allow_html=True)
            if st.button("🗑️", key=f"{section_key}-prof-remove-{row_id}"):
                remove_profile = idx
            st.markdown("</div>", unsafe_allow_html=True)

    if remove_profile is not None:
        st.session_state[profiles_key].pop(remove_profile)
        st.rerun()

    if st.button("Add run profile", key=f"{section_key}-add-profile"):
        next_id = st.session_state[next_id_key]
        st.session_state[profiles_key].append({"id": next_id})
        st.session_state[next_id_key] = next_id + 1
        st.rerun()


def collect_profile_editor(section_key: str) -> list[RunProfile]:
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
            profiles.append(RunProfile(label, cmd, None))
        elif label_type == "streamlit":
            port = int(port_raw) if port_raw.isdigit() else 8510
            command = f"streamlit run {filename or 'app.py'} --server.port {port} --server.headless true"
            profiles.append(RunProfile("streamlit", command, port))
        else:
            command = f"python3 {filename or 'main.py'}"
            profiles.append(RunProfile("backend", command, None))
    return profiles

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
TRIGGER_MANAGER.ensure_started()

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
    [data-testid="stFormSubmitButton"] button {
        background: var(--accent) !important;
        color: #1a1a1a !important;
    }
    [data-testid="baseButton-secondary"] {
        background: var(--card-2) !important;
        color: var(--text) !important;
        border: 1px solid var(--border) !important;
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
    .profile-remove {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
    .profile-remove button {
        width: 36px;
        height: 36px;
        padding: 0;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
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
    [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] span,
    [data-testid="stWidgetLabel"] div,
    [data-testid="stWidgetLabel"] * {
        color: var(--text) !important;
    }
    .stSelectbox label,
    .stTextInput label,
    .stNumberInput label,
    .stTextarea label,
    .stMultiSelect label,
    .stCheckbox label {
        color: var(--text) !important;
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
    if st.button("Refresh App"):
        st.rerun()
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

    overview_tab, files_tab, env_tab, setup_tab, run_tab, automation_tab = st.tabs(
        ["Overview", "Files", "Environments", "Setup", "Run & Monitor", "Automation"]
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
            st.warning("No run profile configured for this agent.")
            st.markdown("#### Add run profiles")
            render_profile_editor(f"profile-{selected_agent.name}")
            if st.button("Save run profiles", key=f"save-profiles-{selected_agent.name}"):
                new_profiles = collect_profile_editor(f"profile-{selected_agent.name}")
                if not new_profiles:
                    st.error("Add at least one run profile.")
                else:
                    all_profiles = load_profiles()
                    all_profiles[selected_agent.name] = new_profiles
                    save_profiles(all_profiles)
                    st.success("Run profiles saved.")
                    st.rerun()
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

    with automation_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Schedules & triggers")
        triggers_data = load_triggers()
        agent_rules = triggers_data.get(selected_agent.name, [])
        trigger_state = load_trigger_state()

        if not agent_rules:
            st.info("No schedules or triggers configured for this agent.")
        else:
            for rule in agent_rules:
                rule_id = rule.get("id", "")
                title = rule.get("label") or rule.get("kind", "Automation").title()
                with st.expander(title, expanded=False):
                    profile_label = rule.get("profile_label", "unknown")
                    kind = rule.get("kind", "schedule")
                    enabled_key = f"trigger-enabled-{rule_id}"
                    if enabled_key not in st.session_state:
                        st.session_state[enabled_key] = rule.get("enabled", True)
                    enabled_val = st.toggle("Enabled", key=enabled_key)
                    if enabled_val != rule.get("enabled", True):
                        rule["enabled"] = enabled_val
                        triggers_data[selected_agent.name] = agent_rules
                        save_triggers(triggers_data)
                        TRIGGER_MANAGER.reload_triggers()
                    st.markdown(f"**Profile:** `{profile_label}` · **Type:** `{kind}`")
                    if kind == "schedule":
                        schedule_type = rule.get("schedule_type", "hourly")
                        if schedule_type == "hourly":
                            st.markdown(f"Runs hourly at minute `{rule.get('minute', 0)}`.")
                        elif schedule_type == "daily":
                            st.markdown(
                                f"Runs daily at `{rule.get('hour', 0):02d}:{rule.get('minute', 0):02d}`."
                            )
                        else:
                            st.markdown(f"Cron: `{rule.get('cron', '* * * * *')}`")
                    else:
                        event_type = rule.get("event_type")
                        if event_type in {"file_new", "file_change"}:
                            st.markdown(
                                f"Folder: `{rule.get('path', '')}` · Pattern: `{rule.get('pattern', '*')}`"
                            )
                            st.markdown(
                                f"Recursive: `{rule.get('recursive', False)}` · Event: `{event_type}`"
                            )
                        else:
                            hook_path = rule.get("webhook_path", "")
                            st.markdown(
                                f"Webhook URL: `http://localhost:{WEBHOOK_PORT}{hook_path}`"
                            )
                            if event_type == "github_push":
                                st.caption("GitHub event: push")
                    last_run = trigger_state.get("last_run", {}).get(rule_id)
                    if last_run:
                        st.markdown(
                            f"**Last run:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_run))}"
                        )
                    col_run, col_delete = st.columns([0.2, 0.8])
                    with col_run:
                        if st.button("Run now", key=f"trigger-run-{rule_id}"):
                            TRIGGER_MANAGER.trigger_now(selected_agent.name, rule_id)
                            st.success("Trigger fired.")
                    with col_delete:
                        if st.button("Delete", key=f"trigger-delete-{rule_id}"):
                            agent_rules[:] = [r for r in agent_rules if r.get("id") != rule_id]
                            if agent_rules:
                                triggers_data[selected_agent.name] = agent_rules
                            else:
                                triggers_data.pop(selected_agent.name, None)
                            save_triggers(triggers_data)
                            st.rerun()

        st.markdown("#### Add automation")
        profiles = load_profiles().get(selected_agent.name, [])
        profile_labels = [p.label for p in profiles]
        if not profile_labels:
            st.warning("Add run profiles before creating schedules or triggers.")
        else:
            with st.form(f"add-trigger-{selected_agent.name}"):
                rule_kind = st.selectbox("Automation type", ["Schedule", "Event"])
                label = st.text_input("Label", value="")
                profile_choice = st.selectbox("Run profile", profile_labels)
                enabled = st.checkbox("Enabled", value=True)
                skip_if_running = st.checkbox("Skip if already running", value=True)

                schedule_type = "hourly"
                minute = 0
                hour = 0
                cron_expr = ""
                event_type = "file_new"
                folder_path = ""
                pattern = "*"
                recursive = False
                secret = ""
                secret_header = "X-Agentica-Token"

                if rule_kind == "Schedule":
                    schedule_type = st.selectbox(
                        "Schedule type", ["hourly", "daily", "cron"]
                    )
                    if schedule_type == "hourly":
                        minute = st.number_input("Minute", min_value=0, max_value=59, value=0)
                    elif schedule_type == "daily":
                        hour = st.number_input("Hour", min_value=0, max_value=23, value=9)
                        minute = st.number_input("Minute", min_value=0, max_value=59, value=0)
                    else:
                        cron_expr = st.text_input("Cron (min hour day month weekday)", value="0 * * * *")
                        st.caption("Weekday uses 0=Sunday..6=Saturday (7 also treated as Sunday).")
                else:
                    event_type = st.selectbox(
                        "Event type", ["file_new", "file_change", "webhook", "github_push"]
                    )
                    if event_type in {"file_new", "file_change"}:
                        folder_path = st.text_input("Folder path", value=str(selected_agent))
                        pattern = st.text_input("Filename pattern", value="*")
                        recursive = st.checkbox("Recursive", value=False)
                    elif event_type == "webhook":
                        secret = st.text_input("Webhook token (optional)", value="")
                        secret_header = st.text_input(
                            "Token header", value="X-Agentica-Token"
                        )
                    else:
                        secret = st.text_input("GitHub webhook secret (optional)", value="")
                submitted = st.form_submit_button("Create automation")

            if submitted:
                rule_id = uuid.uuid4().hex
                rule_label = label.strip() or f"{rule_kind.lower()}-{rule_id[:8]}"
                new_rule: dict[str, object] = {
                    "id": rule_id,
                    "label": rule_label,
                    "profile_label": profile_choice,
                    "kind": "schedule" if rule_kind == "Schedule" else "event",
                    "enabled": enabled,
                    "skip_if_running": skip_if_running,
                }
                if rule_kind == "Schedule":
                    new_rule["schedule_type"] = schedule_type
                    if schedule_type == "hourly":
                        new_rule["minute"] = int(minute)
                    elif schedule_type == "daily":
                        new_rule["hour"] = int(hour)
                        new_rule["minute"] = int(minute)
                    else:
                        new_rule["cron"] = cron_expr.strip()
                else:
                    new_rule["event_type"] = event_type
                    if event_type in {"file_new", "file_change"}:
                        new_rule["path"] = folder_path.strip()
                        new_rule["pattern"] = pattern.strip() or "*"
                        new_rule["recursive"] = bool(recursive)
                    else:
                        new_rule["webhook_path"] = f"/hook/{rule_id}"
                        if secret:
                            new_rule["secret"] = secret.strip()
                        if event_type == "webhook":
                            new_rule["secret_header"] = secret_header.strip() or "X-Agentica-Token"
                triggers = load_triggers()
                triggers.setdefault(selected_agent.name, [])
                triggers[selected_agent.name].append(new_rule)
                save_triggers(triggers)
                st.success("Automation saved.")
                st.rerun()

        if TRIGGER_LOG_PATH.exists():
            st.markdown("#### Automation log")
            st.text_area(
                "Recent scheduler output",
                value=tail_log(TRIGGER_LOG_PATH, max_lines=120),
                height=220,
            )
        st.markdown("</div>", unsafe_allow_html=True)
