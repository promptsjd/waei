@echo off
title WAIE
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-LocalServer.ps1"
if errorlevel 1 pause
