@echo off
cd /d "%~dp0"
echo Start WAIE first. These tests need local samples, excluded from source exports.
echo No external LLM is called.
".venv\Scripts\python.exe" -m unittest -v test_editor_units.py
if errorlevel 1 goto done
".venv\Scripts\python.exe" editor_smoke_test.py
:done
pause
