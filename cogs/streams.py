"""🔴 Стримы: человек подключил Twitch или YouTube в Discord (Настройки → Подключения) и вышел в эфир —
Discord ставит ему статус «Стримит», и Дворецкий сам публикует пост в форуме #🔴・стримы: название стрима,
игра, ссылка, превью (у Twitch), тег игры. Эфир закончился — пост помечается «завершён» и закрывается.
Нужен Presence Intent (Developer Portal → Bot): без него бот статусов не видит и молчит — bot.py проверяет это
при запуске. В закреплённом посте форума — инструкция для стримеров."""
import logging
import time

import discord
from discord.ext import commands

import config
import db

log = logging.getLogger(__name__)
FORUM = "🔴・стримы"
OTHER = "Другое"
# как игры называются в статусе Twitch/YouTube → наши игры
ALIASES = {"grand theft auto": "GTA 5 RP", "gta": "GTA 5 RP", "minecraft": "Minecraft", "vrchat": "VRchat",
           "scum": "SCUM", "midnight": "Midnight3D"}
GUIDE = (
    "Стримишь на **Twitch** или **YouTube**? Дворецкий сам расскажет об этом здесь, как только ты выйдешь в эфир.\n\n"
    "**Как подключить (один раз):**\n"
    "1. Discord → ⚙️ **Настройки пользователя → Подключения** (Connections).\n"
    "2. Добавь **Twitch** или **YouTube** и войди в свой аккаунт.\n"
    "3. Включи у него **«Показывать в профиле»** (Display on profile).\n\n"
    "Всё! Когда начнёшь стрим, Discord покажет у тебя статус «Стримит», а здесь появится пост со ссылкой, "
    "игрой и превью. Закончишь — пост закроется сам.\n\n"
    "Стримишь без Twitch/YouTube (например, экран в голосовом)? Создай пост сам: «Новая публикация», "
    "в названии — что стримишь, выбери тег игры.")


def game_tag(game: str | None) -> str:
    low = (game or "").lower()
    for g in config.GAMES:
        if g["name"].lower() in low:
            return g["name"]
    return next((name for key, name in ALIASES.items() if key in low), OTHER)


def streaming(member: discord.Member) -> discord.Streaming | None:
    return next((a for a in member.activities if isinstance(a, discord.Streaming) and a.url), None)


def duration(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60} ч {m % 60} мин" if m >= 60 else f"{max(m, 1)} мин"


def post_embed(member: discord.Member, s: discord.Streaming, game: str) -> discord.Embed:
    platform = s.platform or ("Twitch" if "twitch.tv" in s.url else "YouTube" if "youtu" in s.url else "стрим")
    colour = discord.Colour.purple() if platform == "Twitch" else discord.Colour.red()
    e = discord.Embed(title=(s.name or "Стрим")[:256], url=s.url, colour=colour, timestamp=discord.utils.utcnow(),
                      description=f"🔴 {member.mention} в эфире на **{platform}**!")
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    e.add_field(name="Игра", value=s.game or game)
    if s.twitch_name:
        e.set_image(url=f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{s.twitch_name.lower()}-640x360.jpg"
                        f"?t={int(time.time())}")
    return e


class Streams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.enabled = bot.intents.presences
        if not self.enabled:
            log.warning("Стримы: Presence Intent выключен — оповещений не будет (Developer Portal → Bot)")

    async def forum(self, guild: discord.Guild) -> discord.ForumChannel | None:
        return discord.utils.get(guild.forums, name=FORUM)

    async def start(self, member: discord.Member, s: discord.Streaming):
        g = member.guild
        if await db.fetchone("SELECT 1 FROM streams WHERE guild_id=? AND user_id=?", (g.id, member.id)):
            return
        forum = await self.forum(g)
        if not forum:
            return
        game = game_tag(s.game)
        tag = next((t for t in forum.available_tags if t.name == game), None)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Смотреть", emoji="📺", url=s.url))
        post = await forum.create_thread(name=f"🔴 {member.display_name} — {s.game or s.name or 'стрим'}"[:100],
                                         embed=post_embed(member, s, game), view=view,
                                         applied_tags=[tag] if tag else [], reason="Начался стрим")
        await db.execute("INSERT OR REPLACE INTO streams (guild_id, user_id, thread_id, game, started) VALUES (?,?,?,?,?)",
                         (g.id, member.id, post.thread.id, game, int(time.time())))

    async def stop(self, member: discord.Member):
        g = member.guild
        row = await db.fetchone("SELECT thread_id, started FROM streams WHERE guild_id=? AND user_id=?",
                                (g.id, member.id))
        if not row:
            return
        await db.execute("DELETE FROM streams WHERE guild_id=? AND user_id=?", (g.id, member.id))
        thread_id, started = row
        took = duration(time.time() - started)
        try:
            thread = g.get_thread(thread_id) or await self.bot.fetch_channel(thread_id)
            starter = await thread.fetch_message(thread.id)
            embed = starter.embeds[0]
            embed.colour = discord.Colour.dark_grey()
            embed.description = f"⚫ Стрим {member.mention} закончился · длился **{took}**"
            embed.set_image(url=None)
            await starter.edit(embed=embed, view=None)
            await thread.edit(name=("⚫" + thread.name[1:])[:100], archived=True)
        except discord.HTTPException:
            log.exception("Не обновился пост о стриме")

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or config.is_ghost(after):
            return
        was, now = streaming(before), streaming(after)
        try:
            if now and not was:
                await self.start(after, now)
            elif was and not now:
                await self.stop(after)
        except discord.HTTPException:
            log.exception("Стримы: не получилось")

    @commands.Cog.listener()
    async def on_ready(self):
        """Пока бот был выключен: закончившиеся стримы — закрыть, начавшиеся — объявить (без дублей)."""
        if not self.enabled:
            return
        for g in self.bot.guilds:
            try:
                live = {m.id: s for m in g.members if not m.bot and not config.is_ghost(m) and (s := streaming(m))}
                for (uid,) in await db.fetchall("SELECT user_id FROM streams WHERE guild_id=?", (g.id,)):
                    if uid not in live:
                        if m := g.get_member(uid):
                            await self.stop(m)
                        else:
                            await db.execute("DELETE FROM streams WHERE guild_id=? AND user_id=?", (g.id, uid))
                for uid, s in live.items():
                    await self.start(g.get_member(uid), s)
            except discord.HTTPException:
                log.exception("Стримы: проверка при запуске не удалась")


async def setup(bot: commands.Bot):
    await bot.add_cog(Streams(bot))
