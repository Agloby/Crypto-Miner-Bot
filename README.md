# Crypto Miner Bot

Windows automation for starting NiceHash QuickMiner, verifying an NVIDIA GPU is actually hashing, and controlling it from the existing AI Passive Income dashboard.

The project uses one entry point: double-click `START_EVERYTHING.bat`. The launcher requests Administrator access once, generates local configuration, reuses a healthy project bridge or removes only a stale project-owned bridge, runs preflight checks, starts QuickMiner without duplication, waits for Excavator and positive hashrate, and then opens the dashboard.

## Prerequisites

- Windows 10 or 11.
- An NVIDIA GPU with a working driver and `nvidia-smi` on `PATH`.
- Python 3.10 or newer. Microsoft Store Python is supported only when its `python.exe` or `py.exe` command actually launches Python.
- [NiceHash QuickMiner](https://www.nicehash.com/quick-miner), installed and configured by the user. The preferred path is `C:\NiceHash\NiceHash QuickMiner\NiceHashQuickMiner.exe`.
- A completed QuickMiner setup, including acceptance of NiceHash terms and the user's own payout/mining configuration.

No wallet private key, seed phrase, NiceHash password, or API secret belongs in this repository. The app does not need any wallet private key.

## One-click startup

1. Close obsolete copies of the old Google Drive launcher.
2. Double-click `START_EVERYTHING.bat` in this repository.
3. Approve the single UAC prompt.
4. Read the `PASS`/`FAIL` checklist. The dashboard opens only after the bridge, QuickMiner, Excavator, and positive hashrate have been observed.

The launcher prefers the confirmed QuickMiner location, but detection checks a valid runtime setting first, then common QuickMiner and NiceHash Miner locations, then searches only likely installation roots.

## Dashboard behavior

The Crypto Mining page reports bridge, QuickMiner, Excavator, GPU, mining state, hashrate, temperature, power, utilization, profitability source, gross revenue, electricity cost, decision profit, last update, and the last structured error.

`MINING` requires positive hashrate from Excavator's local API. A QuickMiner process alone is `STARTING` or `IDLE`; a disabled Excavator GPU can never be labeled as mining.

NiceHash-native switching is the default. If no reliable gross earnings value is available, the dashboard displays `Unavailable`, not a fabricated `€0/day`. A user may enter a locally sourced gross estimate in the dashboard. When **Ignore electricity cost** is selected, decision profit equals gross revenue while estimated electricity remains visible.

## Configuration and local files

`config/config.example.json` contains safe defaults. On startup the launcher creates or updates `config/runtime.json` as BOM-free UTF-8. Runtime configuration and `logs/` are ignored by Git because they are machine-specific.

Thermal defaults are 78°C stop and 70°C resume. Automatic resume is disabled by default; enable `auto_resume_after_thermal_stop` locally only after validating your cooling and QuickMiner configuration.

## Tests

From PowerShell at the repository root:

```powershell
py -3 -m unittest discover -s tests -v
```

The suite uses mocks for process, GPU, and Excavator behavior. It also parses the PowerShell launcher and checks the dashboard JavaScript with Node.js. Node.js is therefore required for the full developer test suite, but not for normal mining use.

## Updating

Use Git to pull reviewed changes from `main`, then rerun the tests. Do not copy newer files back from the retired Google Drive project; this repository is the canonical source. Preserve `config/runtime.json` as local state and review `config/config.example.json` for newly introduced settings.

## Troubleshooting and design

- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Changelog](docs/CHANGELOG.md)

Mining has financial, electrical, thermal, hardware-wear, tax, and account-policy implications. This project controls local software; it does not guarantee profitability or hardware safety.

