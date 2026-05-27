@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; " ^
  "$netstatOutput = @(netstat -ano -p tcp); " ^
  "if ($LASTEXITCODE -ne 0) { throw ('netstat failed with exit code ' + $LASTEXITCODE) }; " ^
  "$listenerPids = @(); " ^
  "foreach ($line in $netstatOutput) { " ^
  "  $match = [regex]::Match($line, '^\s*TCP\s+\S+:30415\s+\S+\s+LISTENING\s+(\d+)\s*$'); " ^
  "  if ($match.Success) { $listenerPids += [int]$match.Groups[1].Value } " ^
  "}; " ^
  "$namedProcesses = @(Get-Process -Name 'ocrapp_pureray' -ErrorAction SilentlyContinue); " ^
  "$targetPids = @(); " ^
  "$targetPids += $listenerPids | Select-Object -Unique; " ^
  "$targetPids += $namedProcesses | Select-Object -ExpandProperty Id -Unique; " ^
  "$targetPids = @($targetPids | Where-Object { $_ } | Select-Object -Unique); " ^
  "if (-not $targetPids) { Write-Host '[INFO] No listener is bound to port 30415 and no ocrapp_pureray process is running.'; exit 0 }; " ^
  "foreach ($targetPid in $targetPids) { " ^
  "  $process = Get-Process -Id $targetPid -ErrorAction SilentlyContinue; " ^
  "  if ($null -eq $process) { continue }; " ^
  "  Write-Host ('[INFO] Terminating PID ' + $targetPid + ' (' + $process.ProcessName + ').'); " ^
  "  Stop-Process -Id $targetPid -Force -ErrorAction Stop " ^
  "};"

exit /b %ERRORLEVEL%
