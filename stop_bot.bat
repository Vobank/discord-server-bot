@echo off
rem Stop bot on this PC (the other PC takes over automatically)
echo stop> "%~dp0runtime\command.txt"
timeout /t 20 /nobreak >nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*autostart.bat*' -or $_.CommandLine -like '*supervisor.py*' -or ($_.CommandLine -like '*bot.py*' -and $_.CommandLine -like '*-X utf8*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Bot stopped on this PC.
pause
