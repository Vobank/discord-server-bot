"""📸 Каналы «скриншоты»: сообщения без картинки/видео бот удаляет через пару минут.
Комментировать скриншоты можно в ветках — их бот не трогает. Ссылки на картинки (превью) считаются фото."""
import asyncio
import time

import discord
from discord.ext import commands

import config

MEDIA = ("image/", "video/")


def is_photo_channel(channel) -> bool:
    return isinstance(channel, discord.TextChannel) and any(k in channel.name for k in config.PHOTO_ONLY_KEYWORDS)


def has_media(msg: discord.Message) -> bool:
    if any((a.content_type or "").startswith(MEDIA) for a in msg.attachments):
        return True
    return any(e.type in ("image", "gifv", "video") or e.image or e.thumbnail for e in msg.embeds) or bool(msg.stickers)


class PhotoOnly(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.hinted: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):  # служебные — не наше
            return
        if message.author.bot or not is_photo_channel(message.channel) or has_media(message):
            return
        key = (message.channel.id, message.author.id)
        if time.time() - self.hinted.get(key, 0) > 600:  # подсказка — не чаще раза в 10 минут
            self.hinted[key] = time.time()
            minutes = max(1, config.PHOTO_ONLY_DELAY // 60)
            await message.reply(f"📸 Здесь только скриншоты — это сообщение удалится через {minutes} мин.\n"
                                "Обсудить скриншот можно в ветке: наведи на сообщение → «Создать ветку».",
                                delete_after=config.PHOTO_ONLY_DELAY, mention_author=False)
        await asyncio.sleep(config.PHOTO_ONLY_DELAY)
        try:
            fresh = await message.channel.fetch_message(message.id)  # превью ссылки появляется не сразу
            if not has_media(fresh):
                await fresh.delete()
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PhotoOnly(bot))
