@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "POWERSHELL_SCRIPT=%ROOT_DIR%tools\restart_server.ps1"

if not exist "%POWERSHELL_SCRIPT%" (
    echo [ERROR] PowerShell restart script not found: %POWERSHELL_SCRIPT%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%POWERSHELL_SCRIPT%"
exit /b %ERRORLEVEL%
