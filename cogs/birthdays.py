"""Дни рождения и праздники в #📅・календарь.
Человек сам решает, видят ли его ДР все (публично — поздравление в календаре, иначе — только в ЛС)."""
import calendar
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import utils
import db
import greetings
from cogs.adult_channels import sync_member
from utils import GENDER_NAMES, finish_if_complete

MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


def validate(day: int, month: int, year: int | None) -> str | None:
    try:
        datetime.date(2000, month, day)  # 2000 — високосный, 29 февраля допустимо
    except ValueError:
        return "Такой даты не бывает 🤔"
    if year is None:
        return "Укажи год рождения — он обязателен"
    if year is not None:
        now = datetime.date.today().year
        if not 1920 <= year <= now:
            return f"Год должен быть от 1920 до {now}"
        try:
            datetime.date(year, month, day)
        except ValueError:
            return "В этом году не было такого дня 🤔"
    return None


async def save_birthday(guild_id: int, user_id: int, day: int, month: int, year: int | None):
    await db.execute(
        "INSERT INTO birthdays (guild_id, user_id, day, month, year) VALUES (?,?,?,?,?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET day=excluded.day, month=excluded.month, year=excluded.year",
        (guild_id, user_id, day, month, year),
    )


async def set_public(guild_id: int, user_id: int, public: bool):
    await db.execute("UPDATE birthdays SET public=? WHERE guild_id=? AND user_id=?",
                     (int(public), guild_id, user_id))


def is_today(day: int, month: int, today: datetime.date) -> bool:
    if (day, month) == (today.day, today.month):
        return True
    # 29 февраля в невисокосный год поздравляем 28-го
    return (day, month) == (29, 2) and not calendar.isleap(today.year) and (today.day, today.month) == (28, 2)


def next_birthday(day: int, month: int, today: datetime.date) -> datetime.date:
    for y in (today.year, today.year + 1):
        try:
            d = datetime.date(y, month, day)
        except ValueError:
            d = datetime.date(y, 2, 28)
        if d >= today:
            return d


class PrivacyView(discord.ui.View):
    """Показывать ли ДР всем — спрашиваем после ввода даты."""

    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.guild_id, self.user_id = guild_id, user_id

    async def _set(self, interaction: discord.Interaction, public: bool):
        await set_public(self.guild_id, self.user_id, public)
        text = ("🎉 Отлично! В твой день рождения весь сервер поздравит тебя в #📅・календарь."
                if public else "🤫 Хорошо, дата останется секретом — поздравлю тебя лично в ЛС.")
        await interaction.response.edit_message(content=text, view=None)

    @discord.ui.button(label="Да, пусть все знают", emoji="🎉", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, _):
        await self._set(interaction, True)

    @discord.ui.button(label="Нет, держать в секрете", emoji="🤫", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, _):
        await self._set(interaction, False)


