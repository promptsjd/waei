@echo off
title WAIE
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-LocalServer.ps1"
if errorlevel 1 pause
