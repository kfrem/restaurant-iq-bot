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
    echo ERROR: Python not found. Install from python.org
    pause
    exit /b 1
)

REM Check Ollama
ollama --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: Ollama not found on PATH. Make sure it is running before starting the bot.
) else (
    echo Ollama found.
)

REM Create .env if it does not exist
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
echo Setup complete. To start the bot, run:
echo   python bot.py
echo.
echo Make sure Ollama is running first (open Ollama from your taskbar or run: ollama serve)
echo.
pause
