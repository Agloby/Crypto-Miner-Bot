[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BridgePath = Join-Path $ProjectRoot 'bridge\crypto_bridge.py'
$DashboardPath = Join-Path $ProjectRoot 'dashboard\AI_Passive_Income_Dashboard_Crypto_AutoProfit.html'
$ExampleConfigPath = Join-Path $ProjectRoot 'config\config.example.json'
$RuntimeConfigPath = Join-Path $ProjectRoot 'config\runtime.json'
$LogDirectory = Join-Path $ProjectRoot 'logs'
$LauncherLog = Join-Path $LogDirectory 'launcher.log'
$BridgeUrl = 'http://127.0.0.1:8765'
$ProjectId = 'Agloby/Crypto-Miner-Bot'

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $PSCommandPath)
    )
    exit 0
}

Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Host.UI.RawUI.WindowTitle = 'Crypto Miner One-Click - Administrator'

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format o), $Message
    Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
}

function Pass([string]$Step, [string]$Detail = '') {
    $suffix = if ($Detail) { ': ' + $Detail } else { '' }
    Write-Host ('PASS {0}{1}' -f $Step, $suffix) -ForegroundColor Green
    Write-Log ('PASS {0}{1}' -f $Step, $suffix)
}

function Fail([string]$Step, [string]$Reason) {
    Write-Host ('FAIL {0}: {1}' -f $Step, $Reason) -ForegroundColor Red
    Write-Log ('FAIL {0}: {1}' -f $Step, $Reason)
    Read-Host 'Press Enter to close'
    exit 1
}

function Set-ConfigProperty($Object, [string]$Name, $Value) {
    if ($Object.PSObject.Properties.Name -contains $Name) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Find-Miner($RuntimeConfig) {
    $candidates = [System.Collections.Generic.List[object]]::new()
    if ($RuntimeConfig -and $RuntimeConfig.miner_path) {
        $candidates.Add([PSCustomObject]@{ Path = [Environment]::ExpandEnvironmentVariables([string]$RuntimeConfig.miner_path); Method = 'configured' })
    }
    $candidates.Add([PSCustomObject]@{ Path = 'C:\NiceHash\NiceHash QuickMiner\NiceHashQuickMiner.exe'; Method = 'confirmed_path' })
    @(
        "$env:LOCALAPPDATA\Programs\NiceHashQuickMiner\NiceHashQuickMiner.exe",
        "$env:LOCALAPPDATA\Programs\NiceHashMiner\NiceHashMiner.exe",
        "$env:ProgramFiles\NiceHash QuickMiner\NiceHashQuickMiner.exe",
        "$env:ProgramFiles\NiceHash Miner\NiceHashMiner.exe",
        "${env:ProgramFiles(x86)}\NiceHash QuickMiner\NiceHashQuickMiner.exe",
        "${env:ProgramFiles(x86)}\NiceHash Miner\NiceHashMiner.exe"
    ) | ForEach-Object { if ($_ -and $_ -notmatch '^\\') { $candidates.Add([PSCustomObject]@{ Path = $_; Method = 'common_location' }) } }

    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $candidates) {
        try {
            if (Test-Path -LiteralPath $candidate.Path -PathType Leaf) {
                return [PSCustomObject]@{ Detected = $true; Path = $candidate.Path; Method = $candidate.Method; Error = $null }
            }
            if ($candidate.Method -eq 'configured') { $errors.Add("Configured miner path does not exist: $($candidate.Path)") }
        } catch { $errors.Add("Could not inspect $($candidate.Path): $($_.Exception.Message)") }
    }

    $roots = @('C:\NiceHash', "$env:LOCALAPPDATA\Programs", $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
    foreach ($root in $roots) {
        try {
            if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
            foreach ($name in @('NiceHashQuickMiner.exe', 'NiceHashMiner.exe')) {
                $found = Get-ChildItem -LiteralPath $root -Filter $name -File -Recurse -ErrorAction Stop | Select-Object -First 1
                if ($found) { return [PSCustomObject]@{ Detected = $true; Path = $found.FullName; Method = "targeted_search:$root"; Error = $null } }
            }
        } catch { $errors.Add("Search failed under ${root}: $($_.Exception.Message)") }
    }
    $message = if ($errors.Count) { $errors -join '; ' } else { 'NiceHash QuickMiner or NiceHash Miner was not found' }
    return [PSCustomObject]@{ Detected = $false; Path = $null; Method = $null; Error = $message }
}

function Get-BridgeHealth {
    try { return Invoke-RestMethod -Uri "$BridgeUrl/api/crypto/health" -TimeoutSec 2 }
    catch { return $null }
}

function Get-BridgeStatus {
    try { return Invoke-RestMethod -Uri "$BridgeUrl/api/crypto/status" -TimeoutSec 5 }
    catch { return $null }
}

function Wait-For([scriptblock]$Condition, [int]$Seconds, [int]$PollMilliseconds = 1000) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $result = & $Condition
        if ($result) { return $result }
        Start-Sleep -Milliseconds $PollMilliseconds
    } while ((Get-Date) -lt $deadline)
    return $null
}

