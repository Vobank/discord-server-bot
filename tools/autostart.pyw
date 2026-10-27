"""Автозапуск без окна: держит диспетчер (supervisor.py) запущенным, как autostart.bat, но без VBScript —
в новых Windows его может не быть. Запускается через pythonw.exe из ярлыка в автозагрузке и из панели.
Код выхода 3 — «остановлен вручную», тогда не перезапускаем. Журнал: runtime\\supervisor_console.log"""
import os
import subprocess
import sys
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(APP, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
EXIT_STOP = 3

os.makedirs(os.path.join(APP, "runtime"), exist_ok=True)
while True:
    try:
        log = open(os.path.join(APP, "runtime", "supervisor_console.log"), "ab")
    except OSError:  # журнал занят старым autostart.bat — этот диспетчер всё равно сразу выйдет
        log = subprocess.DEVNULL
    code = subprocess.call([PY, "-X", "utf8", "-W", "ignore", "supervisor.py"], cwd=APP, stdout=log,
                           stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if log is not subprocess.DEVNULL:
        log.close()
    if code == EXIT_STOP:
        break
    time.sleep(10)
