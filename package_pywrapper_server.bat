@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "POWERSHELL_SCRIPT=%ROOT_DIR%tools\package_pywrapper_server.ps1"

if not exist "%POWERSHELL_SCRIPT%" (
    echo [ERROR] PowerShell package script not found: %POWERSHELL_SCRIPT%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%POWERSHELL_SCRIPT%"
exit /b %ERRORLEVEL%
