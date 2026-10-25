"""Собрать архив-установщик для второго ПК: код + настройки + ключ + установщик. Запускает Мастер настройки.
  make_package.py --name "ПК друга" --priority 2 [--out папка]
priority: 1 — главный (забирает бота себе, когда включён), 2 — запасной. Архив — на рабочий стол."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import config  # noqa: E402
import sync  # noqa: E402

SKIP_DIRS = {".venv", "runtime", "__pycache__", ".git", "legacy", ".github"}
SKIP_FILES = {"bot.db", "bot.log", "host.json", "bot.db-journal", "version.txt"}
README = """{bot} — УСТАНОВКА НА ВТОРОЙ ПК (делать один раз)

1. Распакуй этот архив (правой кнопкой → «Извлечь всё»).
2. Открой распакованную папку и дважды нажми «УСТАНОВИТЬ.bat».
   Если Windows спросит «Защитник Windows предотвратил запуск» — нажми «Подробнее» → «Выполнить в любом случае».
3. Подожди 5–10 минут, пока всё поставится. В конце будет зелёная надпись «ГОТОВО».

Всё! Дальше ничего делать не нужно:
  • бот сам включается вместе с компьютером;
  • обновления бот скачивает и ставит сам;
  • если твой ПК выключен — бот работает на ПК «{other}», и наоборот.

На рабочем столе появится ярлык «{bot}» — там видно, работает ли бот (зелёный кружок — работает у тебя,
жёлтый — работает на другом ПК, это тоже нормально).

⚠ В архиве лежит ключ от бота. Никому его не пересылай и не выкладывай.
"""


def desktop() -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        if out and os.path.isdir(out):
            return out
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Второй ПК")
    ap.add_argument("--priority", type=int, default=2, choices=(1, 2))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if not sync.SYNC_CHANNEL_ID:
        raise SystemExit("Сначала включи синхронизацию двух ПК (Мастер настройки → «Два ПК»)")
    friend = {"name": args.name, "priority": args.priority, "id": re.sub(r"\W+", "-", args.name.lower()).strip("-")
              or "second-pc"}
    stage = tempfile.mkdtemp()
    root = os.path.join(stage, "DiscordBot")
    for dirpath, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, APP)
        for name in files:
            if name in SKIP_FILES or name.endswith((".pyc", ".log")) or (rel == "tools" and name.startswith("backup")):
                continue
            dst = os.path.join(root, rel, name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(dirpath, name), dst)
    with open(os.path.join(root, "host.json"), "w", encoding="utf-8") as f:
        json.dump(friend, f, ensure_ascii=False)
    with open(os.path.join(root, "ПРОЧТИ.txt"), "w", encoding="utf-8-sig") as f:
        f.write(README.format(bot=config.BOT_NAME, other=sync.host_info()["name"]))
    out_dir = args.out or desktop()
    bad = r'[\\/:*?"<>|]'
    safe, who = re.sub(bad, "", config.BOT_NAME).strip() or "Bot", re.sub(bad, "", args.name).strip()
    out = os.path.join(out_dir, f"{safe} — установщик для {who}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, files in os.walk(root):
            for name in files:
                full = os.path.join(dirpath, name)
                z.write(full, os.path.relpath(full, stage))
    shutil.rmtree(stage, ignore_errors=True)
    print(f"✅ Архив: {out}\n   {os.path.getsize(out) // 1024} КБ, версия кода {sync.local_version()}")
    print("\nОтправь его на второй ПК ЛИЧНО (в архиве ключ бота!). Там: распаковать → УСТАНОВИТЬ.bat.")


if __name__ == "__main__":
    main()
