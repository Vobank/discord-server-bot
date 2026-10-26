@echo off
chcp 65001 >nul
rem Открывает панель управления ботом.
rem Работает из папки установленного бота и из скачанной папки (тогда ищет установленную копию).
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\pythonw.exe" if exist "%HERE%manager.pyw" (
    start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%manager.pyw"
    goto :eof
)
set "INSTALLED=%USERPROFILE%\DiscordBot"
if exist "%INSTALLED%\.venv\Scripts\pythonw.exe" if exist "%INSTALLED%\manager.pyw" (
    start "" "%INSTALLED%\.venv\Scripts\pythonw.exe" "%INSTALLED%\manager.pyw"
    goto :eof
)
echo.
echo   Бот ещё не установлен.
echo   Сначала запустите УСТАНОВИТЬ.bat из этой папки, затем снова Запуск.bat.
echo.
pause
