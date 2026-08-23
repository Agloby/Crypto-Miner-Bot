# Architecture

## Startup flow

`START_EVERYTHING.bat` invokes `launcher/ONE_CLICK_START.ps1`. The script self-elevates once, verifies executable Python and NVIDIA telemetry, detects QuickMiner, writes local runtime configuration without a BOM, and checks TCP 8765.

A bridge is reusable only when `/api/crypto/health` returns this repository's project identifier. If the port is held by a stale command line from this project, that PID alone is stopped. Unrelated processes and generic Python processes are never killed.

After launching or reusing the bridge, the launcher calls the slower `/preflight` endpoint once, requests `/start`, and polls lightweight `/status`. It opens the dashboard only after QuickMiner, Excavator, and positive Excavator hashrate are all observed.

## Bridge API

The Python standard-library bridge binds only to `127.0.0.1:8765`:

- `GET /api/crypto/health`: constant, lightweight identity/readiness response.
- `GET /api/crypto/status`: cached live state suitable for dashboard polling; it does not run miner detection or full preflight.
- `GET /api/crypto/preflight`: administrator, miner detection, and NVIDIA checks.
- `POST /api/crypto/start`: guarded, duplicate-safe miner start.
- `POST /api/crypto/stop`: targeted QuickMiner/NiceHash Miner/Excavator stop.
- `POST /api/crypto/config`: allowlisted local runtime settings.

Normal client disconnect exceptions are absorbed at the response and server layers. Other exceptions are written to a rotating local log.

## Mining state model

The bridge separates process and hardware signals. `quickminer_process_running` and `excavator_process_running` are independent. `gpu_mining` requires a running Excavator process, a non-disabled GPU indication, and positive hashrate from the local Excavator JSON-RPC service (normally port 3456).

States are `OFFLINE`, `IDLE`, `STARTING`, `MINING`, `STOPPING`, `ERROR`, and `THERMAL_STOP`. GPU power or utilization is displayed as telemetry but is not sufficient by itself to claim hashing.

## Configuration and security boundary

Committed defaults live in `config/config.example.json`. Generated `config/runtime.json` and all logs are ignored. Configuration writes are atomic, BOM-free UTF-8, and API updates use an allowlist. The HTTP service is loopback-only and stores no wallet seed, private key, account cookie, or NiceHash credential.

## Profitability and thermal policy

NiceHash-native algorithm switching remains authoritative. Gross revenue is nullable. Electricity cost is calculated from observed GPU power and the configured tariff; ignoring electricity changes only the decision profit, not the displayed cost. Thermal monitoring stops mining at the configured maximum. Optional automatic resume requires both explicit enablement and cooling below the resume threshold.

