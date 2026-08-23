#!/usr/bin/env python3
"""Local-only NiceHash QuickMiner control bridge."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterable
import ctypes
import json
import logging
import os
import socket
import subprocess
import threading
import time

PROJECT_ID = "Agloby/Crypto-Miner-Bot"
HOST, PORT = "127.0.0.1", 8765
ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "config" / "config.example.json"
RUNTIME_CONFIG = ROOT / "config" / "runtime.json"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "crypto_bridge.log"
KNOWN_QUICKMINER = Path(r"C:\NiceHash\NiceHash QuickMiner\NiceHashQuickMiner.exe")
_LAST_GPU_WARNING = 0.0

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("crypto_bridge")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    """Read UTF-8 JSON with or without a BOM."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return deepcopy(default)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.error("JSON read failed for %s: %s", path, exc)
        return deepcopy(default)


def save_json(path: Path, value: Any) -> None:
    """Atomically write BOM-free UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def config() -> dict[str, Any]:
    base = load_json(EXAMPLE_CONFIG, {})
    runtime = load_json(RUNTIME_CONFIG, {})
    if isinstance(runtime, dict):
        base.update(runtime)
    return base


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _candidate_entries(cfg: dict[str, Any]) -> list[tuple[Path, str]]:
    values: list[tuple[Path, str]] = []
    configured = str(cfg.get("miner_path") or "").strip()
    if configured:
        values.append((Path(os.path.expandvars(os.path.expanduser(configured))), "configured"))
    values.append((KNOWN_QUICKMINER, "confirmed_path"))
    local = os.environ.get("LOCALAPPDATA")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    common = [
        Path(r"C:\NiceHash\NiceHashQuickMiner\NiceHashQuickMiner.exe"),
        Path(pf) / "NiceHash QuickMiner" / "NiceHashQuickMiner.exe",
        Path(pfx86) / "NiceHash QuickMiner" / "NiceHashQuickMiner.exe",
        Path(pf) / "NiceHash Miner" / "NiceHashMiner.exe",
        Path(pfx86) / "NiceHash Miner" / "NiceHashMiner.exe",
    ]
    if local:
        common[0:0] = [
            Path(local) / "Programs" / "NiceHashQuickMiner" / "NiceHashQuickMiner.exe",
            Path(local) / "Programs" / "NiceHashMiner" / "NiceHashMiner.exe",
        ]
    values.extend((path, "common_location") for path in common)
    return values


def _search_roots() -> list[Path]:
    roots = [Path(r"C:\NiceHash")]
    for key in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value) / "Programs" if key == "LOCALAPPDATA" else Path(value))
    return roots


def detect_miner_path(
    cfg: dict[str, Any] | None = None,
    candidates: Iterable[tuple[Path, str]] | None = None,
    search_roots: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Return path, method, and all non-fatal detection errors."""
    cfg = config() if cfg is None else cfg
    errors: list[str] = []
    seen: set[str] = set()
    entries = list(candidates) if candidates is not None else _candidate_entries(cfg)
    for path, method in entries:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                return {"detected": True, "path": str(path), "method": method, "error": None, "errors": errors}
            if method == "configured":
                errors.append(f"Configured miner path does not exist: {path}")
        except OSError as exc:
            errors.append(f"Could not inspect {path}: {exc}")
    for root in (list(search_roots) if search_roots is not None else _search_roots()):
        try:
            if not root.is_dir():
                continue
            for filename in ("NiceHashQuickMiner.exe", "NiceHashMiner.exe"):
                for path in root.rglob(filename):
                    if path.is_file():
                        return {"detected": True, "path": str(path), "method": f"targeted_search:{root}", "error": None, "errors": errors}
        except OSError as exc:
            errors.append(f"Search failed under {root}: {exc}")
    error = "; ".join(errors) if errors else "NiceHash QuickMiner or NiceHash Miner was not found"
    return {"detected": False, "path": None, "method": None, "error": error, "errors": errors}


