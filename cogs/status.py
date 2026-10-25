"""/status — где сейчас работает бот (какой ПК), все компьютеры с ботом, версия кода, сколько без перерыва."""
import json
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

STARTED = time.time()
STATUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "status.json")


def hosts_text() -> str:
    """Список ПК — из статуса диспетчера на этом же компьютере."""
    try:
        with open(STATUS, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    if st.get("solo"):
        return "Один ПК (синхронизация не включена)"
    lines = []
    for h in st.get("hosts") or []:
        online = time.time() - h.get("ts", 0) < 150
        here = h.get("name") == os.getenv("BOT_HOST")
        icon = "🟢" if here else ("🟡" if online else "⚪")
        kind = "🌐" if h.get("kind") == "server" else "🖥"
        extra = [f"№{h.get('priority')}"]
        if h.get("mode") == "manual":
            extra.append("только по кнопке")
        if st.get("pinned") == h.get("id"):
            extra.append("📌 закреплён")
        if online and h.get("load") is not None:
            extra.append(f"нагрузка {h['load']}%")
        if not online:
            extra.append(f"не в сети с <t:{int(h.get('ts', 0))}:R>")
        lines.append(f"{icon} {kind} **{h.get('name')}** · " + " · ".join(extra))
    return "\n".join(lines)


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="Где сейчас работает бот и сколько без перерыва")
    @app_commands.default_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        s = int(time.time() - STARTED)
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        version = os.getenv("BOT_VERSION", "—")
        e = discord.Embed(title="🖥️ Где работает бот", colour=discord.Colour.green())
        e.add_field(name="Сейчас на", value=os.getenv("BOT_HOST", "этом ПК (без диспетчера)"))
        e.add_field(name="Без перерыва", value=(f"{d} д " if d else "") + f"{h} ч {s // 60} мин")
        e.add_field(name="Версия кода", value=f"<t:{version}:f>" if version.isdigit() else version)
        e.add_field(name="Пинг до Discord", value=f"{round(self.bot.latency * 1000)} мс")
        if hosts := hosts_text():
            e.add_field(name="Компьютеры", value=hosts[:1024], inline=False)
        e.set_footer(text="Если этот ПК выключат — бот сам продолжит работу на другом. "
                          "Перенести к себе — «📌 Забрать бота сюда» в панели на своём ПК")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Status(bot))
