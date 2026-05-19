@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "SCRIPT_PATH=%ROOT_DIR%tools\test_ocr_client_gui.py"

if defined PYTHON_EXE (
    set "PYTHON_CMD=%PYTHON_EXE%"
) else (
    set "PYTHON_CMD=D:\miniconda3\envs\py39\python.exe"
)

if not exist "%PYTHON_CMD%" (
    echo [ERROR] Python not found: %PYTHON_CMD%
    exit /b 1
)

if not exist "%SCRIPT_PATH%" (
    echo [ERROR] GUI script not found: %SCRIPT_PATH%
    exit /b 1
)

"%PYTHON_CMD%" "%SCRIPT_PATH%"
exit /b %ERRORLEVEL%
