@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo Run setup_env.bat first, then run this file again.
    exit /b 1
)

".venv\Scripts\python.exe" -m chainlit run chainlit_app.py --host 127.0.0.1 --port 8000
