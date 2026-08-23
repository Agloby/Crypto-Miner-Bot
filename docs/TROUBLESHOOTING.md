# Troubleshooting

## `FAIL Python`

Run `py -3 --version` and `python --version` in PowerShell. If both fail or open the Microsoft Store, install Python 3 and disable broken App Execution Aliases in Windows Settings. The launcher never treats an alias as valid unless it returns a Python 3 version.

## `FAIL QuickMiner found`

Confirm `C:\NiceHash\NiceHash QuickMiner\NiceHashQuickMiner.exe` exists. The launcher reports configured-path and targeted-search errors instead of hiding them. Do not put a JSON path in quotes with unescaped backslashes by hand; normally the launcher writes `config/runtime.json` safely.

## `FAIL Port 8765`

A healthy bridge from this repository is reused. A stale listener is terminated only when its command line identifies this project's `bridge\crypto_bridge.py`. An unrelated listener is left untouched and its PID is shown. Stop or reconfigure that application, then relaunch.

Useful inspection command:

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object LocalAddress,OwningProcess
```

## `ADMIN_REQUIRED` or WinError 740

Start only through `START_EVERYTHING.bat` and approve UAC. Do not start `bridge\crypto_bridge.py` directly from a non-elevated terminal if you expect it to launch QuickMiner.

## Bridge is online but QuickMiner does not start

Read `logs\launcher.log` and `logs\crypto_bridge.log`. The dashboard preserves the structured error code and message, so a miner path, thermal limit, permission, or profitability error is not mislabeled as a network failure.

## QuickMiner runs but state stays `STARTING` or `IDLE`

The process is not proof of mining. Check QuickMiner's own interface for initial setup, accepted terms, active optimization, connection status, and device enablement. `excavator.exe` must be running, its local API must respond, the GPU must not be disabled, and a positive speed must be reported before the dashboard shows `MINING`.

## `GPU disabled`

Open QuickMiner and enable the RTX 2070 SUPER. Check driver compatibility, optimization profile, mining address, and any NiceHash-side restrictions. The dashboard intentionally refuses to infer mining from GPU utilization alone.

## `THERMAL_STOP`

The default stop temperature is 78°C. Improve cooling or reduce the QuickMiner optimization profile. Automatic resume is off by default. If enabled locally, resume is attempted only after temperature falls to 70°C or below.

## Revenue says `Unavailable`

That is intentional when no reliable earnings input exists. NiceHash controls algorithm switching, but its public reachability is not a precise local EUR/day measurement. Enter a reliable local gross estimate if desired; never interpret `Unavailable` as zero.

## Browser disconnect messages

Ordinary `BrokenPipeError`, WinError 10053/`ConnectionAbortedError`, and connection resets are suppressed. Repeated tracebacks in `logs\crypto_bridge.log` indicate an unexpected server error and should be reported with the surrounding log lines.

