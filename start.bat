@echo off
cd /d "%~dp0backend"
echo Starting Museum Audio Guide...
echo Open in browser: http://localhost:8000
echo.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
