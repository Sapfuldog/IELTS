@echo off
rem Start the IELTS bot.
rem
rem ASCII only and no fancy quoting: cmd.exe reads this file in the console
rem codepage, and anything else turns into mojibake or a syntax error.
rem
rem Double-click it, or run it from a terminal. The window stays open on
rem failure so the reason is readable instead of flashing past.

setlocal
cd /d "%~dp0"

rem The bot logs dashes and Russian; without UTF-8 the console prints them as
rem question marks, which makes a real error message look like a broken one.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

set PYTHON=.venv\Scripts\python.exe

if not exist "%PYTHON%" (
    echo.
    echo   No virtual environment found at %PYTHON%
    echo.
    echo   Create it once with:
    echo       python -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo   No .env file. Copy .env.example to .env and add your BOT_TOKEN.
    echo.
    pause
    exit /b 1
)

echo Starting the IELTS bot. Close this window or press Ctrl+C to stop it.
echo.

"%PYTHON%" run.py
set CODE=%ERRORLEVEL%

echo.
if %CODE% neq 0 (
    rem Exit code 1 is usually the single-instance guard: another copy is
    rem already polling, and the message above says which PID holds it.
    echo   The bot stopped with code %CODE%. The reason is printed above.
) else (
    echo   The bot stopped.
)
echo.
pause
endlocal
