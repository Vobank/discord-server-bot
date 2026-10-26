"""Один раз: включить режим двух ПК — создать закрытый канал #🔧・bot-sync (в админке) и сообщение-«пульс»,
записать их ID в .env. Запускает Мастер настройки (вкладка «Два ПК»)."""
import os
import re
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["BOT_HELPER"] = "1"
os.chdir(APP)
sys.path.insert(0, APP)
import discord  # noqa: E402

import bot as botmod  # noqa: E402
import config  # noqa: E402

ENV = os.path.join(APP, ".env")
SYNC_CHANNEL = "🔧・bot-sync"


def set_env(key: str, value: str):
    text = open(ENV, encoding="utf-8").read()
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    elif key == "SYNC_CHANNEL_ID":
        text = text.rstrip("\n") + f"\n\n# Синхронизация между ПК (не трогать)\n{key}={value}\n"
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    open(ENV, "w", encoding="utf-8").write(text)


class SyncSetup(botmod.Bot):
    async def on_ready(self):
        code = 0
        try:
            if os.getenv("SYNC_HEARTBEAT_ID"):  # новый пульс отрезал бы второй ПК со старым
                print("Синхронизация уже включена, ничего менять не нужно.")
                sys.stdout.flush()
                os._exit(0)
            g = self.get_guild(botmod.GUILD_ID)
            if g is None:
                raise RuntimeError("бот не видит сервер с GUILD_ID из .env")
            admin = discord.utils.get(g.categories, name=config.CAT_ADMIN)
            ch = discord.utils.get(g.text_channels, name=SYNC_CHANNEL)
            if ch is None:
                ch = await g.create_text_channel(
                    SYNC_CHANNEL, category=admin, reason="Синхронизация бота между ПК",
                    topic="Служебный канал бота: пульс, снимки базы, обновления. Ничего не писать и не удалять!",
                    overwrites={g.default_role: discord.PermissionOverwrite(view_channel=False),
                                g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                                  attach_files=True, read_message_history=True)})
            hb = await ch.send("HEARTBEAT\n{}")
            await hb.pin()
            set_env("SYNC_CHANNEL_ID", str(ch.id))
            set_env("SYNC_HEARTBEAT_ID", str(hb.id))
            print(f"Служебный канал #{ch.name} готов, его данные записаны в .env.")
            print("Перезапустите бота, затем соберите установщик для другого компьютера.")
        except Exception:
            import traceback
            traceback.print_exc()
            code = 1
        sys.stdout.flush()
        os._exit(code)


discord.utils.setup_logging(level=40)
SyncSetup().run(botmod.TOKEN, log_handler=None)
