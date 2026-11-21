@echo off
cd /d "%~dp0"
echo Start WAIE first. These tests need local samples, excluded from source exports.
".venv\Scripts\python.exe" smoke_test.py --vision --transcribe
pause
