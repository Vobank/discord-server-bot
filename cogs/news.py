"""Пересылка новостей из канала-источника (например, с другого сервера) в наши каналы.
Источники задаются в .env: NEWS_FORWARDS=ID_канала_источника:название_нашего_канала,...
Бот должен состоять на сервере, где находится канал-источник, и видеть этот канал."""
import logging
import os

import discord
from discord.ext import commands

log = logging.getLogger(__name__)
MAX_FILE = 10 * 1024 * 1024  # лимит загрузки для бота на сервере без бустов


def parse_forwards() -> dict[int, str]:
    result = {}
    for part in (os.getenv("NEWS_FORWARDS") or "").split(","):
        if ":" in part:
            src, name = part.split(":", 1)
            result[int(src.strip())] = name.strip()
    return result


class News(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.forwards = parse_forwards()
        self.guild_id = int(os.getenv("GUILD_ID") or 0)
        log.info("Новости: источников %d", len(self.forwards))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        target_name = self.forwards.get(message.channel.id)
        if not target_name or message.author == self.bot.user:
            return
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return
        # цель — ID канала или его название
        target = guild.get_channel(int(target_name)) if target_name.isdigit() else \
            discord.utils.get(guild.text_channels, name=target_name)
        if not target or target.id == message.channel.id:
            return

        content = message.content
        attachments = list(message.attachments)
        embeds = [e for e in message.embeds if e.type == "rich"]
        # Если в источник «переслали» сообщение — берём его содержимое
        for snap in getattr(message, "message_snapshots", None) or []:
            content = content or snap.content
            attachments += snap.attachments
            embeds += [e for e in snap.embeds if e.type == "rich"]

        files = [await a.to_file() for a in attachments if a.size <= MAX_FILE]
        too_big = [a.url for a in attachments if a.size > MAX_FILE]
        if too_big:
            content = (content + "\n" + "\n".join(too_big)).strip()
        if not content and not files and not embeds:
            return

        try:
            await target.send(content=content[:2000] or None, embeds=embeds[:10], files=files[:10],
                              allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Не удалось переслать новость в #%s", target_name)


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))
