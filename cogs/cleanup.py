"""🧹 Чистота в чатах: служебное «X started a thread / начал(а) ветку» бот сразу удаляет во всех каналах —
ветка при этом остаётся, найти её можно под сообщением и в списке веток канала."""
import discord
from discord.ext import commands


class Cleanup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.type == discord.MessageType.thread_created and message.guild:
            try:
                await message.delete()
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Cleanup(bot))
