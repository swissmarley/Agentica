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
import zipfile
import tempfile
import shutil
import urllib.request
import difflib
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
HEALTH_CONFIG_PATH = CONFIG_DIR / "agent_health.json"
HEALTH_STATE_PATH = Path("logs/agent_health_state.json")
HEALTH_LOG_PATH = LOG_DIR / "agent_health.log"
METADATA_PATH = CONFIG_DIR / "agent_metadata.json"
REGISTRY_DIR = APP_ROOT / "registry"
REGISTRY_INDEX_PATH = REGISTRY_DIR / "index.json"
SNAPSHOT_DIR = Path("logs/agent_snapshots")
SNAPSHOT_INDEX_PATH = SNAPSHOT_DIR / "index.json"
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


def load_health_config() -> dict:
    if not HEALTH_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(HEALTH_CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_health_config(data: dict) -> None:
    HEALTH_CONFIG_PATH.write_text(json.dumps(data, indent=2))


def load_health_state() -> dict:
    if not HEALTH_STATE_PATH.exists():
        return {"profiles": {}}
    try:
        data = json.loads(HEALTH_STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"profiles": {}}
    if not isinstance(data, dict):
        return {"profiles": {}}
    data.setdefault("profiles", {})
    return data


def save_health_state(data: dict) -> None:
    HEALTH_STATE_PATH.write_text(json.dumps(data, indent=2))


def append_health_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    HEALTH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HEALTH_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line)


