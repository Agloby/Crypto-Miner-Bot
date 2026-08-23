@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\ONE_CLICK_START.ps1"
exit /b %ERRORLEVEL%

