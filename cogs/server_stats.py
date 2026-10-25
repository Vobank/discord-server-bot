"""Голосовой-счётчик «👥・Участников: N». Discord разрешает переименовывать канал
2 раза в 10 минут, поэтому обновляем раз в 10 минут и только если число изменилось."""
import discord
from discord.ext import commands, tasks

import config


class ServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.updater.start()

    def cog_unload(self):
        self.updater.cancel()

    @tasks.loop(minutes=10)
    async def updater(self):
        for guild in self.bot.guilds:
            counter = next((v for v in guild.voice_channels if v.name.startswith(config.STATS_PREFIX)), None)
            if not counter:
                continue
            name = f"{config.STATS_PREFIX}{len([m for m in guild.members if not m.bot])}"
            if counter.name != name:
                try:
                    await counter.edit(name=name, reason="Счётчик участников")
                except discord.HTTPException:
                    pass

    @updater.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStats(bot))
