import hashlib
import json
import logging
import os
import time
import traceback

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import db

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
# Служебные скрипты из tools/ ставят BOT_HELPER=1: такой бот не реагирует на события сервера
# и не запускает таймеры — иначе, пока скрипт работает, всё дублировалось бы с основным ботом.
HELPER = os.getenv("BOT_HELPER") == "1"
GUILD_ID = int(os.getenv("GUILD_ID") or 0)

# Модуль → выключатель в настройках (modules). Без выключателя — основа бота, грузится всегда.
COGS = {
    "cogs.setup_server": None,
    "cogs.onboarding": None,
    "cogs.admin_panel": None,
    "cogs.mini_panel": None,
    "cogs.mod_panel": None,
    "cogs.rules": None,
    "cogs.status": None,
    "cogs.voice_rooms": "voice_rooms",
    "cogs.music": "music",
    "cogs.news": "news_forward",
    "cogs.birthdays": "birthdays",
    "cogs.levels": "levels",
    "cogs.achievements": "levels",
    "cogs.ratings": "levels",
    "cogs.server_stats": "server_stats",
    "cogs.welcome_card": "welcome_card",
    "cogs.cinema": "cinema",
    "cogs.films": "cinema",
    "cogs.applications": "applications",
    "cogs.adult_channels": "adult_channels",
    "cogs.family": "family",
    "cogs.protection": "protection",
    "cogs.community": "community",
    "cogs.photo_only": "photo_only",
    "cogs.cleanup": "hide_thread_notices",
    "cogs.ghosts": None,
    "cogs.updates": None,
    "cogs.streams": None,
    "cogs.bot_panel": None,
}

log = logging.getLogger("bot")


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    def dispatch(self, event_name: str, /, *args, **kwargs):
        if HELPER and event_name not in ("ready", "connect", "disconnect", "resumed", "shard_ready"):
            return
        super().dispatch(event_name, *args, **kwargs)

    async def setup_hook(self):
        await db.init()
        self.failed_cogs: dict[str, BaseException] = {}
        import config
        for cog, module in COGS.items():
            if module and not config.enabled(module):
                log.info("Модуль %s выключен в настройках", cog)
                continue
            try:
                await self.load_extension(cog)
            except Exception as e:  # один сломанный модуль не должен валить весь бот
                self.failed_cogs[cog] = e
                log.exception("Модуль %s не загрузился — бот работает без него", cog)
        if HELPER:  # таймеры (кино, ДР, рейтинги…) работают только в основном боте
            for cog in self.cogs.values():
                for name in dir(type(cog)):
                    if isinstance(getattr(type(cog), name, None), tasks.Loop):
                        getattr(cog, name).cancel()

        # На своём сервере команды появляются сразу, глобально — до часа.
        # Синхронизируем только если команды изменились — иначе запуск дольше (Discord ограничивает частоту).
        guild = discord.Object(id=GUILD_ID) if GUILD_ID else None
        if guild:
            self.tree.copy_global_to(guild=guild)
        payload = json.dumps([c.to_dict(self.tree) for c in self.tree.get_commands(guild=guild)],
                             sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if await db.get_setting(GUILD_ID, "commands_hash") != digest:
            synced = await self.tree.sync(guild=guild)
            await db.set_setting(GUILD_ID, "commands_hash", digest)
            log.info("Слэш-команд синхронизировано: %d", len(synced))
        else:
            log.info("Слэш-команды не менялись — синхронизация не нужна")

        self.tree.on_error = self.on_app_command_error
        discord.ui.View.on_error = view_error  # ошибки в кнопках/меню — тоже в #📋・логи
        if not HELPER:
            self.alive.start()

    @tasks.loop(seconds=30)
    async def alive(self):
        """Метка «я живой» для диспетчера: если бот завис и не обновляет её — диспетчер его перезапустит."""
        if self.is_ready() and not self.is_closed() and self.latency < 10:
            os.makedirs("runtime", exist_ok=True)
            with open(os.path.join("runtime", "bot_alive.txt"), "w") as f:
                f.write(str(time.time()))
            # бот в голосовом (играет музыка) — диспетчер не будет переносить его на другой ПК
            with open(os.path.join("runtime", "bot_busy.txt"), "w") as f:
                f.write("1" if any(vc.is_connected() for vc in self.voice_clients) else "0")

    async def report_error(self, where: str, error: BaseException):
        """Короткий отчёт об ошибке в #📋・логи (одна и та же ошибка — не чаще раза в 10 минут)."""
        key = f"{where}:{type(error).__name__}:{error}"[:200]
        now = time.time()
        if now - ERRORS_SENT.get(key, 0) < 600 or HELPER:
            return
        ERRORS_SENT[key] = now
        import config
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-1500:]
        for g in self.guilds:
            ch = discord.utils.get(g.text_channels, name=config.CH_ADMIN_LOG)
            if ch:
                try:
                    await ch.send(embed=discord.Embed(title=f"⚠️ Ошибка бота: {where}", colour=discord.Colour.red(),
                                                      description=f"```py\n{tb}\n```"))
                except discord.HTTPException:
                    pass

    async def on_error(self, event_method: str, /, *args, **kwargs):
        import sys
        error = sys.exc_info()[1]
        log.exception("Ошибка в событии %s", event_method)
        if error:
            await self.report_error(f"событие {event_method}", error)

    async def on_ready(self):
        log.info("Бот %s запущен, серверов: %d", self.user, len(self.guilds))
        for cog, error in getattr(self, "failed_cogs", {}).items():
            await self.report_error(f"модуль {cog} не загрузился (бот работает без него)", error)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            text = "⛔ У тебя нет прав на эту команду."
        else:
            log.exception("Ошибка в команде", exc_info=error)
            text = f"⚠️ Ошибка: `{getattr(error, 'original', error)}`"
            name = interaction.command.qualified_name if interaction.command else "?"
            await self.report_error(f"команда /{name}", getattr(error, "original", error))
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)


ERRORS_SENT: dict[str, float] = {}


async def view_error(self, interaction: discord.Interaction, error: Exception, item):
    log.exception("Ошибка в кнопке/меню", exc_info=error)
    # устаревшее нажатие (бот перезапускался) или человек уже вышел с сервера — не ошибка бота
    if isinstance(error, discord.NotFound) and error.code in (10062, 10007, 10008):
        return
    try:
        text = "⚠️ Что-то пошло не так — администрация уже получила отчёт об ошибке."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass
    if isinstance(interaction.client, Bot):
        label = getattr(item, "label", None) or getattr(item, "custom_id", None) or type(item).__name__
        await interaction.client.report_error(f"кнопка «{label}»", error)


def main():
    if not TOKEN:
        raise SystemExit("Нет DISCORD_TOKEN в файле .env")
    discord.utils.setup_logging()
    Bot().run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
