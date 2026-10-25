#!/usr/bin/env bash
# Установка бота на Linux-сервер (Ubuntu / Debian): программы, библиотеки и автозапуск (служба systemd).
# Запуск из папки бота:  bash install/install.sh
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE=discord-bot
cd "$DIR"

echo "==> 1/4 Программы: Python, FFmpeg, Opus, шрифты"
if command -v apt-get >/dev/null; then
  sudo apt-get update -q
  sudo apt-get install -y -q python3 python3-venv python3-pip ffmpeg libopus0 fonts-dejavu-core curl unzip
else
  echo "Нет apt-get — поставь вручную: python3 (3.10+), python3-venv, ffmpeg, libopus, curl, unzip"
fi

echo "==> 2/4 Deno (нужен для YouTube в музыке)"
if ! command -v deno >/dev/null && [ ! -x "$HOME/.deno/bin/deno" ]; then
  curl -fsSL https://deno.land/install.sh | sh -s -- -y || echo "Deno не поставился — музыка с YouTube может не играть"
fi

echo "==> 3/4 Библиотеки бота"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p runtime

if ! grep -qE '^DISCORD_TOKEN=.{50,}' .env 2>/dev/null; then
  echo
  echo "⚠ Нет ключа бота в .env."
  echo "  Проще всего: на Windows-ПК в Мастере настройки → «Несколько ПК» собери архив «Хостинг / сервер»"
  echo "  и залей его сюда (там уже есть .env). Или впиши вручную: cp .env.example .env && nano .env"
  echo "  Потом запусти этот скрипт ещё раз."
  exit 1
fi

if [ ! -f host.json ]; then
  printf '{"name": "%s", "priority": 1, "kind": "server", "id": "%s"}\n' "$(hostname)" "$(hostname)" > host.json
fi

echo "==> 4/4 Автозапуск (служба $SERVICE)"
sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=Discord bot ($DIR)
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -X utf8 supervisor.py
Restart=always
RestartSec=10
RestartPreventExitStatus=3
Environment=PYTHONUNBUFFERED=1
Environment=PATH=$HOME/.deno/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now $SERVICE

echo
echo "✅ Готово! Бот работает и сам запускается после перезагрузки сервера."
echo "   Статус:  sudo systemctl status $SERVICE"
echo "   Лог:     sudo journalctl -u $SERVICE -f     (лог бота — $DIR/bot.log)"
