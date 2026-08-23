# Changelog

## Unreleased

- Migrated the legacy Google Drive source into the canonical repository layout.
- Added a single self-elevating root launcher and concise startup checklist.
- Added structured miner detection with the confirmed QuickMiner path first after valid local configuration.
- Added safe TCP 8765 reuse and project-scoped stale bridge cleanup.
- Added BOM-safe, atomic local runtime configuration and Git ignores for mutable state.
- Split bridge health, status, and preflight workloads.
- Added structured API errors and ordinary browser-disconnect handling.
- Added QuickMiner, Excavator, GPU-disabled, positive-hashrate, and explicit mining-state reporting.
- Added thermal stop/resume guardrails and rotating local logs.
- Preserved electricity-ignore behavior without hiding estimated electricity cost.
- Replaced fabricated zero profitability with an unavailable state.
- Added automated bridge, launcher, configuration, JavaScript, and PowerShell tests.