def load_metadata() -> dict:
    if not METADATA_PATH.exists():
        return {}
    try:
        data = json.loads(METADATA_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_metadata(data: dict) -> None:
    METADATA_PATH.write_text(json.dumps(data, indent=2))


def load_registry_index() -> dict:
    if not REGISTRY_INDEX_PATH.exists():
        return {"bundles": []}
    try:
        data = json.loads(REGISTRY_INDEX_PATH.read_text())
    except json.JSONDecodeError:
        return {"bundles": []}
    if not isinstance(data, dict):
        return {"bundles": []}
    data.setdefault("bundles", [])
    return data


def save_registry_index(data: dict) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_INDEX_PATH.write_text(json.dumps(data, indent=2))


def load_snapshot_index() -> dict:
    if not SNAPSHOT_INDEX_PATH.exists():
        return {"agents": {}}
    try:
        data = json.loads(SNAPSHOT_INDEX_PATH.read_text())
    except json.JSONDecodeError:
        return {"agents": {}}
    if not isinstance(data, dict):
        return {"agents": {}}
    data.setdefault("agents", {})
    return data


def save_snapshot_index(data: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_INDEX_PATH.write_text(json.dumps(data, indent=2))


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


def find_pids_by_port(port: int) -> list[int]:
    pids: list[int] = []
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, OSError):
            return pids
        for line in result.stdout.splitlines():
            if f":{port} " not in line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                pid = parts[-1]
                if pid.isdigit():
                    pids.append(int(pid))
        return sorted(set(pids))
    for cmd in (["lsof", "-ti", f"tcp:{port}"], ["fuser", "-n", "tcp", str(port)]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue
        for token in result.stdout.replace(",", " ").split():
            if token.isdigit():
                pids.append(int(token))
    return sorted(set(pids))


def stop_processes_by_port(port: int) -> bool:
    pids = find_pids_by_port(port)
    if not pids:
        return False
    for pid in pids:
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    return True


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


def profile_key(agent_name: str, label: str) -> str:
    return f"{agent_name}::{label}"


def http_ping(port: int, timeout: float = 2.0) -> bool:
    try:
        conn = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        conn.settimeout(timeout)
        conn.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
        conn.recv(1)
        conn.close()
        return True
    except OSError:
        return False


def run_probe_command(agent_path: Path, command: str, timeout: int = 10) -> bool:
    if not command.strip():
        return False


def sanitize_env_file(path: Path) -> str:
    if not path.exists():
        return ""
    lines = []
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            lines.append(line)
            continue
        comment = ""
        if "#" in value:
            comment = value[value.index("#") :].strip()
        placeholder = "YOUR_CREDENTIALS"
        new_line = f"{key}={placeholder}"
        if comment:
            new_line += f" {comment}"
        lines.append(new_line)
    return "\n".join(lines) + ("\n" if lines else "")


def build_manifest(agent_name: str, agent_path: Path) -> dict:
    metadata = load_metadata().get(agent_name, {})
    requirements_path = agent_path / "requirements.txt"
    requirements = []
    if requirements_path.exists():
        requirements = [
            line.strip()
            for line in requirements_path.read_text(errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    profiles = [
        {
            "label": profile.label,
            "command": profile.command,
            "streamlit_port": profile.streamlit_port,
        }
        for profile in load_profiles().get(agent_name, [])
    ]
    return {
        "name": agent_name,
        "version": metadata.get("version", "0.1.0"),
        "tags": metadata.get("tags", []),
        "description": metadata.get("description", ""),
        "requirements": requirements,
        "profiles": profiles,
    }


def snapshot_agent(agent_name: str, agent_path: Path, note: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_id = f"{agent_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    snapshot_path = SNAPSHOT_DIR / f"{snapshot_id}.zip"
    manifest = build_manifest(agent_name, agent_path)
    manifest["note"] = note.strip()
    manifest["created_at"] = time.time()
    with zipfile.ZipFile(snapshot_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("agentica_snapshot.json", json.dumps(manifest, indent=2))
        for root, dirs, files in os.walk(agent_path):
            dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", ".git"}]
            for filename in files:
                if filename.endswith(".pyc"):
                    continue
                path = Path(root) / filename
                rel = path.relative_to(agent_path)
                bundle.write(path, arcname=str(Path("agent") / rel))
    index = load_snapshot_index()
    index["agents"].setdefault(agent_name, [])
    index["agents"][agent_name].append(
        {
            "id": snapshot_id,
            "path": str(snapshot_path),
            "created_at": manifest["created_at"],
            "note": manifest["note"],
            "version": manifest["version"],
        }
    )
    save_snapshot_index(index)
    return snapshot_path


def read_snapshot(snapshot_path: Path) -> dict:
    with zipfile.ZipFile(snapshot_path, "r") as bundle:
        manifest = json.loads(bundle.read("agentica_snapshot.json"))
        files = {}
        for info in bundle.infolist():
            if not info.filename.startswith("agent/") or info.is_dir():
                continue
            rel = info.filename[len("agent/") :]
            try:
                content = bundle.read(info.filename).decode("utf-8")
            except UnicodeDecodeError:
                content = ""
            files[rel] = content
    return {"manifest": manifest, "files": files}


def diff_snapshot_to_current(agent_path: Path, snapshot: dict) -> str:
    current_files = {}
    for root, dirs, files in os.walk(agent_path):
        dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", ".git"}]
        for filename in files:
            if filename.endswith(".pyc"):
                continue
            path = Path(root) / filename
            rel = str(path.relative_to(agent_path))
            try:
                current_files[rel] = path.read_text(errors="ignore")
            except OSError:
                current_files[rel] = ""
    snapshot_files = snapshot.get("files", {})
    all_files = sorted(set(current_files) | set(snapshot_files))
    diff_chunks = []
    for rel in all_files:
        before = snapshot_files.get(rel, "").splitlines()
        after = current_files.get(rel, "").splitlines()
        if before == after:
            continue
        diff = difflib.unified_diff(
            before,
            after,
            fromfile=f"snapshot/{rel}",
            tofile=f"current/{rel}",
            lineterm="",
        )
        diff_chunks.extend(list(diff))
    return "\n".join(diff_chunks)


def restore_snapshot(agent_name: str, agent_path: Path, snapshot_path: Path) -> tuple[bool, str]:
    try:
        snapshot = read_snapshot(snapshot_path)
    except Exception as exc:
        return False, f"Failed to read snapshot: {exc}"
    agent_folder = agent_path
    if agent_folder.exists():
        shutil.rmtree(agent_folder)
    agent_folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(snapshot_path, "r") as bundle:
        for info in bundle.infolist():
            if not info.filename.startswith("agent/") or info.is_dir():
                continue
            rel = info.filename[len("agent/") :]
            target = agent_folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data = bundle.read(info.filename)
            target.write_bytes(data)
    manifest = snapshot.get("manifest", {})
    profiles = load_profiles()
    if manifest.get("profiles"):
        profiles[agent_name] = [
            RunProfile(item.get("label"), item.get("command"), item.get("streamlit_port"))
            for item in manifest.get("profiles", [])
            if item.get("label") and item.get("command")
        ]
        save_profiles(profiles)
    metadata = load_metadata()
    metadata[agent_name] = {
        "version": manifest.get("version", "0.1.0"),
        "tags": manifest.get("tags", []),
        "description": manifest.get("description", ""),
    }
    save_metadata(metadata)
    return True, "Snapshot restored."


def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as bundle:
        for member in bundle.infolist():
            target = (dest / member.filename).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise ValueError("Unsafe path in bundle.")
        bundle.extractall(dest)


def export_agent_bundle(agent_name: str, agent_path: Path) -> Path:
    exports_dir = APP_ROOT / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(agent_name, agent_path)
    bundle_name = f"{agent_name}_v{manifest['version']}.agentica.zip"
    bundle_path = exports_dir / bundle_name
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("agentica_manifest.json", json.dumps(manifest, indent=2))
        for root, dirs, files in os.walk(agent_path):
            dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", ".git"}]
            for filename in files:
                if filename.endswith(".pyc"):
                    continue
                path = Path(root) / filename
                rel = path.relative_to(agent_path)
                if rel.name == ".env":
                    sanitized = sanitize_env_file(path)
                    bundle.writestr(str(Path("agent") / rel), sanitized)
                else:
                    bundle.write(path, arcname=str(Path("agent") / rel))
    return bundle_path


def import_agent_bundle(bundle_bytes: bytes, overwrite: bool) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "bundle.zip"
        bundle_path.write_bytes(bundle_bytes)
        extract_path = Path(tmpdir) / "bundle"
        extract_path.mkdir()
        safe_extract_zip(bundle_path, extract_path)
        manifest_path = extract_path / "agentica_manifest.json"
        if not manifest_path.exists():
            return False, "Missing agentica_manifest.json in bundle."
        manifest = json.loads(manifest_path.read_text())
        agent_name = manifest.get("name")
        if not agent_name:
            return False, "Manifest missing agent name."
        agent_folder = extract_path / "agent"
        if not agent_folder.exists():
            return False, "Bundle missing agent folder."
        target = AGENTS_ROOT / agent_name
        if target.exists():
            if not overwrite:
                return False, "Agent folder already exists."
            shutil.rmtree(target)
        shutil.copytree(agent_folder, target)

        profiles = load_profiles()
        if manifest.get("profiles"):
            profiles[agent_name] = [
                RunProfile(
                    item.get("label"),
                    item.get("command"),
                    item.get("streamlit_port"),
                )
                for item in manifest.get("profiles", [])
                if item.get("label") and item.get("command")
            ]
            save_profiles(profiles)

        metadata = load_metadata()
        metadata[agent_name] = {
            "version": manifest.get("version", "0.1.0"),
            "tags": manifest.get("tags", []),
            "description": manifest.get("description", ""),
        }
        save_metadata(metadata)
        return True, f"Imported {agent_name}."


def publish_to_registry(bundle_path: Path) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    target = REGISTRY_DIR / bundle_path.name
    shutil.copy2(bundle_path, target)
    index = load_registry_index()
    try:
        with zipfile.ZipFile(bundle_path, "r") as bundle:
            manifest = json.loads(bundle.read("agentica_manifest.json"))
    except Exception:
        manifest = {}
    index["bundles"].append(
        {
            "bundle": target.name,
            "name": manifest.get("name", ""),
            "version": manifest.get("version", "0.1.0"),
            "tags": manifest.get("tags", []),
        }
    )
    save_registry_index(index)


def publish_to_remote_registry(bundle_path: Path, endpoint: str, api_key: str) -> tuple[bool, str]:
    if not endpoint.strip():
        return False, "Missing registry endpoint."
    try:
        with open(bundle_path, "rb") as handle:
            bundle_data = handle.read()
        url = endpoint.rstrip("/") + "/upload"
        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/zip",
        }
        req = urllib.request.Request(url, data=bundle_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return True, "Published to remote registry."
            return False, f"Registry returned {resp.status}."
    except Exception as exc:
        return False, f"Registry error: {exc}"


def publish_to_github(agent_path: Path, repo_url: str, branch: str) -> tuple[bool, str]:
    return publish_to_github_with_credentials(agent_path, repo_url, branch, None, None)


def publish_to_github_with_credentials(
    agent_path: Path,
    repo_url: str,
    branch: str,
    username: str | None,
    token: str | None,
) -> tuple[bool, str]:
    git_dir = agent_path / ".git"
    repo = repo_url.strip()
    if username and token and repo.startswith("https://"):
        auth_prefix = f"https://{username}:{token}@"
        repo = repo.replace("https://", auth_prefix, 1)
    try:
        if not git_dir.exists():
            subprocess.run(["git", "init"], cwd=agent_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=agent_path, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=agent_path,
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "branch", "-M", branch], cwd=agent_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "remove", "origin"], cwd=agent_path, check=False, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", repo], cwd=agent_path, check=True, capture_output=True, text=True)
        result = subprocess.run(["git", "push", "-u", "origin", branch], cwd=agent_path, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            return False, result.stderr.strip() or "Git push failed."
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return False, f"Git error: {exc}"
    return True, "Published to GitHub."
def restart_profile_process(agent_name: str, profile: RunProfile, agent_path: Path) -> dict | None:
    state = load_state()
    stopped = False
    for item in list(state.get("processes", [])):
        if item.get("agent") == agent_name and item.get("label") == profile.label:
            stop_process(item["pid"], item.get("pgid"))
            state["processes"] = [
                p for p in state.get("processes", [])
                if not (p.get("agent") == agent_name and p.get("label") == profile.label)
            ]
            stopped = True
    save_state(state)
    if stopped:
        time.sleep(0.3)
    try:
        item = start_process(agent_name, profile, agent_path)
    except Exception:
        return None
    if item.get("pid") is None:
        return None
    state = load_state()
    state.setdefault("processes", []).append(item)
    save_state(state)
    return item
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                command,
                cwd=agent_path,
                shell=True,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
        else:
            wrapped = f"source .venv/bin/activate && {command}"
            result = subprocess.run(
                ["bash", "-lc", wrapped],
                cwd=agent_path,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


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
            HEALTH_MANAGER.clear_manual_stop(agent_name, profile_label)
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


class HealthManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def ensure_started(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run_loop(self) -> None:
        append_health_log("Health loop started.")
        while not self._stop_event.is_set():
            try:
                self._check_health()
            except Exception as exc:
                append_health_log(f"Health error: {exc}")
            self._stop_event.wait(15)

    def _check_health(self) -> None:
        with self._lock:
            health_config = load_health_config()
            profiles_by_agent = load_profiles()
            for agent_name, profiles in profiles_by_agent.items():
                for profile in profiles:
                    key = profile_key(agent_name, profile.label)
                    if key not in health_config:
                        health_config[key] = {
                            "probe_type": "http" if profile.streamlit_port else "disabled",
                            "port": profile.streamlit_port,
                            "probe_command": "",
                            "auto_restart": False,
                        }
            save_health_config(health_config)
            health_state = load_health_state()
            state = refresh_state(load_state())
            running = state.get("processes", [])
            running_keys = {
                profile_key(item["agent"], item["label"]): item for item in running
            }
            now = time.time()

            for key, config in health_config.items():
                agent_name, label = key.split("::", 1)
                status_entry = health_state["profiles"].setdefault(
                    key,
                    {
                        "status": "unknown",
                        "last_check": None,
                        "last_log_time": None,
                        "restart_count": 0,
                        "last_pid": None,
                        "manual_stop": False,
                        "last_ok": None,
                        "last_failure": "",
                    },
                )
                running_item = running_keys.get(key)
                if running_item:
                    status_entry["last_pid"] = running_item.get("pid")
                    log_path = Path(running_item.get("log_path", ""))
                    if log_path.exists():
                        try:
                            status_entry["last_log_time"] = log_path.stat().st_mtime
                        except OSError:
                            pass
                    ok = True
                    probe_type = config.get("probe_type")
                    if probe_type == "disabled":
                        ok = True
                    elif probe_type == "http":
                        port = config.get("port")
                        if isinstance(port, int):
                            ok = http_ping(port)
                        else:
                            ok = False
                    elif probe_type == "command":
                        cmd = config.get("probe_command", "")
                        agent_path = next((p for p in list_agents() if p.name == agent_name), None)
                        ok = bool(agent_path) and run_probe_command(agent_path, cmd)
                    status_entry["status"] = "healthy" if ok else "unhealthy"
                    status_entry["last_check"] = now
                    if ok:
                        status_entry["last_ok"] = now
                        status_entry["last_failure"] = ""
                    else:
                        status_entry["last_failure"] = "health probe failed"
                else:
                    if status_entry.get("last_pid") and config.get("auto_restart") and not status_entry.get("manual_stop"):
                        profiles = load_profiles()
                        profile = None
                        for p in profiles.get(agent_name, []):
                            if p.label == label:
                                profile = p
                                break
                        agent_path = next((p for p in list_agents() if p.name == agent_name), None)
                        if profile and agent_path:
                            try:
                                item = start_process(agent_name, profile, agent_path)
                            except Exception as exc:
                                status_entry["status"] = "stopped"
                                status_entry["last_failure"] = f"restart failed: {exc}"
                            else:
                                if item.get("pid"):
                                    state["processes"].append(item)
                                    save_state(state)
                                    status_entry["restart_count"] = int(
                                        status_entry.get("restart_count", 0)
                                    ) + 1
                                    status_entry["status"] = "running"
                                    status_entry["last_pid"] = item.get("pid")
                                    status_entry["last_check"] = now
                                    status_entry["manual_stop"] = False
                                    append_health_log(
                                        f"Auto-restarted {agent_name}:{label}."
                                    )
                        else:
                            status_entry["status"] = "stopped"
                    else:
                        status_entry["status"] = "stopped"
                        status_entry["last_check"] = now

            save_health_state(health_state)

    def mark_manual_stop(self, agent_name: str, label: str) -> None:
        with self._lock:
            state = load_health_state()
            entry = state["profiles"].setdefault(
                profile_key(agent_name, label),
                {"restart_count": 0},
            )
            entry["manual_stop"] = True
            save_health_state(state)

    def clear_manual_stop(self, agent_name: str, label: str) -> None:
        with self._lock:
            state = load_health_state()
            entry = state["profiles"].setdefault(
                profile_key(agent_name, label),
                {"restart_count": 0},
            )
            entry["manual_stop"] = False
            save_health_state(state)


HEALTH_MANAGER = HealthManager()
atexit.register(HEALTH_MANAGER.stop)


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
HEALTH_MANAGER.ensure_started()

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
    [data-testid="stDownloadButton"] button {
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
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] span,
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] div,
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] * {
        color: #111111 !important;
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
    with st.expander("GitHub credentials", expanded=False):
        st.caption("Used only for publishing to GitHub.")
        st.text_input("GitHub username", key="github-username")
        st.text_input("GitHub token", key="github-token", type="password")
    with st.expander("Emergency controls", expanded=False):
        st.caption("Stop stray processes by port.")
        force_port = st.number_input(
            "Port",
            min_value=1,
            max_value=65535,
            value=8510,
            key="force-stop-port",
        )
        if st.button("Stop process on port", key="force-stop-port-btn"):
            stopped = stop_processes_by_port(int(force_port))
            if stopped:
                st.success(f"Stop signal sent for port {force_port}.")
            else:
                st.warning("No process found on that port.")

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

    overview_tab, files_tab, env_tab, setup_tab, run_tab, automation_tab, marketplace_tab, versioning_tab = st.tabs(
        ["Overview", "Files", "Environments", "Setup", "Run & Monitor", "Automation", "Marketplace", "Versioning"]
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
                    HEALTH_MANAGER.clear_manual_stop(selected_agent.name, profile.label)
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

            st.markdown("#### Health checks")
            health_config = load_health_config()
            health_state = load_health_state()
            for profile in profiles:
                key = profile_key(selected_agent.name, profile.label)
                config = health_config.get(key, {})
                if not config:
                    probe_type = "http" if profile.streamlit_port else "disabled"
                    config = {
                        "probe_type": probe_type,
                        "port": profile.streamlit_port,
                        "probe_command": "",
                        "auto_restart": False,
                    }
                    health_config[key] = config
                    save_health_config(health_config)
                status = health_state.get("profiles", {}).get(key, {})
                with st.expander(f"{profile.label} health", expanded=False):
                    st.markdown(
                        f"**Status:** {status.get('status', 'unknown')} · "
                        f"**Restarts:** {status.get('restart_count', 0)}"
                    )
                    probe_type = st.selectbox(
                        "Probe type",
                        ["http", "command", "disabled"],
                        index=["http", "command", "disabled"].index(config.get("probe_type", "disabled")),
                        key=f"probe-type-{key}",
                    )
                    config["probe_type"] = probe_type
                    if probe_type == "http":
                        port_val = config.get("port") or profile.streamlit_port or 0
                        port_val = st.number_input(
                            "HTTP port",
                            min_value=0,
                            max_value=65535,
                            value=int(port_val),
                            key=f"probe-port-{key}",
                        )
                        config["port"] = int(port_val)
                    elif probe_type == "command":
                        cmd_val = st.text_input(
                            "Probe command",
                            value=config.get("probe_command", ""),
                            key=f"probe-cmd-{key}",
                            placeholder="python3 health_check.py",
                        )
                        config["probe_command"] = cmd_val
                    auto_restart = st.toggle(
                        "Auto-restart on crash",
                        value=bool(config.get("auto_restart", False)),
                        key=f"auto-restart-{key}",
                    )
                    config["auto_restart"] = bool(auto_restart)
                    health_config[key] = config
            save_health_config(health_config)

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
                        key = profile_key(item["agent"], item["label"])
                        health_state = load_health_state()
                        health = health_state.get("profiles", {}).get(key, {})
                        uptime = time.time() - item["started_at"]
                        last_log_time = health.get("last_log_time")
                        last_log_display = (
                            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_log_time))
                            if last_log_time
                            else "n/a"
                        )
                        st.markdown(
                            f"**Status:** {health.get('status', 'unknown')} · "
                            f"**Uptime:** {int(uptime)}s · "
                            f"**Last log line:** {last_log_display} · "
                            f"**Restarts:** {health.get('restart_count', 0)}"
                        )
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
                            HEALTH_MANAGER.mark_manual_stop(item["agent"], item["label"])
                            state = load_state()
                            state["processes"] = [
                                p for p in state.get("processes", [])
                                if p.get("pid") != item["pid"]
                            ]
                            save_state(state)
                            refresh_state(state)
                            st.success("Stop signal sent.")
                            st.rerun()
                        if st.button(
                            f"Restart {item['agent']} {item['label']}",
                            key=f"restart-{item['pid']}",
                        ):
                            profiles = load_profiles().get(item["agent"], [])
                            profile = next((p for p in profiles if p.label == item["label"]), None)
                            if profile:
                                restarted = restart_profile_process(item["agent"], profile, Path(item["cwd"]))
                                if restarted:
                                    state = load_health_state()
                                    entry = state["profiles"].setdefault(
                                        profile_key(item["agent"], item["label"]),
                                        {"restart_count": 0},
                                    )
                                    entry["restart_count"] = int(entry.get("restart_count", 0)) + 1
                                    entry["manual_stop"] = False
                                    save_health_state(state)
                                    st.success("Restarted.")
                                    st.rerun()
                                else:
                                    st.error("Restart failed. Check logs.")
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

    with marketplace_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Agent marketplace / registry")

        metadata = load_metadata()
        current_meta = metadata.get(selected_agent.name, {})

        version = st.text_input(
            "Version",
            value=current_meta.get("version", "0.1.0"),
            key=f"meta-version-{selected_agent.name}",
        )
        tags_raw = st.text_input(
            "Tags (comma-separated)",
            value=", ".join(current_meta.get("tags", [])),
            key=f"meta-tags-{selected_agent.name}",
        )
        description = st.text_area(
            "Description",
            value=current_meta.get("description", ""),
            key=f"meta-desc-{selected_agent.name}",
            height=100,
        )
        if st.button("Save metadata", key=f"save-meta-{selected_agent.name}"):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
            metadata[selected_agent.name] = {
                "version": version.strip() or "0.1.0",
                "tags": tags,
                "description": description.strip(),
            }
            save_metadata(metadata)
            st.success("Metadata saved.")

        st.markdown("#### Export bundle")
        if st.button("Build bundle", key=f"build-bundle-{selected_agent.name}"):
            bundle_path = export_agent_bundle(selected_agent.name, selected_agent)
            st.session_state[f"bundle-path-{selected_agent.name}"] = str(bundle_path)
            st.success(f"Bundle created: {bundle_path.name}")

        bundle_path_str = st.session_state.get(f"bundle-path-{selected_agent.name}")
        if bundle_path_str:
            bundle_path = Path(bundle_path_str)
            if bundle_path.exists():
                st.download_button(
                    "Download bundle",
                    data=bundle_path.read_bytes(),
                    file_name=bundle_path.name,
                    mime="application/zip",
                    key=f"download-bundle-{selected_agent.name}",
                )
                if st.button("Publish to internal registry", key=f"publish-registry-{selected_agent.name}"):
                    publish_to_registry(bundle_path)
                    st.success("Published to internal registry.")
                st.markdown("#### Publish to remote registry")
                registry_url = st.text_input(
                    "Registry endpoint",
                    value="",
                    key=f"registry-url-{selected_agent.name}",
                    placeholder="https://registry.example.com",
                )
                registry_key = st.text_input(
                    "Registry API key",
                    value="",
                    key=f"registry-key-{selected_agent.name}",
                    type="password",
                )
                if st.button("Publish to remote", key=f"publish-remote-{selected_agent.name}"):
                    ok, message = publish_to_remote_registry(bundle_path, registry_url, registry_key)
                    if ok:
                        st.success(message)
                    else:
                        st.error(message)

        st.markdown("#### Publish to GitHub")
        repo_url = st.text_input("Repo URL", value="", key=f"repo-url-{selected_agent.name}")
        branch = st.text_input("Branch", value="main", key=f"repo-branch-{selected_agent.name}")
        if st.button("Publish", key=f"publish-github-{selected_agent.name}"):
            if not repo_url.strip():
                st.error("Provide a repo URL.")
            else:
                username = st.session_state.get("github-username")
                token = st.session_state.get("github-token")
                ok, message = publish_to_github_with_credentials(
                    selected_agent,
                    repo_url.strip(),
                    branch.strip() or "main",
                    username,
                    token,
                )
                if ok:
                    st.success(message)
                else:
                    st.error(message)

        st.markdown("#### Import bundle")
        uploaded = st.file_uploader("Agent bundle (.zip)", type=["zip"])
        overwrite = st.checkbox("Overwrite if agent exists", value=False, key="import-overwrite")
        if st.button("Import bundle"):
            if not uploaded:
                st.error("Upload a bundle first.")
            else:
                ok, message = import_agent_bundle(uploaded.getvalue(), overwrite)
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

        st.markdown("#### Internal registry")
        index = load_registry_index()
        if not index.get("bundles"):
            st.caption("No bundles published yet.")
        else:
            for item in index.get("bundles", []):
                st.markdown(
                    f"- **{item.get('name','')}** v{item.get('version','')} · "
                    f"tags: {', '.join(item.get('tags', []))} · "
                    f"bundle: `{item.get('bundle','')}`"
                )
        st.markdown("</div>", unsafe_allow_html=True)

    with versioning_tab:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Workspace versioning & rollback")

        note = st.text_input("Snapshot note", value="")
        if st.button("Create snapshot"):
            snapshot_path = snapshot_agent(selected_agent.name, selected_agent, note)
            st.success(f"Snapshot created: {snapshot_path.name}")

        index = load_snapshot_index()
        entries = index.get("agents", {}).get(selected_agent.name, [])
        if not entries:
            st.info("No snapshots yet.")
        else:
            entries_sorted = sorted(entries, key=lambda item: item.get("created_at", 0), reverse=True)
            labels = [
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.get('created_at', 0)))} · "
                f"{e.get('version','')} · {e.get('note','') or 'no note'}"
                for e in entries_sorted
            ]
            selection = st.selectbox("Snapshots", labels)
            selected_idx = labels.index(selection)
            snapshot_meta = entries_sorted[selected_idx]
            snapshot_path = Path(snapshot_meta.get("path", ""))
            if snapshot_path.exists():
                st.markdown("#### Diff vs current")
                snapshot = read_snapshot(snapshot_path)
                diff_text = diff_snapshot_to_current(selected_agent, snapshot)
                if diff_text:
                    st.text_area("Unified diff", value=diff_text, height=320)
                else:
                    st.caption("No changes between snapshot and current.")
                if st.button("Revert to snapshot"):
                    ok, message = restore_snapshot(selected_agent.name, selected_agent, snapshot_path)
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
            else:
                st.error("Snapshot file missing.")
        st.markdown("</div>", unsafe_allow_html=True)
