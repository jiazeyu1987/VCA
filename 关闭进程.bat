@echo off
setlocal EnableExtensions

call "%~dp0closeserver.bat"

exit /b %ERRORLEVEL%
