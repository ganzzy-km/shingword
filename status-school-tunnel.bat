@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\status-school-tunnel.ps1"
exit /b %errorlevel%