Write-Host '==================================================' -ForegroundColor Cyan
Write-Host ' Crypto Miner One-Click startup' -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan
Write-Log 'Launcher startup'
Pass 'Administrator'

$python = $null
foreach ($commandName in @('py.exe', 'python.exe', 'python3.exe')) {
    $candidate = Get-Command $commandName -ErrorAction SilentlyContinue
    if (-not $candidate) { continue }
    try {
        $versionArgs = if ($candidate.Name -eq 'py.exe') { @('-3', '--version') } else { @('--version') }
        $version = & $candidate.Source @versionArgs 2>&1
        if ($LASTEXITCODE -eq 0 -and "$version" -match 'Python 3\.') {
            $python = $candidate
            $pythonVersion = "$version"
            break
        }
    } catch { Write-Log "Python candidate failed: $($candidate.Source): $($_.Exception.Message)" }
}
if (-not $python) { Fail 'Python' 'Python 3 could not be executed. Install Python 3 and disable broken Microsoft Store aliases.' }
Pass 'Python' $pythonVersion

try {
    $gpuLine = & nvidia-smi --query-gpu=name,temperature.gpu,power.draw,utilization.gpu --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    if (-not $gpuLine) { throw 'nvidia-smi returned no GPU row' }
} catch { Fail 'NVIDIA GPU' $_.Exception.Message }
Pass 'NVIDIA GPU' $gpuLine

try {
    $example = Get-Content -Raw -LiteralPath $ExampleConfigPath -Encoding UTF8 | ConvertFrom-Json
} catch { Fail 'Configuration' "config.example.json is missing or invalid: $($_.Exception.Message)" }
$runtime = [PSCustomObject]@{}
if (Test-Path -LiteralPath $RuntimeConfigPath) {
    try { $runtime = Get-Content -Raw -LiteralPath $RuntimeConfigPath -Encoding UTF8 | ConvertFrom-Json }
    catch { Fail 'Configuration' "runtime.json is invalid: $($_.Exception.Message)" }
}
$miner = Find-Miner $runtime
if (-not $miner.Detected) { Fail 'QuickMiner found' $miner.Error }
Pass 'QuickMiner found' "$($miner.Path) [$($miner.Method)]"
Set-ConfigProperty $runtime 'miner_path' $miner.Path
foreach ($property in $example.PSObject.Properties) {
    if ($runtime.PSObject.Properties.Name -notcontains $property.Name) { Set-ConfigProperty $runtime $property.Name $property.Value }
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($RuntimeConfigPath, ($runtime | ConvertTo-Json -Depth 10), $utf8NoBom)
Pass 'Runtime config' 'generated BOM-free'

$bridgeHealth = Get-BridgeHealth
$bridgeProcess = $null
if ($bridgeHealth -and $bridgeHealth.project_id -eq $ProjectId) {
    Pass 'Port 8765' 'healthy project bridge reused'
} else {
    $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        $commandLine = [string]$owner.CommandLine
        if ($commandLine -and ($commandLine -like "*$BridgePath*" -or ($commandLine -like '*crypto_bridge.py*' -and $commandLine -like "*$ProjectRoot*"))) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
            Write-Log "Stopped stale project bridge PID $($listener.OwningProcess)"
        } else {
            Fail 'Port 8765' "Port is owned by unrelated PID $($listener.OwningProcess); it was not terminated."
        }
    }
    Pass 'Port 8765' 'available'
    if (-not (Test-Path -LiteralPath $BridgePath -PathType Leaf)) { Fail 'Bridge' "Missing $BridgePath" }
    $quotedBridgePath = '"{0}"' -f $BridgePath
    $bridgeArgs = if ($python.Name -eq 'py.exe') { @('-3', $quotedBridgePath) } else { @($quotedBridgePath) }
    $bridgeProcess = Start-Process -FilePath $python.Source -ArgumentList $bridgeArgs -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
}

