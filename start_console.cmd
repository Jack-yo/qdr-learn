@echo off
cd /d "%~dp0"
echo Open http://127.0.0.1:8765 in your browser. Ctrl+C stops the server.
".venv\Scripts\python.exe" -m quant_research.web
pause
