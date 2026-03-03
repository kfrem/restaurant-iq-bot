@echo off
REM Restaurant-IQ Windows Setup Script
REM Run this ONCE from inside C:\RestaurantIQ after copying all .py files there

echo ==========================================
echo  Restaurant-IQ Setup
echo ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from https://python.org
    echo Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
) else (
    echo Python found.
)

REM Check Ollama
ollama --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: Ollama not found on PATH.
    echo Install Ollama from https://ollama.ai and ensure it is running before starting the bot.
) else (
    echo Ollama found.
)

REM Install Python dependencies
echo.
echo Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo Dependencies installed.

REM Pull Ollama models (first-time download, may take several minutes)
echo.
echo Pulling Ollama AI models (this only runs once — may take a few minutes)...
ollama pull gemma3:4b
ollama pull qwen3-vl:30b

REM Create .env if it does not exist
echo.
if not exist ".env" (
    echo Creating .env from .env.example...
    copy .env.example .env
    echo.
    echo ACTION REQUIRED: Open .env in Notepad and replace "your_token_here"
    echo with your actual Telegram bot token from @BotFather.
    echo.
    notepad .env
) else (
    echo .env already exists.
)

REM Create directories
if not exist "reports"     mkdir reports
if not exist "voice_files" mkdir voice_files
if not exist "photo_files" mkdir photo_files

echo.
echo ==========================================
echo  Setup complete!
echo ==========================================
echo.
echo To start the bot:
echo   1. Make sure Ollama is running (open Ollama from your taskbar or run: ollama serve)
echo   2. Run: python bot.py
echo.
echo The bot will auto-send weekly reports every Monday at 08:00.
echo Edit REPORT_DAY and REPORT_TIME in .env to change this.
echo.
pause
