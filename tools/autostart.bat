@echo off
rem Autostart: supervisor decides if this PC runs the bot or waits in reserve. Logs: runtime\supervisor.log
cd /d %~dp0..
:loop
".venv\Scripts\python.exe" -X utf8 -W ignore supervisor.py >> runtime\supervisor_console.log 2>&1
if %errorlevel%==3 goto :eof
timeout /t 10 /nobreak >nul
goto loop
