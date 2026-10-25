"""🎉 Сообщество: 💡 идеи с голосованием, ⭐ зал славы, ⏰ /remind, 📰 итоги недели."""
import datetime
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import utils
import db
from cogs import achievements

IDEA_STATUS = {
    "new": ("🗳️ Голосование", discord.Colour.blurple()),
    "accepted": ("✅ Принято", discord.Colour.green()),
    "progress": ("🛠️ В работе", discord.Colour.gold()),
    "done": ("🎉 Сделано", discord.Colour.teal()),
    "rejected": ("❌ Отклонено", discord.Colour.red()),
}


def is_staff(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.name in config.STAFF_ROLES for r in member.roles)


def week_key(dt: datetime.datetime | None = None) -> str:
    y, w, _ = (dt or datetime.datetime.now(config.TIMEZONE)).isocalendar()
    return f"{y}-{w:02}"


# ---------- 💡 идеи ----------
def idea_embed(author: discord.abc.User, idea_id: int, title: str, text: str, status: str, note: str = ""):
    label, colour = IDEA_STATUS[status]
    e = discord.Embed(title=f"💡 {title}", description=text, colour=colour, timestamp=discord.utils.utcnow())
    e.set_author(name=f"Идея №{idea_id} · {author.display_name}", icon_url=author.display_avatar.url)
    e.add_field(name="Статус", value=label + (f"\n{note}" if note else ""))
    e.set_footer(text="Голосуй реакциями 👍 / 👎")
    return e


class IdeaModal(discord.ui.Modal, title="💡 Твоя идея для сервера"):
    head = discord.ui.TextInput(label="Коротко: что предлагаешь?", max_length=100,
                                placeholder="Например: турнир по CS2 каждую пятницу")
    body = discord.ui.TextInput(label="Подробнее", style=discord.TextStyle.paragraph, max_length=1500,
                                placeholder="Как это должно работать, зачем это серверу")

    async def on_submit(self, interaction: discord.Interaction):
        g = interaction.guild
        channel = discord.utils.get(g.text_channels, name=config.CH_IDEAS)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await db.execute("INSERT INTO ideas (guild_id, user_id, title, text, created_at) VALUES (?,?,?,?,?)",
                         (g.id, interaction.user.id, self.head.value, self.body.value, int(time.time())))
        (idea_id,) = await db.fetchone("SELECT last_insert_rowid()")
        msg = await channel.send(embed=idea_embed(interaction.user, idea_id, self.head.value, self.body.value, "new"),
                                 view=IdeaAdminView())
        for emoji in ("👍", "👎"):
            await msg.add_reaction(emoji)
        await db.execute("UPDATE ideas SET message_id=? WHERE id=?", (msg.id, idea_id))
        try:
            await msg.create_thread(name=f"💬 Обсуждение идеи №{idea_id}")
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"✅ Идея опубликована в {channel.mention}! Когда админы её рассмотрят — "
                                        "напишу в ЛС.", ephemeral=True)
        await post_ideas_panel(interaction.client, channel)  # кнопка «Предложить» — снова внизу


class IdeaAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_staff(interaction.user):
            return True
        await interaction.response.send_message("Голосуй реакциями 👍 / 👎 — статус ставит администрация 🙂",
                                                ephemeral=True)
        return False

    async def set_status(self, interaction: discord.Interaction, status: str):
        row = await db.fetchone("SELECT id, user_id, title, text FROM ideas WHERE message_id=?",
                                (interaction.message.id,))
        if not row:
            return await interaction.response.send_message("Идея не найдена", ephemeral=True)
        idea_id, user_id, title, text = row
        await db.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))
        author = interaction.guild.get_member(user_id) or await interaction.client.fetch_user(user_id)
        up = next((r.count - 1 for r in interaction.message.reactions if str(r.emoji) == "👍"), 0)
        down = next((r.count - 1 for r in interaction.message.reactions if str(r.emoji) == "👎"), 0)
        note = f"{interaction.user.mention} · 👍 {up} / 👎 {down}"
        final = status in ("done", "rejected")
        await interaction.response.edit_message(embed=idea_embed(author, idea_id, title, text, status, note),
                                                view=None if final else IdeaAdminView())
        try:
            await author.send(f"💡 Твоя идея «**{title}**» на сервере **{interaction.guild.name}**: "
                              f"{IDEA_STATUS[status][0]}")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Принять", emoji="✅", style=discord.ButtonStyle.success, custom_id="idea:accept")
    async def accept(self, i, _):
        await self.set_status(i, "accepted")

    @discord.ui.button(label="В работе", emoji="🛠️", custom_id="idea:progress")
    async def progress(self, i, _):
        await self.set_status(i, "progress")

    @discord.ui.button(label="Сделано", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="idea:done")
    async def done(self, i, _):
        await self.set_status(i, "done")

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="idea:reject")
    async def reject(self, i, _):
        await self.set_status(i, "rejected")


class IdeasPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Предложить идею", emoji="💡", style=discord.ButtonStyle.success, custom_id="idea:new")
    async def new(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(IdeaModal())


async def post_ideas_panel(bot: commands.Bot, channel: discord.TextChannel):
    """Панель с кнопкой всегда последним сообщением в канале."""
    async for msg in channel.history(limit=15):
        if msg.author == bot.user and msg.components and msg.components[0].children[0].custom_id == "idea:new":
            await msg.delete()
    await channel.send(embed=discord.Embed(
        title="💡 Есть идея для сервера?",
        description="Жми **💡 Предложить идею** — она появится здесь, все проголосуют 👍 / 👎, "
                    "а администрация поставит статус: ✅ принято, 🛠️ в работе, 🎉 сделано или ❌ отклонено.\n"
                    "Автору придёт ответ в ЛС. Обсуждать идею — в её ветке 💬.",
        colour=discord.Colour.gold()), view=IdeasPanelView())


# ---------- ⏰ напоминания ----------
def parse_when(text: str) -> datetime.datetime | None:
    now = datetime.datetime.now(config.TIMEZONE)
    t = text.lower().strip().replace(" ", "")
    if m := re.fullmatch(r"(\d+)(м|мин|минут[уы]?|m)", t):
        return now + datetime.timedelta(minutes=int(m[1]))
    if m := re.fullmatch(r"(\d+)(ч|час|часа|часов|h)", t):
        return now + datetime.timedelta(hours=int(m[1]))
    if m := re.fullmatch(r"(\d+)(д|дн|день|дня|дней|d)", t):
        return now + datetime.timedelta(days=int(m[1]))
    if m := re.fullmatch(r"(завтра)?(\d{1,2})[:.](\d{2})", t):
        when = now.replace(hour=int(m[2]), minute=int(m[3]), second=0, microsecond=0)
        if m[1] or when <= now:
            when += datetime.timedelta(days=1)
        return when
    return None


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(IdeaAdminView())
        bot.add_view(IdeasPanelView())
        self.reminder_loop.start()
        self.digest_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()
        self.digest_loop.cancel()

    # --- ⭐ зал славы ---
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != config.STAR_EMOJI or not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        board = discord.utils.get(guild.text_channels, name=config.CH_STARBOARD)
        channel = guild.get_channel(payload.channel_id)
        if not board or not channel or channel.id == board.id or getattr(channel, "nsfw", False):
            return
        if channel.name in (config.CH_GIRLS, config.CH_BOYS) or channel.category and \
                channel.category.name == config.CAT_ADMIN:
            return  # из закрытых каналов в общий зал не выносим
        if await db.fetchone("SELECT 1 FROM starboard WHERE message_id=?", (payload.message_id,)):
            return
        msg = await channel.fetch_message(payload.message_id)
        stars = next((r.count for r in msg.reactions if str(r.emoji) == config.STAR_EMOJI), 0)
        if stars < config.STAR_COUNT or msg.author.bot:
            return
        e = discord.Embed(description=msg.content[:4000] or None, colour=discord.Colour.gold(),
                          timestamp=msg.created_at)
        e.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
        img = next((a.url for a in msg.attachments if (a.content_type or "").startswith("image")), None)
        if img:
            e.set_image(url=img)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="К сообщению", url=msg.jump_url))
        posted = await board.send(content=f"⭐ **{stars}** · {channel.mention}", embed=e, view=view)
        await db.execute("INSERT OR IGNORE INTO starboard (guild_id, message_id, board_message_id) VALUES (?,?,?)",
                         (guild.id, msg.id, posted.id))
        await achievements.bump(msg.author, "stars") if isinstance(msg.author, discord.Member) else None

    # --- ⏰ /remind ---
    @app_commands.command(name="remind", description="Напомнить тебе о чём-то: через 30м, 2ч, 1д или в 18:30")
    @app_commands.describe(when="Когда: 30м, 2ч, 3д, 18:30, завтра 10:00", what="О чём напомнить")
    @app_commands.guild_only()
    async def remind(self, interaction: discord.Interaction, when: str, what: app_commands.Range[str, 1, 300]):
        due = parse_when(when)
        if not due or due - datetime.datetime.now(config.TIMEZONE) > datetime.timedelta(days=90):
            return await interaction.response.send_message(
                "Не понял, когда 🤔 Пиши так: `30м`, `2ч`, `3д`, `18:30` или `завтра 10:00` (до 90 дней)", ephemeral=True)
        await db.execute("INSERT INTO reminders (guild_id, user_id, channel_id, text, due) VALUES (?,?,?,?,?)",
                         (interaction.guild.id, interaction.user.id, interaction.channel.id, what, int(due.timestamp())))
        await interaction.response.send_message(f"⏰ Напомню <t:{int(due.timestamp())}:R> (<t:{int(due.timestamp())}:f>): "
                                                f"**{what}**", ephemeral=True)

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        rows = await db.fetchall("SELECT id, guild_id, user_id, channel_id, text FROM reminders WHERE due<=?",
                                 (int(time.time()),))
        for rid, gid, uid, cid, text in rows:
            await db.execute("DELETE FROM reminders WHERE id=?", (rid,))
            user = self.bot.get_user(uid)
            try:
                await (user or await self.bot.fetch_user(uid)).send(f"⏰ **Напоминание:** {text}")
            except discord.HTTPException:
                ch = self.bot.get_channel(cid)
                if ch:
                    await ch.send(f"⏰ <@{uid}>, напоминание: **{text}**", delete_after=3600)

    # --- 📰 итоги недели ---
    @tasks.loop(minutes=15)
    async def digest_loop(self):
        now = datetime.datetime.now(config.TIMEZONE)
        if now.weekday() != config.DIGEST_WEEKDAY or now.hour < config.DIGEST_HOUR:
            return
        for g in self.bot.guilds:
            key = f"digest:{week_key(now)}"
            if await db.get_setting(g.id, key):
                continue
            await db.set_setting(g.id, key, "1")
            channel = utils.general_channel(g)
            if channel:
                await channel.send(embed=await self.digest_embed(g, now))

    async def digest_embed(self, g: discord.Guild, now: datetime.datetime) -> discord.Embed:
        wk = week_key(now)
        msgs = await db.fetchall("SELECT user_id, value FROM stats WHERE guild_id=? AND key=? ORDER BY value DESC "
                                 "LIMIT 5", (g.id, f"wmsg:{wk}"))
        voice = await db.fetchall("SELECT user_id, value FROM stats WHERE guild_id=? AND key=? ORDER BY value DESC "
                                  "LIMIT 3", (g.id, f"wvoice:{wk}"))
        week_ago = discord.utils.utcnow() - datetime.timedelta(days=7)
        newbies = [m for m in g.members if not m.bot and m.joined_at and m.joined_at > week_ago]
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        e = discord.Embed(title="📰 Итоги недели", colour=discord.Colour.purple(),
                          description=f"Неделя {now.strftime('%d.%m')} · спасибо, что вы с нами 💜")
        e.add_field(name="💬 Самые активные в чате",
                    value="\n".join(f"{medals[i]} <@{u}> — {v} сообщ." for i, (u, v) in enumerate(msgs)) or "—",
                    inline=False)
        e.add_field(name="🎙️ Больше всех в голосовых",
                    value="\n".join(f"{medals[i]} <@{u}> — {v // 60} ч {v % 60} мин" for i, (u, v) in enumerate(voice))
                    or "—", inline=False)
        e.add_field(name="👋 Новички недели", value=(", ".join(m.mention for m in newbies[:20]) +
                                                    (f" и ещё {len(newbies) - 20}" if len(newbies) > 20 else ""))
                    or "—", inline=False)
        from cogs.birthdays import MONTHS, next_birthday
        today = now.date()
        rows = await db.fetchall("SELECT user_id, day, month FROM birthdays WHERE guild_id=? AND public=1", (g.id,))
        soon = sorted(((next_birthday(d, m, today) - today).days, u, d, m) for u, d, m in rows if g.get_member(u))
        soon = [s for s in soon if 0 < s[0] <= 7]
        e.add_field(name="🎂 Дни рождения на следующей неделе",
                    value="\n".join(f"**{d} {MONTHS[m]}** — <@{u}>" for _, u, d, m in soon) or "—", inline=False)
        return e

    @app_commands.command(name="digest", description="(Админ) Показать итоги этой недели прямо сейчас")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def digest(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=await self.digest_embed(interaction.guild, datetime.datetime.now(config.TIMEZONE)), ephemeral=True)

    # недельные счётчики для итогов
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild and not message.author.bot:
            await achievements.add_stat(message.guild.id, message.author.id, f"wmsg:{week_key()}")

    @reminder_loop.before_loop
    @digest_loop.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Community(bot))
