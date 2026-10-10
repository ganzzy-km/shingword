@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-geulbit.ps1"
exit /b %errorlevel%
