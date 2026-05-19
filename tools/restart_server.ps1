$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path $PSScriptRoot -Parent
$stopScript = Join-Path $workspaceRoot "closeserver.bat"
$serverExe = Join-Path $workspaceRoot "dist\OCRSERVER\ocrapp_pureray.exe"
$serverPort = 30415
$stopWaitDeadline = (Get-Date).AddSeconds(10)

Write-Host "[INFO] Workspace root: $workspaceRoot"
Write-Host "[INFO] Stop script: $stopScript"
Write-Host "[INFO] Server exe: $serverExe"

if (-not (Test-Path $stopScript)) {
    throw "Stop script not found: $stopScript"
}

if (-not (Test-Path $serverExe)) {
    throw "Server executable not found: $serverExe"
}

& $stopScript
if ($LASTEXITCODE -ne 0) {
    throw "Stop script failed with exit code $LASTEXITCODE"
}

do {
    Start-Sleep -Milliseconds 500
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $serverPort -ErrorAction SilentlyContinue)
    if (-not $listeners) {
        break
    }
} while ((Get-Date) -lt $stopWaitDeadline)

$remainingListeners = @(Get-NetTCPConnection -State Listen -LocalPort $serverPort -ErrorAction SilentlyContinue)
if ($remainingListeners) {
    throw "Port $serverPort is still occupied after stop attempt."
}

$serverDir = Split-Path $serverExe -Parent
$process = Start-Process -FilePath $serverExe -WorkingDirectory $serverDir -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 2
$process.Refresh()
if ($process.HasExited) {
    throw "Server process exited immediately after launch. PID=$($process.Id)"
}

Write-Host "[OK] Server restarted. PID=$($process.Id)"
