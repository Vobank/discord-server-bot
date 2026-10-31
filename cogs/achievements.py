"""Достижения: считаем активность и выдаём роли из config.ACHIEVEMENTS. Прогресс — /achievements."""
import datetime
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import db

NIGHT_COOLDOWN = 10  # сек — чтобы «Полуночника» не нафармили спамом


async def add_stat(guild_id: int, user_id: int, key: str, delta: int = 1) -> int:
    if config.is_ghost(user_id):  # невидимкам статистику не ведём
        return 0
    await db.execute("INSERT INTO stats (guild_id, user_id, key, value) VALUES (?,?,?,?) "
                     "ON CONFLICT(guild_id, user_id, key) DO UPDATE SET value = value + excluded.value",
                     (guild_id, user_id, key, delta))
    return await get_stat(guild_id, user_id, key)


async def set_stat(guild_id: int, user_id: int, key: str, value: int):
    await db.execute("INSERT INTO stats (guild_id, user_id, key, value) VALUES (?,?,?,?) "
                     "ON CONFLICT(guild_id, user_id, key) DO UPDATE SET value = excluded.value",
                     (guild_id, user_id, key, value))


async def get_stat(guild_id: int, user_id: int, key: str) -> int:
    row = await db.fetchone("SELECT value FROM stats WHERE guild_id=? AND user_id=? AND key=?",
                            (guild_id, user_id, key))
    return row[0] if row else 0


async def progress(member: discord.Member) -> dict[str, int]:
    rows = await db.fetchall("SELECT key, value FROM stats WHERE guild_id=? AND user_id=?",
                             (member.guild.id, member.id))
    values = dict(rows)
    values["games"] = sum(1 for g in config.GAMES if any(r.name == g["role"] for r in member.roles))
    joined = member.joined_at or discord.utils.utcnow()
    values["days"] = (discord.utils.utcnow() - joined).days
    return values


async def check(member: discord.Member, only: set[str] | None = None):
    """Выдать заслуженные роли. only — проверять только эти stat (экономим запросы)."""
    if member.bot or not config.enabled("levels") or config.is_ghost(member):
        return
    values = await progress(member)
    # объявления — только в канале достижений (нет канала — молча, без запасного «уровней»)
    channel = discord.utils.get(member.guild.text_channels, name=config.CH_ACHIEVEMENTS)
    for ach in config.ACHIEVEMENTS:
        if only and ach["stat"] not in only:
            continue
        if values.get(ach["stat"], 0) < ach["need"]:
            continue
        role = discord.utils.get(member.guild.roles, name=ach["role"])
        if not role or role in member.roles or role >= member.guild.me.top_role:
            continue
        await member.add_roles(role, reason=f"Достижение: {ach['desc']}")
        if channel and ach["stat"] != "days":  # «Старожил» — молча, иначе на запуске будет спам
            await channel.send(embed=discord.Embed(
                description=f"🏆 {member.mention} получил достижение **{ach['role']}**\n*{ach['desc']}*",
                colour=discord.Colour(ach["colour"])))


async def bump(member: discord.Member, key: str, delta: int = 1):
    """Для других модулей: +delta к счётчику и проверка достижений."""
    await add_stat(member.guild.id, member.id, key, delta)
    await check(member, {key})


def bar(value: int, need: int, width: int = 10) -> str:
    filled = min(width, int(width * value / need)) if need else width
    return "▰" * filled + "▱" * (width - filled)


class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_since: dict[tuple[int, int], float] = {}
        self.night_last: dict[tuple[int, int], float] = {}
        self.daily.start()

    def cog_unload(self):
        self.daily.cancel()

    # --- сообщения: скриншоты, ночь, серия дней ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        m, g = message.author, message.guild
        changed = set()

        if "скриншот" in message.channel.name and any(
                (a.content_type or "").startswith(("image", "video")) for a in message.attachments):
            await add_stat(g.id, m.id, "screens")
            changed.add("screens")

        now = datetime.datetime.now(config.TIMEZONE)
        key = (g.id, m.id)
        if now.hour < 5 and time.monotonic() - self.night_last.get(key, 0) > NIGHT_COOLDOWN:
            self.night_last[key] = time.monotonic()
            await add_stat(g.id, m.id, "night")
            changed.add("night")

        today = now.date().toordinal()
        last = await get_stat(g.id, m.id, "last_day")
        if last != today:
            streak = await get_stat(g.id, m.id, "streak") + 1 if last == today - 1 else 1
            await set_stat(g.id, m.id, "streak", streak)
            await set_stat(g.id, m.id, "last_day", today)
            if streak > await get_stat(g.id, m.id, "best_streak"):
                await set_stat(g.id, m.id, "best_streak", streak)
            changed.add("best_streak")

        if changed:
            await check(m, changed)

    # --- время в голосовых (АФК не считается) ---
    def _counts(self, state: discord.VoiceState) -> bool:
        ch = state.channel
        return bool(ch) and ch != ch.guild.afk_channel

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.bot:
            return
        key = (member.guild.id, member.id)
        was, now = self._counts(before), self._counts(after)
        if now and not was:
            self.voice_since[key] = time.monotonic()
        elif was and not now and key in self.voice_since:
            minutes = int((time.monotonic() - self.voice_since.pop(key)) // 60)
            if minutes:
                await bump(member, "voice_min", minutes)
                y, w, _ = datetime.datetime.now(config.TIMEZONE).isocalendar()  # для «итогов недели»
                await add_stat(member.guild.id, member.id, f"wvoice:{y}-{w:02}", minutes)

    @commands.Cog.listener()
    async def on_ready(self):
        for g in self.bot.guilds:
            for vc in g.voice_channels:
                for m in vc.members:
                    if not m.bot and vc != g.afk_channel:
                        self.voice_since.setdefault((g.id, m.id), time.monotonic())

    # --- выбор игр ---
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            await check(after, {"games"})

    # --- раз в 6 часов: старожилы ---
    @tasks.loop(hours=6)
    async def daily(self):
        for g in self.bot.guilds:
            for m in g.members:
                await check(m, {"days"})

    @daily.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="achievements", description="Достижения и прогресс")
    @app_commands.guild_only()
    async def achievements(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        values = await progress(member)
        # незаконченная сессия в голосовом тоже считается
        if (since := self.voice_since.get((member.guild.id, member.id))) is not None:
            values["voice_min"] = values.get("voice_min", 0) + int((time.monotonic() - since) // 60)
        lines = []
        got = 0
        for ach in config.ACHIEVEMENTS:
            v, need = values.get(ach["stat"], 0), ach["need"]
            if v >= need:
                got += 1
                lines.append(f"✅ **{ach['role']}** — {ach['desc']}")
            else:
                shown = f"{v // 60}/{need // 60} ч" if ach["stat"] == "voice_min" else f"{v}/{need}"
                lines.append(f"🔒 **{ach['role']}** — {ach['desc']}\n　{bar(v, need)} {shown}")
        embed = discord.Embed(title=f"🏆 Достижения: {member.display_name}", description="\n".join(lines),
                              colour=discord.Colour.gold())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Получено {got} из {len(config.ACHIEVEMENTS)} · серия: "
                              f"{values.get('streak', 0)} дн. подряд")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
