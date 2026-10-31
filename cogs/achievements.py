"""Достижения: считаем активность и выдаём роли из config.ACHIEVEMENTS. Прогресс — /achievements.
У каждого достижения свой значок (assets/badges, cogs/badge_art.py): он в объявлении о достижении и в сетке
/achievements (не полученные — серые). Админ меняет значок командой /badge: свой файл или новый от ИИ."""
import asyncio
import datetime
import io
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import ai
import config
import db
from cogs import badge_art

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
            embed = discord.Embed(description=f"🏆 {member.mention} получил достижение **{ach['role']}**\n*{ach['desc']}*",
                                  colour=discord.Colour(ach["colour"]))
            data = await badge(member.guild.id, ach)
            if data:
                embed.set_thumbnail(url="attachment://badge.png")
            await channel.send(embed=embed, files=[badge_file(data)] if data else [])


async def bump(member: discord.Member, key: str, delta: int = 1):
    """Для других модулей: +delta к счётчику и проверка достижений."""
    await add_stat(member.guild.id, member.id, key, delta)
    await check(member, {key})


# ---------- значки ----------
BADGE_STYLE = ("game achievement badge icon, ornate golden shield emblem with spread golden wings, small pink gem "
               "at the bottom, glossy 3D render, centered, symmetrical, isolated on plain flat dark purple background, "
               "soft glow, no text, no letters")


def badge_key(ach: dict) -> str:
    return f"{ach['stat']}_{ach['need']}"


def plain_name(name: str) -> str:
    """Название роли без эмодзи в начале — для подписи на картинке."""
    return re.sub(r"^\W+", "", name).strip() or name


async def badge(guild_id: int, ach: dict) -> bytes | None:
    """Значок: заменённый админом (в базе) или стандартный из assets/badges."""
    row = await db.fetchone("SELECT data FROM badges WHERE guild_id=? AND key=?", (guild_id, badge_key(ach)))
    return row[0] if row else badge_art.default_file(badge_key(ach))


async def draw_badge(ach: dict, idea: str = "") -> bytes | None:
    """Новый значок от ИИ: Gemini придумывает символ, Workers AI рисует, фон вырезаем."""
    symbol = await ai.ask(
        f"Значок достижения на Discord-сервере: «{plain_name(ach['role'])}» — {ach['desc']}."
        + (f" Пожелание: {idea[:200]}." if idea else "")
        + " Опиши одной короткой фразой на английском, что нарисовать в центре щита и какого цвета эмаль щита, "
          "например: golden headphones in the center, teal enamel shield. Только эту фразу.")
    data = await ai.image(f"{BADGE_STYLE}, {symbol.strip().strip('.')[:200]}")
    return await asyncio.to_thread(badge_art.cut_out, data) if ai.is_image(data) else None


def badge_file(data: bytes, name: str = "badge.png") -> discord.File:
    return discord.File(io.BytesIO(data), filename=name)


class BadgeView(discord.ui.View):
    """Предпросмотр нового значка: поставить, нарисовать ещё (ИИ) или вернуть стандартный."""

    def __init__(self, ach: dict, data: bytes, idea: str | None):
        super().__init__(timeout=600)
        self.ach, self.data, self.idea = ach, data, idea
        if idea is None:  # свой файл — «ещё вариант» не нужен
            self.remove_item(self.again)

    async def finish(self, interaction: discord.Interaction, text: str):
        await interaction.edit_original_response(content=text, attachments=[], view=None)
        await asyncio.sleep(20)
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Поставить", emoji="✅", style=discord.ButtonStyle.success)
    async def apply(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await db.execute("INSERT OR REPLACE INTO badges (guild_id, key, data) VALUES (?,?,?)",
                         (interaction.guild.id, badge_key(self.ach), self.data))
        await self.finish(interaction, f"✅ Значок **{self.ach['role']}** поставлен")

    @discord.ui.button(label="Нарисовать ещё", emoji="🎲", style=discord.ButtonStyle.primary)
    async def again(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="🎨 Рисую ещё вариант — секунд 10–20…", view=None)
        try:
            data = await draw_badge(self.ach, self.idea or "")
        except ai.AIError as e:
            data, problem = None, str(e)
        else:
            problem = "ИИ прислал не картинку"
        if data:
            self.data = data
        await interaction.edit_original_response(
            content=f"Новый значок для **{self.ach['role']}** — поставить?" if data else f"⚠️ {problem}",
            attachments=[badge_file(self.data)], view=self)

    @discord.ui.button(label="Вернуть стандартный", emoji="↩️")
    async def reset(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await db.execute("DELETE FROM badges WHERE guild_id=? AND key=?", (interaction.guild.id, badge_key(self.ach)))
        await self.finish(interaction, f"↩️ У **{self.ach['role']}** снова стандартный значок")


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
        await interaction.response.defer()
        items = [(await badge(member.guild.id, ach), plain_name(ach["role"]), values.get(ach["stat"], 0) >= ach["need"])
                 for ach in config.ACHIEVEMENTS]
        files = []
        if any(data for data, *_ in items):
            files = [badge_file(await asyncio.to_thread(badge_art.grid, items), "badges.png")]
            embed.set_image(url="attachment://badges.png")
        await interaction.followup.send(embed=embed, files=files)

    @app_commands.command(name="badge", description="(Админ) Поменять значок достижения: свой файл или новый от ИИ")
    @app_commands.describe(achievement="Какое достижение", picture="Своя картинка (не выбрал — нарисует ИИ)",
                           idea="Что нарисовать на значке — для ИИ (можно не писать)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def badge_cmd(self, interaction: discord.Interaction, achievement: str,
                        picture: discord.Attachment | None = None, idea: str | None = None):
        ach = next((a for a in config.ACHIEVEMENTS if badge_key(a) == achievement), None)
        if not ach:
            return await interaction.response.send_message("Нет такого достижения — выбери из списка",
                                                           ephemeral=True, delete_after=15)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if picture:
                raw = await picture.read()
                data = await asyncio.to_thread(badge_art.cut_out, raw) if ai.is_image(raw) else None
            else:
                data = await draw_badge(ach, idea or "")
        except ai.AIError as e:
            return await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
        if not data:
            return await interaction.followup.send("⚠️ Не получилось открыть картинку — попробуй другую", ephemeral=True)
        view = BadgeView(ach, data, None if picture else (idea or ""))
        await interaction.followup.send(f"Новый значок для **{ach['role']}** — поставить?", file=badge_file(data),
                                        view=view, ephemeral=True)

    @badge_cmd.autocomplete("achievement")
    async def badge_autocomplete(self, interaction: discord.Interaction, current: str):
        cur = current.lower()
        return [app_commands.Choice(name=f"{plain_name(a['role'])} — {a['desc']}"[:100], value=badge_key(a))
                for a in config.ACHIEVEMENTS if cur in f"{a['role']} {a['desc']}".lower()][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
