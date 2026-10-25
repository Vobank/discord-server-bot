@echo off
rem Bot now runs through the supervisor (autostart). This opens the control panel.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0control_panel.pyw"