class BirthdayModal(discord.ui.Modal, title="🎂 Твой день рождения"):
    day = discord.ui.TextInput(label="День (1-31)", placeholder="15", max_length=2)
    month = discord.ui.TextInput(label="Месяц (1-12)", placeholder="7", max_length=2)
    year = discord.ui.TextInput(label="Год рождения", placeholder="2005", min_length=4, max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            d, m, y = int(self.day.value), int(self.month.value), int(self.year.value)
        except ValueError:
            return await interaction.response.send_message("Вводи только цифры 🙂", ephemeral=True)
        if err := validate(d, m, y):
            return await interaction.response.send_message(err, ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        await save_birthday(interaction.guild.id, interaction.user.id, d, m, y)
        text = f"🎂 Записал: **{d} {MONTHS[m]} {y}**"
        text += await finish_if_complete(interaction.user)
        await sync_member(await interaction.guild.fetch_member(interaction.user.id))
        await interaction.followup.send(text, ephemeral=True)
        await interaction.followup.send("**Показывать твой день рождения всем на сервере?**\n"
                                        "Если да — в этот день весь сервер увидит поздравление в #📅・календарь.",
                                        view=PrivacyView(interaction.guild.id, interaction.user.id), ephemeral=True)


def gender_of(member: discord.Member) -> str | None:
    return next((r.name for r in member.roles if r.name in GENDER_NAMES), None)


class Birthdays(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checker.start()

    def cog_unload(self):
        self.checker.cancel()

    # Каждые 15 минут — если бот был выключен в BIRTHDAY_HOUR, поздравит позже
    @tasks.loop(minutes=15)
    async def checker(self):
        now = datetime.datetime.now(config.TIMEZONE)
        today = now.date()
        rows = await db.fetchall("SELECT guild_id, user_id, day, month, year, last_congrats, public FROM birthdays")

        # Роль «🎂 Именинник» — только в сам день рождения
        bday_today = {(g, u) for g, u, d, m, *_ in rows if is_today(d, m, today)}
        for guild in self.bot.guilds:
            role = discord.utils.get(guild.roles, name=config.ROLE_BIRTHDAY)
            for m in role.members if role else []:
                if (guild.id, m.id) not in bday_today:
                    await m.remove_roles(role, reason="День рождения прошёл")

        if now.hour < config.BIRTHDAY_HOUR:
            return
        for guild in self.bot.guilds:
            await self.holidays(guild, today)
        for guild_id, user_id, day, month, year, last, public in rows:
            if last == today.year or not is_today(day, month, today):
                continue
            guild = self.bot.get_guild(guild_id)
            member = guild and guild.get_member(user_id)
            if not member or config.is_ghost(member):  # невидимок не поздравляем публично
                continue
            await self.congratulate(member, year, bool(public), today)
            await db.execute("UPDATE birthdays SET last_congrats=? WHERE guild_id=? AND user_id=?",
                             (today.year, guild_id, user_id))

    async def congratulate(self, member: discord.Member, year: int | None, public: bool, today: datetime.date):
        guild = member.guild
        age = today.year - year if year else None
        text = greetings.birthday_text(gender_of(member), age, member.mention)
        embed = discord.Embed(title="🎉 С днём рождения!", description=text, colour=discord.Colour.magenta())
        embed.set_thumbnail(url=member.display_avatar.url)
        if age:
            embed.set_footer(text=f"Исполняется {age} 🎈")

        role = discord.utils.get(guild.roles, name=config.ROLE_BIRTHDAY)
        if role and role < guild.me.top_role:
            await member.add_roles(role, reason="День рождения")
        if public:
            if channel := discord.utils.get(guild.text_channels, name=config.CH_BIRTHDAYS):
                await channel.send(content=member.mention, embed=embed)
            if general := utils.general_channel(guild):
                await general.send(f"🎂 Сегодня день рождения у {member.mention}! Поздравьте 🎉")
        else:
            embed.title = f"🎉 С днём рождения от сервера {guild.name}!"
            embed.description = text.replace(member.mention, f"**{member.display_name}**")
            try:
                await member.send(embed=embed)
            except discord.HTTPException:
                pass

    async def holidays(self, guild: discord.Guild, today: datetime.date):
        channel = discord.utils.get(guild.text_channels, name=config.CH_BIRTHDAYS)
        if not channel:
            return
        key = f"holiday:{today.isoformat()}"
        if await db.get_setting(guild.id, key):
            return
        posts = []
        if h := greetings.holiday_for(today.day, today.month):
            posts.append((h[0], h[1].format(server=guild.name)))
        created = guild.created_at.astimezone(config.TIMEZONE).date()
        if (created.day, created.month) == (today.day, today.month) and today.year > created.year:
            years = today.year - created.year
            posts.append((f"🎂 Серверу {guild.name} исполняется {years}!",
                          f"Спасибо каждому, кто с нами! Вместе нас уже {guild.member_count - len([m for m in guild.members if config.is_ghost(m)])} 💜"))
        for title, text in posts:
            await channel.send(content="@everyone", embed=discord.Embed(title=title, description=text,
                                                                         colour=discord.Colour.gold()),
                               allowed_mentions=discord.AllowedMentions(everyone=True))
        await db.set_setting(guild.id, key, "1")

    @checker.before_loop
    async def before_checker(self):
        await self.bot.wait_until_ready()

    group = app_commands.Group(name="birthday", description="Дни рождения", guild_only=True)

    @group.command(name="set", description="Указать свой день рождения (если ещё не указан)")
    async def bd_set(self, interaction: discord.Interaction):
        row = await db.fetchone("SELECT year FROM birthdays WHERE guild_id=? AND user_id=?",
                                (interaction.guild.id, interaction.user.id))
        if row and row[0]:  # дату меняет только администрация
            return await interaction.response.send_message(
                "🎂 Дата рождения уже указана. Если ошибся — напиши администрации, она поменяет.", ephemeral=True)
        await interaction.response.send_modal(BirthdayModal())

    @group.command(name="privacy", description="Показывать ли твой ДР всем")
    async def bd_privacy(self, interaction: discord.Interaction):
        await interaction.response.send_message("**Показывать твой день рождения всем на сервере?**",
                                                view=PrivacyView(interaction.guild.id, interaction.user.id),
                                                ephemeral=True)

    @group.command(name="remove", description="(Админ) Удалить свой день рождения")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def bd_remove(self, interaction: discord.Interaction):
        await db.execute("DELETE FROM birthdays WHERE guild_id=? AND user_id=?",
                         (interaction.guild.id, interaction.user.id))
        await interaction.response.send_message("🗑️ Удалено", ephemeral=True)

    @group.command(name="list", description="Ближайшие дни рождения (только публичные)")
    async def bd_list(self, interaction: discord.Interaction):
        today = datetime.datetime.now(config.TIMEZONE).date()
        rows = await db.fetchall("SELECT user_id, day, month FROM birthdays WHERE guild_id=? AND public=1",
                                 (interaction.guild.id,))
        items = []
        for user_id, day, month in rows:
            member = interaction.guild.get_member(user_id)
            if member and not config.is_ghost(member):
                nxt = next_birthday(day, month, today)
                items.append(((nxt - today).days, member, day, month))
        items.sort(key=lambda x: x[0])
        if not items:
            return await interaction.response.send_message("Пока никто не указал день рождения", ephemeral=True)
        lines = [f"**{d} {MONTHS[m]}** — {mem.mention}" + (" 🎉 сегодня!" if days == 0 else f" (через {days} дн.)")
                 for days, mem, d, m in items[:20]]
        embed = discord.Embed(title="🎂 Ближайшие дни рождения", description="\n".join(lines),
                              colour=discord.Colour.magenta())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="add", description="(Админ) Указать день рождения другому участнику")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def bd_add(self, interaction: discord.Interaction, member: discord.Member,
                     day: app_commands.Range[int, 1, 31], month: app_commands.Range[int, 1, 12],
                     year: app_commands.Range[int, 1920, 2100], public: bool = True):
        if err := validate(day, month, year):
            return await interaction.response.send_message(err, ephemeral=True)
        await save_birthday(interaction.guild.id, member.id, day, month, year)
        await set_public(interaction.guild.id, member.id, public)
        await sync_member(member)
        await interaction.response.send_message(f"✅ {member.mention}: {day} {MONTHS[month]}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthdays(bot))
