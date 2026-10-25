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

SKIP_DIRS = {".venv", "runtime", "__pycache__", ".git", "legacy", ".github", "docs"}
SKIP_FILES = {"bot.db", "bot.log", "host.json", "bot.db-journal", "version.txt"}
README_PC = """{bot} — УСТАНОВКА НА ЭТОТ ПК (делать один раз)

1. Распакуй этот архив (правой кнопкой → «Извлечь всё»).
2. Открой распакованную папку и дважды нажми «УСТАНОВИТЬ.bat».
   Если Windows спросит «Защитник Windows предотвратил запуск» — нажми «Подробнее» → «Выполнить в любом случае».
3. Подожди 5–10 минут, пока всё поставится. В конце будет зелёная надпись «ГОТОВО».

Всё! Дальше ничего делать не нужно:
  • бот сам включается вместе с компьютером;
  • обновления бот скачивает и ставит сам;
  • работает всегда только один ПК — если тот, где бот, выключится, бот сам продолжит на другом.
{mode_note}
На рабочем столе появится ярлык «{bot}» — там видно все компьютеры и где сейчас работает бот
(🟢 — у тебя, 🟡 — на другом ПК, это тоже нормально). Кнопка «📌 Забрать бота сюда» — перенести бота к себе.

⚠ В архиве лежит ключ от бота. Никому его не пересылай и не выкладывай.
"""
README_SERVER = """{bot} — ЗАПУСК НА ХОСТИНГЕ / СЕРВЕРЕ (Linux)

Имя в списке компьютеров: «{name}», номер в очереди: {priority}.
{sync_note}
Выбери свой вариант:

━━ А. VPS / выделенный сервер (Ubuntu или Debian, есть доступ по SSH) ━━
  1. Залей архив на сервер и распакуй:   unzip "{zip}" -d ~ && cd ~/DiscordBot
  2. Запусти установку:                    bash install/install.sh
     Скрипт поставит Python, FFmpeg, Deno, библиотеки и включит автозапуск (служба discord-bot).
  Полезное:  sudo systemctl status discord-bot   — работает ли
             sudo journalctl -u discord-bot -f   — лог
             sudo systemctl restart discord-bot  — перезапуск

━━ Б. Docker (любая ОС с Docker) ━━
  1. Распакуй архив и зайди в папку DiscordBot.
  2. docker compose up -d --build
  Бот работает в контейнере и сам поднимается после перезагрузки. Лог: docker compose logs -f

━━ В. Хостинг с панелью для ботов (Pterodactyl и т.п., «Python»-сервер) ━━
  1. Загрузи СОДЕРЖИМОЕ папки DiscordBot в файлы сервера (вместе со скрытым файлом .env).
  2. В настройках запуска: файл запуска — supervisor.py, файл зависимостей — requirements.txt
     (если просят команду: pip install -r requirements.txt && python supervisor.py).
  3. Запусти сервер в панели.
  ⚠ Для музыки на хостинге должен быть FFmpeg — спроси поддержку, если /play не играет.

Обновления хостинг ставит сам (их публикуют с любого ПК кнопкой «📤 Опубликовать обновление»).
⚠ В архиве лежит ключ от бота (.env). Не выкладывай его в открытый доступ.
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
                "⚠ Синхронизация НЕ включена: бот будет работать только здесь. На ПК его нужно остановить!\n")
        text = README_SERVER.format(bot=config.BOT_NAME, name=args.name, priority=friend["priority"],
                                    sync_note=note, zip=zip_name)
        with open(os.path.join(root, "ПРОЧТИ-ХОСТИНГ.txt"), "w", encoding="utf-8") as f:
            f.write(text)
    else:
        mode_note = ("\n  • этот ПК в режиме «только по кнопке»: бот сюда приходит, только когда нажмёшь\n"
                     "    в панели «📌 Забрать бота сюда».\n" if args.mode == "manual" else "")
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
    print(f"✅ Архив: {out}\n   {os.path.getsize(out) // 1024} КБ, версия кода {sync.local_version()}")
    if args.kind == "server":
        print("\nЗалей его на хостинг и сделай, как написано в ПРОЧТИ-ХОСТИНГ.txt внутри архива.")
        if not synced:
            print("⚠ Синхронизация не включена — после запуска на хостинге останови бота на этом ПК!")
    else:
        print("\nОтправь его на тот ПК ЛИЧНО (в архиве ключ бота!). Там: распаковать → УСТАНОВИТЬ.bat.")


if __name__ == "__main__":
    main()
