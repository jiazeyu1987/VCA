@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "SCRIPT_PATH=%ROOT_DIR%tools\hem_roi2_batch_analyzer.py"

if defined PYTHON_EXE (
    set "PYTHON_CMD=%PYTHON_EXE%"
    if not exist "%PYTHON_CMD%" (
        echo [ERROR] Python not found: %PYTHON_CMD%
        exit /b 1
    )
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python command not found. Set PYTHON_EXE or add python to PATH.
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

if not exist "%SCRIPT_PATH%" (
    echo [ERROR] HEM ROI2 batch analyzer not found: %SCRIPT_PATH%
    exit /b 1
)

set "PYTHONDONTWRITEBYTECODE=1"
"%PYTHON_CMD%" "%SCRIPT_PATH%" --gui
exit /b %ERRORLEVEL%