$bridgeHealth = Wait-For { $health = Get-BridgeHealth; if ($health -and $health.project_id -eq $ProjectId) { $health } } 30 500
if (-not $bridgeHealth) { Fail 'Bridge online' "Health endpoint did not become ready. See $LauncherLog and logs\crypto_bridge.log." }
Pass 'Bridge online' "version $($bridgeHealth.version)"

try { $preflight = Invoke-RestMethod -Uri "$BridgeUrl/api/crypto/preflight" -TimeoutSec 15 }
catch {
    $detail = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
    Fail 'Preflight' $detail
}
if (-not $preflight.ok) { Fail 'Preflight' $preflight.message }
Pass 'Preflight' $preflight.message

try { $start = Invoke-RestMethod -Method Post -Uri "$BridgeUrl/api/crypto/start" -ContentType 'application/json' -Body '{}' -TimeoutSec 15 }
catch {
    $detail = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
    Fail 'QuickMiner start' $detail
}
Write-Log "Start result: $($start.result.message)"

$quick = Wait-For { $s = Get-BridgeStatus; if ($s -and $s.quickminer_process_running) { $s } } 45
if (-not $quick) { Fail 'QuickMiner running' 'Process did not appear within 45 seconds.' }
Pass 'QuickMiner running'

$excavator = Wait-For { $s = Get-BridgeStatus; if ($s -and $s.excavator_process_running) { $s } } 90
if (-not $excavator) { Fail 'Excavator detected' 'Excavator did not appear within 90 seconds. Check QuickMiner setup and logs.' }
Pass 'Excavator detected'

$mining = Wait-For {
    $s = Get-BridgeStatus
    if ($s -and $s.gpu_disabled) { Fail 'GPU mining' 'Excavator reports that the GPU is disabled.' }
    if ($s -and $s.gpu_mining -and $s.hashrate -gt 0 -and $s.mining_state -eq 'MINING') { $s }
} 120 2000
if (-not $mining) {
    $last = Get-BridgeStatus
    $reason = if ($last.last_error) { $last.last_error.message } else { "No positive Excavator hashrate was observed; state was $($last.mining_state)." }
    Fail 'GPU mining' $reason
}
Pass 'GPU mining' "hashrate $($mining.hashrate)"

if (-not (Test-Path -LiteralPath $DashboardPath -PathType Leaf)) { Fail 'Dashboard opened' "Missing $DashboardPath" }
Start-Process -FilePath $DashboardPath
Pass 'Dashboard opened'

Write-Host ''
Write-Host 'ALL STARTUP CHECKS PASSED.' -ForegroundColor Green
Write-Host 'The bridge, QuickMiner, Excavator, and positive hashrate were all observed.' -ForegroundColor Green
Write-Host 'Keep this window open or minimized.'
if ($bridgeProcess) { Wait-Process -Id $bridgeProcess.Id }