def nvidia_telemetry() -> dict[str, Any] | None:
    global _LAST_GPU_WARNING
    command = ["nvidia-smi", "--query-gpu=name,temperature.gpu,power.draw,utilization.gpu", "--format=csv,noheader,nounits"]
    try:
        line = subprocess.check_output(command, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip().splitlines()[0]
        name, temperature, power, utilization = (item.strip() for item in line.split(",", 3))
        return {"name": name, "temperature_c": float(temperature), "power_w": float(power), "utilization_pct": float(utilization)}
    except (OSError, subprocess.SubprocessError, IndexError, ValueError) as exc:
        if time.monotonic() - _LAST_GPU_WARNING >= 60:
            logger.warning("NVIDIA telemetry unavailable: %s", exc)
            _LAST_GPU_WARNING = time.monotonic()
        return None


def _task_running(image_name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        output = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"], text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return f'"{image_name}"' in output or image_name in output
    except (OSError, subprocess.SubprocessError):
        return False


def _numbers_for_keys(value: Any, parent_key: str = "") -> list[float]:
    found: list[float] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            if isinstance(child, (int, float)) and any(token in lowered for token in ("hashrate", "speed")):
                found.append(float(child))
            else:
                found.extend(_numbers_for_keys(child, lowered))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (int, float)) and any(token in parent_key for token in ("hashrate", "speed")):
                found.append(float(child))
            else:
                found.extend(_numbers_for_keys(child, parent_key))
    return found


def _contains_disabled(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in {"disabled", "is_disabled"} and child is True:
                return True
            if lowered in {"status", "state"} and str(child).casefold() == "disabled":
                return True
            if _contains_disabled(child):
                return True
    elif isinstance(value, list):
        return any(_contains_disabled(child) for child in value)
    return False


def excavator_rpc(method: str, port: int = 3456) -> dict[str, Any]:
    request = json.dumps({"id": 1, "method": method, "params": []}).encode() + b"\n"
    with socket.create_connection((HOST, port), timeout=2) as connection:
        connection.sendall(request)
        connection.settimeout(2)
        chunks = bytearray()
        while len(chunks) < 1_000_000:
            piece = connection.recv(65536)
            if not piece:
                break
            chunks.extend(piece)
            if b"\n" in piece:
                break
    return json.loads(bytes(chunks).decode("utf-8").strip())


def excavator_status(rpc=excavator_rpc) -> dict[str, Any]:
    responses, errors = [], []
    for method in ("algorithm.list", "worker.list", "device.list"):
        try:
            responses.append(rpc(method))
        except (OSError, UnicodeError, json.JSONDecodeError, TimeoutError) as exc:
            errors.append(f"{method}: {exc}")
    response_rates = [[number for number in _numbers_for_keys(response) if number > 0] for response in responses]
    totals = [sum(rates) for rates in response_rates if rates]
    return {
        "api_reachable": bool(responses),
        "hashrate": max(totals) if totals else None,
        "gpu_disabled": any(_contains_disabled(response) for response in responses),
        "error": "; ".join(errors) if errors and not responses else None,
    }


def compute_profitability(cfg: dict[str, Any], gpu: dict[str, Any] | None) -> dict[str, Any]:
    raw_gross = cfg.get("gross_revenue_eur_per_day")
    gross = None if raw_gross in (None, "") else float(raw_gross)
    power = None if not gpu else gpu.get("power_w")
    electricity = None if power is None else float(power) / 1000 * 24 * float(cfg.get("electricity_eur_per_kwh", 0) or 0)
    ignore = bool(cfg.get("ignore_electricity_cost", False))
    decision_profit = None if gross is None else gross if ignore else gross - float(electricity or 0)
    threshold = float(cfg.get("minimum_profit_eur_per_day", 0) or 0)
    decision = "UNAVAILABLE" if decision_profit is None else "MINE" if decision_profit >= threshold else "DO_NOT_MINE"
    return {"decision": decision, "gross_revenue_per_day": gross, "electricity_cost_per_day": electricity, "decision_profit_per_day": decision_profit, "profitability_source": "nicehash_native", "ignore_electricity_cost": ignore, "minimum_profit_per_day": threshold}


@dataclass
class BridgeState:
    managed_process: subprocess.Popen | None = None
    desired_mining: bool = False
    thermal_stopped: bool = False
    transition: str | None = None
    last_error: dict[str, str] | None = None
    status_cache: dict[str, Any] | None = None
    status_cache_time: float = 0.0
    lock: threading.RLock = field(default_factory=threading.RLock)


STATE = BridgeState()


def _managed_running() -> bool:
    return STATE.managed_process is not None and STATE.managed_process.poll() is None


def quickminer_process_running() -> bool:
    return _managed_running() or _task_running("NiceHashQuickMiner.exe") or _task_running("NiceHashMiner.exe")


def excavator_process_running() -> bool:
    return _task_running("excavator.exe")


def preflight() -> dict[str, Any]:
    detection, gpu, admin = detect_miner_path(), nvidia_telemetry(), is_admin()
    reasons = []
    if os.name == "nt" and not admin:
        reasons.append("Bridge is not running as Administrator")
    if not detection["detected"]:
        reasons.append(detection["error"])
    if gpu is None:
        reasons.append("NVIDIA GPU telemetry is unavailable; nvidia-smi failed")
    result = {"ok": not reasons, "admin": admin, "python": os.sys.executable, "gpu_detected": gpu is not None, "gpu": gpu, "miner": detection, "config_path": str(RUNTIME_CONFIG), "message": "Preflight passed" if not reasons else "; ".join(str(item) for item in reasons), "last_update": now_iso()}
    logger.info("Preflight: %s", result["message"])
    return result


def _live_status() -> dict[str, Any]:
    cfg, gpu = config(), nvidia_telemetry()
    quickminer, excavator = quickminer_process_running(), excavator_process_running()
    ex = excavator_status() if excavator else {"api_reachable": False, "hashrate": None, "gpu_disabled": False, "error": None}
    hashrate, disabled = ex["hashrate"], bool(ex["gpu_disabled"])
    mining = bool(excavator and not disabled and hashrate is not None and hashrate > 0)
    if mining:
        STATE.transition = None
    if STATE.thermal_stopped:
        mining_state = "THERMAL_STOP"
    elif STATE.last_error:
        mining_state = "ERROR"
    elif mining:
        mining_state = "MINING"
    elif STATE.transition:
        mining_state = STATE.transition
    elif quickminer or excavator:
        mining_state = "IDLE" if not STATE.desired_mining else "STARTING"
    else:
        mining_state = "OFFLINE"
    profitability = compute_profitability(cfg, gpu)
    if STATE.thermal_stopped:
        profitability["decision"] = "THERMAL_STOP"
    return {"bridge_online": True, "quickminer_process_running": quickminer, "excavator_process_running": excavator, "gpu_detected": gpu is not None, "gpu_mining": mining, "gpu_disabled": disabled, "mining_state": mining_state, "hashrate": hashrate, "gpu_name": None if not gpu else gpu["name"], "gpu_temperature": None if not gpu else gpu["temperature_c"], "gpu_power": None if not gpu else gpu["power_w"], "gpu_utilization": None if not gpu else gpu["utilization_pct"], **profitability, "last_update": now_iso(), "last_error": STATE.last_error, "excavator_api_reachable": ex["api_reachable"], "config": {key: cfg.get(key) for key in ("ignore_electricity_cost", "minimum_profit_eur_per_day", "electricity_eur_per_kwh", "max_gpu_temp_c", "resume_gpu_temp_c", "auto_resume_after_thermal_stop")}}


def status(force: bool = False) -> dict[str, Any]:
    with STATE.lock:
        if not force and STATE.status_cache and time.monotonic() - STATE.status_cache_time < 2:
            return deepcopy(STATE.status_cache)
        STATE.status_cache, STATE.status_cache_time = _live_status(), time.monotonic()
        return deepcopy(STATE.status_cache)


def _error(code: str, message: str) -> tuple[bool, dict[str, str]]:
    STATE.last_error, STATE.transition = {"code": code, "message": message}, None
    logger.error("%s: %s", code, message)
    return False, STATE.last_error


def start_mining() -> tuple[bool, dict[str, Any]]:
    with STATE.lock:
        STATE.last_error, STATE.thermal_stopped, STATE.desired_mining = None, False, True
        cfg, telemetry = config(), nvidia_telemetry()
        if telemetry is None:
            return _error("GPU_TELEMETRY_UNAVAILABLE", "NVIDIA GPU telemetry is unavailable; nvidia-smi failed")
        if telemetry["temperature_c"] >= float(cfg.get("max_gpu_temp_c", 78) or 78):
            STATE.thermal_stopped = True
            return _error("THERMAL_LIMIT", f"GPU is at {telemetry['temperature_c']}°C; limit is {cfg.get('max_gpu_temp_c', 78)}°C")
        if compute_profitability(cfg, telemetry)["decision"] == "DO_NOT_MINE":
            return _error("BELOW_PROFIT_THRESHOLD", "Estimated decision profit is below the configured threshold")
        if quickminer_process_running():
            STATE.transition = "STARTING"
            logger.info("QuickMiner already running; duplicate launch avoided")
            return True, {"code": "ALREADY_RUNNING", "message": "QuickMiner already running; waiting for hashing evidence"}
        detection = detect_miner_path(cfg)
        if not detection["detected"]:
            return _error("MINER_NOT_FOUND", str(detection["error"]))
        if os.name == "nt" and not is_admin():
            return _error("ADMIN_REQUIRED", "Bridge is not elevated. Run START_EVERYTHING.bat and approve UAC.")
        path = Path(str(detection["path"]))
        try:
            STATE.transition = "STARTING"
            STATE.managed_process = subprocess.Popen([str(path), *map(str, cfg.get("miner_args", []))], cwd=str(cfg.get("miner_working_dir") or path.parent), creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0)
            logger.info("Started QuickMiner from %s (%s)", path, detection["method"])
            STATE.status_cache_time = 0
            return True, {"code": "STARTED", "message": f"Started {path.name}; waiting for Excavator hashrate"}
        except OSError as exc:
            if getattr(exc, "winerror", None) == 740:
                return _error("ADMIN_REQUIRED", "QuickMiner requires Administrator elevation. Relaunch START_EVERYTHING.bat and approve UAC.")
            return _error("MINER_LAUNCH_FAILED", f"Windows failed to launch QuickMiner: {exc}")


def stop_mining(thermal: bool = False) -> tuple[bool, dict[str, Any]]:
    with STATE.lock:
        STATE.transition, STATE.desired_mining = "STOPPING", False
        errors = []
        if _managed_running():
            try:
                STATE.managed_process.terminate(); STATE.managed_process.wait(timeout=15)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
                try: STATE.managed_process.kill()
                except OSError as kill_error: errors.append(str(kill_error))
            STATE.managed_process = None
        elif os.name == "nt" and (quickminer_process_running() or excavator_process_running()):
            for image in ("NiceHashQuickMiner.exe", "NiceHashMiner.exe", "excavator.exe"):
                if not _task_running(image):
                    continue
                result = subprocess.run(["taskkill", "/IM", image, "/T", "/F"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode not in (0, 128): errors.append((result.stderr or result.stdout).strip())
        STATE.thermal_stopped, STATE.transition, STATE.status_cache_time = thermal, None, 0
        if errors:
            return _error("MINER_STOP_FAILED", "; ".join(item for item in errors if item))
        STATE.last_error = None if not thermal else {"code": "THERMAL_STOP", "message": "Mining stopped at the configured temperature limit"}
        logger.warning("Thermal stop activated") if thermal else logger.info("QuickMiner stop requested")
        return True, {"code": "THERMAL_STOP" if thermal else "STOPPED", "message": "Mining stopped"}


def thermal_action(snapshot: dict[str, Any], cfg: dict[str, Any], thermal_stopped: bool) -> str | None:
    """Return stop/resume without performing a process mutation."""
    temperature = snapshot.get("gpu_temperature")
    if temperature is None:
        return None
    if snapshot.get("gpu_mining") and temperature >= float(cfg.get("max_gpu_temp_c", 78) or 78):
        return "stop"
    if thermal_stopped and cfg.get("auto_resume_after_thermal_stop", False) and temperature <= float(cfg.get("resume_gpu_temp_c", 70) or 70):
        return "resume"
    return None


def thermal_loop() -> None:
    while True:
        try:
            cfg, snapshot = config(), status(force=True)
            action = thermal_action(snapshot, cfg, STATE.thermal_stopped)
            if action == "stop":
                stop_mining(thermal=True)
            elif action == "resume":
                logger.info("GPU cooled to %s°C; attempting automatic resume", snapshot["gpu_temperature"]); start_mining()
        except Exception:
            logger.exception("Unexpected thermal monitor failure")
        time.sleep(5)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads, allow_reuse_address = True, True
    def handle_error(self, request, client_address):
        import sys
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        logger.exception("Unexpected HTTP server error from %s", client_address)


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    def _json(self, payload: Any, http_status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(http_status); self.send_header("Content-Type", "application/json"); self._cors(); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/crypto/health": self._json({"ok": True, "bridge_online": True, "project_id": PROJECT_ID, "version": "5.0"})
        elif path == "/api/crypto/status": self._json(status())
        elif path == "/api/crypto/preflight":
            result = preflight(); self._json(result, 200 if result["ok"] else 409)
        else: self._json({"error": {"code": "NOT_FOUND", "message": "Endpoint not found"}}, 404)
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or 0); payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON"}}, 400); return
        if not isinstance(payload, dict):
            self._json({"error": {"code": "INVALID_JSON", "message": "Request body must be a JSON object"}}, 400); return
        if self.path == "/api/crypto/start":
            ok, result = start_mining(); self._json({"ok": ok, "result": result, "status": status(force=True)}, 200 if ok else 409)
        elif self.path == "/api/crypto/stop":
            ok, result = stop_mining(); self._json({"ok": ok, "result": result, "status": status(force=True)}, 200 if ok else 409)
        elif self.path == "/api/crypto/config":
            current = load_json(RUNTIME_CONFIG, {})
            allowed = {"ignore_electricity_cost", "minimum_profit_eur_per_day", "electricity_eur_per_kwh", "max_gpu_temp_c", "resume_gpu_temp_c", "auto_resume_after_thermal_stop", "gross_revenue_eur_per_day", "miner_path", "miner_working_dir", "miner_args"}
            current.update({key: value for key, value in payload.items() if key in allowed}); save_json(RUNTIME_CONFIG, current)
            logger.info("Runtime configuration updated: %s", ", ".join(sorted(set(payload) & allowed))); self._json({"ok": True, "config": config()})
        else: self._json({"error": {"code": "NOT_FOUND", "message": "Endpoint not found"}}, 404)
    def log_message(self, *_args):
        return


def main() -> None:
    logger.info("Bridge startup: project=%s address=%s:%s", PROJECT_ID, HOST, PORT)
    threading.Thread(target=thermal_loop, daemon=True, name="thermal-monitor").start()
    try: QuietThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except OSError as exc:
        logger.error("Bridge could not bind %s:%s: %s", HOST, PORT, exc); raise


if __name__ == "__main__":
    main()

