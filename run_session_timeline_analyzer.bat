@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "SCRIPT=%ROOT_DIR%tools\session_timeline_analyzer.py"

if not exist "%SCRIPT%" (
    echo [ERROR] Session timeline analyzer not found: %SCRIPT%
    exit /b 1
)

python "%SCRIPT%"
exit /b %ERRORLEVEL%
