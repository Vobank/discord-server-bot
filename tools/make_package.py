"""Собрать архив-установщик для другого ПК или хостинга: код + настройки + ключ + установщик. Запускает Мастер.
  make_package.py --name "ПК друга" --priority 2 [--mode auto|manual] [--kind pc|server] [--out папка]
priority: 1 — главный, 2…5 — запасные по очереди. mode manual — этот ПК берёт бота только по кнопке.
kind server — архив для хостинга/VPS/Docker (Linux), инструкция внутри. Архив — на рабочий стол."""
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

SKIP_DIRS = {".venv", "runtime", "__pycache__", ".git", "legacy", ".github", "docs", "node_modules", ".wrangler"}
SKIP_FILES = {"bot.db", "bot.log", "host.json", "bot.db-journal", "version.txt"}
README_PC = """{bot} — установка на этот компьютер

1. Распакуйте архив: правой кнопкой мыши → «Извлечь всё».
2. В распакованной папке дважды щёлкните «УСТАНОВИТЬ.bat».
   Если Windows покажет «Система Windows защитила ваш компьютер», нажмите «Подробнее» → «Выполнить в любом случае».
3. Подождите 5–10 минут. В конце окно установки сообщит, что всё готово.

Дальше ничего делать не нужно:
  • бот запускается вместе с компьютером;
  • обновления скачиваются и устанавливаются сами;
  • бот всегда работает только на одном компьютере: если тот выключится, бот продолжит на другом.
{mode_note}
Ярлык «{bot}» на рабочем столе открывает панель управления. В разделе «Компьютеры» видно,
где сейчас работает бот, а кнопка «Забрать бота сюда» переносит его на этот компьютер.

В архиве лежит ключ бота. Не пересылайте и не публикуйте этот архив.
"""
README_SERVER = """{bot} — запуск на хостинге или сервере (Linux)

Имя в списке компьютеров: «{name}», номер в очереди: {priority}.
{sync_note}
Выберите подходящий вариант.

А. VPS или выделенный сервер (Ubuntu или Debian, доступ по SSH)
  1. Загрузите архив на сервер и распакуйте:   unzip "{zip}" -d ~ && cd ~/DiscordBot
  2. Запустите установку:                     bash install/install.sh
     Скрипт установит Python, FFmpeg, Deno и библиотеки и включит автозапуск (служба discord-bot).
  Полезные команды:
     sudo systemctl status discord-bot    состояние
     sudo journalctl -u discord-bot -f    журнал
     sudo systemctl restart discord-bot   перезапуск

Б. Docker (любая система с Docker)
  1. Распакуйте архив и перейдите в папку DiscordBot.
  2. Выполните: docker compose up -d --build
  Бот работает в контейнере и сам запускается после перезагрузки. Журнал: docker compose logs -f

В. Хостинг с панелью для ботов (Pterodactyl и похожие, сервер типа «Python»)
  1. Загрузите содержимое папки DiscordBot в файлы сервера, включая скрытый файл .env.
  2. В настройках запуска укажите файл запуска supervisor.py и файл зависимостей requirements.txt
     (если нужна команда: pip install -r requirements.txt && python supervisor.py).
  3. Запустите сервер в панели.
  Для музыки на хостинге нужен FFmpeg. Если /play не играет, уточните у поддержки хостинга.

Обновления хостинг устанавливает сам: их публикуют с любого компьютера в панели управления
(«Обслуживание» → «Опубликовать обновление»).
В архиве лежит ключ бота (файл .env). Не публикуйте его.
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
    ap.add_argument("--priority", type=int, default=2)
    ap.add_argument("--mode", default="auto", choices=("auto", "manual"))
    ap.add_argument("--kind", default="pc", choices=("pc", "server"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    synced = bool(sync.SYNC_CHANNEL_ID)
    if not synced and args.kind == "pc":
        raise SystemExit("Сначала включи синхронизацию ПК (Мастер настройки → «Несколько ПК»)")
    friend = {"name": args.name, "priority": max(1, args.priority), "mode": args.mode, "kind": args.kind,
              "id": re.sub(r"\W+", "-", args.name.lower()).strip("-") or "second-pc"}
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
    bad = r'[\\/:*?"<>|]'
    safe, who = re.sub(bad, "", config.BOT_NAME).strip() or "Bot", re.sub(bad, "", args.name).strip()
    zip_name = f"{safe} — для хостинга ({who}).zip" if args.kind == "server" else f"{safe} — установщик для {who}.zip"
    if args.kind == "server":
        note = ("Синхронизация включена: хостинг — один из компьютеров с ботом, они подменяют друг друга.\n"
                if synced else
                "Синхронизация не включена: бот будет работать только здесь. На компьютере его нужно остановить.\n")
        text = README_SERVER.format(bot=config.BOT_NAME, name=args.name, priority=friend["priority"],
                                    sync_note=note, zip=zip_name)
        with open(os.path.join(root, "ПРОЧТИ-ХОСТИНГ.txt"), "w", encoding="utf-8") as f:
            f.write(text)
    else:
        mode_note = ("  • этот компьютер в режиме «только по кнопке»: бот переходит сюда, только когда\n"
                     "    в панели управления нажата кнопка «Забрать бота сюда».\n" if args.mode == "manual" else "")
        with open(os.path.join(root, "ПРОЧТИ.txt"), "w", encoding="utf-8-sig") as f:
            f.write(README_PC.format(bot=config.BOT_NAME, mode_note=mode_note))
    out_dir = args.out or desktop()
    out = os.path.join(out_dir, zip_name)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, files in os.walk(root):
            for name in files:
                full = os.path.join(dirpath, name)
                z.write(full, os.path.relpath(full, stage))
    shutil.rmtree(stage, ignore_errors=True)
    print(f"Архив сохранён: {out}\nРазмер {os.path.getsize(out) // 1024} КБ, версия кода {sync.local_version()}.")
    if args.kind == "server":
        print("\nЗагрузите его на хостинг и следуйте инструкции ПРОЧТИ-ХОСТИНГ.txt внутри архива.")
        if not synced:
            print("Синхронизация не включена: после запуска на хостинге остановите бота на этом компьютере.")
    else:
        print("\nПередайте архив лично: в нём ключ бота. На том компьютере: распаковать и запустить УСТАНОВИТЬ.bat.")


if __name__ == "__main__":
    main()
