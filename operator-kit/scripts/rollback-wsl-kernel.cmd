@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0rollback-wsl-kernel.ps1"
exit /b %errorlevel%
