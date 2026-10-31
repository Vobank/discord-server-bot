"""🔴 Стримы: кто-то включил трансляцию экрана (Go Live) в голосовом — Дворецкий создаёт пост в форуме
#🔴・стримы со ссылкой на комнату. У поста тег игры: игра берётся из категории голосового канала
(комната в «🧡・GTA 5 RP» → тег «GTA 5 RP»), иначе «Общее». Тегов столько, сколько игр сейчас стримят:
новая игра — новый тег, стримов по игре больше нет — тег убирается.
Стрим закончился — пост помечается «завершён» (с длительностью) и закрывается."""
import logging
import time

import discord
from discord.ext import commands

import config
import db

log = logging.getLogger(__name__)
FORUM = "🔴・стримы"
OTHER = ("Общее", "🎙️")
MAX_TAGS = 20  # ограничение Discord на теги форума


def game_of(channel: discord.VoiceChannel) -> tuple[str, str]:
    """(игра, эмодзи) по категории голосового канала."""
    cat = channel.category.name if channel.category else ""
    for g in config.GAMES:
        if g["name"].lower() in cat.lower():
            return g["name"], g["emoji"]
    for g in config.GAMES:  # «GTA REST Секта» и т. п. — по значку категории
        if g["emoji"] in cat:
            return g["name"], g["emoji"]
    return OTHER


def duration(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60} ч {m % 60} мин" if m >= 60 else f"{max(m, 1)} мин"


async def forum(guild: discord.Guild) -> discord.ForumChannel | None:
    """Форум #🔴・стримы (в категории активности): посты создаёт только бот, обсуждать в них могут все."""
    cid = await db.get_setting(guild.id, "streams_forum")
    channel = guild.get_channel(int(cid)) if cid else None
    channel = channel or discord.utils.get(guild.forums, name=FORUM)
    if channel is None:
        category = discord.utils.find(lambda c: config.CAT_ACTIVITY in c.name, guild.categories)
        over = {guild.default_role: discord.PermissionOverwrite(send_messages=False, send_messages_in_threads=True),
                guild.me: discord.PermissionOverwrite(send_messages=True, manage_threads=True)}
        channel = await guild.create_forum(FORUM, category=category, overwrites=over, reason="Посты о стримах",
                                           topic="Кто сейчас стримит — Дворецкий пишет сам. Заходи посмотреть!")
    if str(channel.id) != cid:
        await db.set_setting(guild.id, "streams_forum", str(channel.id))
    return channel


async def sync_tags(channel: discord.ForumChannel, game: tuple | None = None):
    """Теги = игры, которые сейчас стримят. game — добавить тег этой игры (если нет). Возвращает тег игры."""
    live = {row[0] for row in await db.fetchall("SELECT game FROM streams WHERE guild_id=?", (channel.guild.id,))}
    if game:
        live.add(game[0])
    keep = [t for t in channel.available_tags if t.name in live]
    if game and not any(t.name == game[0][:20] for t in keep):
        keep.append(discord.ForumTag(name=game[0][:20], emoji=game[1]))
    keep = keep[:MAX_TAGS]
    if {t.name for t in keep} != {t.name for t in channel.available_tags}:
        try:
            channel = await channel.edit(available_tags=keep, reason="Теги игр, которые сейчас стримят")
        except discord.HTTPException:  # составные эмодзи (❤️‍🩹) Discord в тегах не всегда принимает — без значка
            keep = [t if t.id else discord.ForumTag(name=t.name) for t in keep]
            channel = await channel.edit(available_tags=keep, reason="Теги игр, которые сейчас стримят")
    return next((t for t in channel.available_tags if game and t.name == game[0][:20]), None)


class Streams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def start(self, member: discord.Member, voice: discord.VoiceChannel):
        g = member.guild
        if await db.fetchone("SELECT 1 FROM streams WHERE guild_id=? AND user_id=?", (g.id, member.id)):
            return
        channel = await forum(g)
        game = game_of(voice)
        tag = await sync_tags(channel, game=game)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Смотреть", emoji="📺", url=voice.jump_url))
        embed = discord.Embed(description=f"{member.mention} начал стрим в {voice.mention}\n"
                                          f"Игра: {game[1]} **{game[0]}**\n\nЗаходи в комнату и нажми на его экран 👀",
                              colour=discord.Colour.red(), timestamp=discord.utils.utcnow())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        post = await channel.create_thread(name=f"🔴 {member.display_name} — {game[0]}"[:100], embed=embed, view=view,
                                           applied_tags=[tag] if tag else [], reason="Начался стрим")
        await db.execute("INSERT OR REPLACE INTO streams (guild_id, user_id, thread_id, game, started) VALUES (?,?,?,?,?)",
                         (g.id, member.id, post.thread.id, game[0], int(time.time())))

    async def stop(self, member: discord.Member):
        g = member.guild
        row = await db.fetchone("SELECT thread_id, game, started FROM streams WHERE guild_id=? AND user_id=?",
                                (g.id, member.id))
        if not row:
            return
        thread_id, game, started = row
        await db.execute("DELETE FROM streams WHERE guild_id=? AND user_id=?", (g.id, member.id))
        thread = g.get_thread(thread_id) or await self.bot.fetch_channel(thread_id)
        took = duration(time.time() - started)
        try:
            starter = await thread.fetch_message(thread.id)
            embed = starter.embeds[0]
            embed.colour = discord.Colour.dark_grey()
            embed.description = embed.description.split("\n\n")[0].replace("начал стрим", "стримил") + \
                f"\n⏱️ Стрим длился **{took}**"
            await starter.edit(embed=embed, view=None)
            await thread.edit(name=f"⚫ {member.display_name} — {game} · {took}"[:100], archived=True, locked=True)
        except discord.HTTPException:
            log.exception("Не обновился пост о стриме")
        if isinstance(thread.parent, discord.ForumChannel):
            await sync_tags(thread.parent)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.bot or config.is_ghost(member):
            return
        was = bool(before.self_stream and before.channel)
        now = bool(after.self_stream and after.channel)
        try:
            if now and not was:
                await self.start(member, after.channel)
            elif was and not now:
                await self.stop(member)
            elif now and before.channel != after.channel:  # перешёл в другую комнату со стримом
                await self.stop(member)
                await self.start(member, after.channel)
        except discord.HTTPException:
            log.exception("Стримы: не получилось")

    @commands.Cog.listener()
    async def on_ready(self):
        """Пока бот был выключен: закончившиеся стримы — закрыть, начавшиеся — объявить."""
        for g in self.bot.guilds:
            try:
                await forum(g)
                live = {m.id: m for vc in g.voice_channels for m in vc.members
                        if m.voice and m.voice.self_stream and not m.bot and not config.is_ghost(m)}
                for (uid,) in await db.fetchall("SELECT user_id FROM streams WHERE guild_id=?", (g.id,)):
                    if uid not in live and (m := g.get_member(uid)):
                        await self.stop(m)
                    elif uid not in live:
                        await db.execute("DELETE FROM streams WHERE guild_id=? AND user_id=?", (g.id, uid))
                for m in live.values():
                    await self.start(m, m.voice.channel)
            except discord.HTTPException:
                log.exception("Стримы: проверка при запуске не удалась")


async def setup(bot: commands.Bot):
    await bot.add_cog(Streams(bot))
