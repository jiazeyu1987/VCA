@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$connections = @(Get-NetTCPConnection -State Listen -LocalPort 30415 -ErrorAction SilentlyContinue); " ^
  "if (-not $connections) { Write-Host '[INFO] No listener is bound to port 30415.'; exit 0 }; " ^
  "$pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique; " ^
  "foreach ($pid in $pids) { Write-Host ('[INFO] Terminating PID ' + $pid + ' bound to port 30415.'); Stop-Process -Id $pid -Force -ErrorAction Stop };"

exit /b %ERRORLEVEL%
