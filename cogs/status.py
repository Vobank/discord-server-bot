"""/status — где сейчас работает бот (какой ПК), версия кода, сколько работает без перерыва."""
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

STARTED = time.time()


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
        e = discord.Embed(title="🖥️ Сервер бота", colour=discord.Colour.green())
        e.add_field(name="Работает на", value=os.getenv("BOT_HOST", "этом ПК (без диспетчера)"))
        e.add_field(name="Без перерыва", value=(f"{d} д " if d else "") + f"{h} ч {s // 60} мин")
        e.add_field(name="Версия кода", value=f"<t:{version}:f>" if version.isdigit() else version)
        e.add_field(name="Пинг до Discord", value=f"{round(self.bot.latency * 1000)} мс")
        e.set_footer(text="Если этот ПК выключат — бот сам продолжит работу на втором ПК")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Status(bot))
