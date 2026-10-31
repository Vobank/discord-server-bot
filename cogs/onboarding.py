"""Вход на сервер: пошаговая анкета в #👋・старт — 1) пол → 2) день рождения → 3) игры.
Одна кнопка «📝 Заполнить анкету» открывает личное окно, каждый шаг заменяет предыдущий в том же окне,
поэтому ничего не копится и порядок не перепутать. После анкеты там же можно что-то изменить."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import db
from cogs.adult_channels import sync_member
from cogs.birthdays import MONTHS, save_birthday, set_public, validate
from utils import (DEPT_ROLE_NAMES, GENDER_NAMES, finish_if_complete, is_pending, rules_channel, set_stash,
                   stashed_roles)

log = logging.getLogger(__name__)
GAME_LOCKS: dict[int, "asyncio.Lock"] = {}  # по человеку: клики по играм — строго по очереди
status_line = finish_if_complete
COLOUR = discord.Colour.blurple()
STEP_NAMES = {"gender": (1, "Пол"), "bday": (2, "День рождения"), "privacy": (2, "День рождения"),
              "games": (3, "Игры")}


async def apply_games(member: discord.Member, chosen: set[str]) -> str:
    """Выдать/забрать игровые роли по выбору. Пока анкета не заполнена — запоминаем до открытия сервера."""
    guild = member.guild
    if is_pending(member):
        if not chosen:
            return "Выбери хотя бы одну игру 🙂 — без этого анкета не засчитается."
        game_roles = {g["role"] for g in config.GAMES}
        keep = [r for r in await stashed_roles(member) if r.name not in game_roles]  # Секта, бета-тестер и т.п.
        roles = [r for g in config.GAMES if g["name"] in chosen
                 and (r := discord.utils.get(guild.roles, name=g["role"]))]
        await set_stash(member, keep + roles)
        await db.set_setting(guild.id, f"games_ok:{member.id}", "1")
        text = "🎮 Запомнил игры: " + ", ".join(f"**{g}**" for g in chosen)
        return text + await status_line(member)
    add, remove = [], []
    for game in config.GAMES:
        role = discord.utils.get(guild.roles, name=game["role"])
        if role is None:
            continue
        if game["name"] in chosen and role not in member.roles:
            add.append(role)
        elif game["name"] not in chosen and role in member.roles:
            remove.append(role)
    try:
        if add:
            await member.add_roles(*add, reason="Выбор игр")
        if remove:
            await member.remove_roles(*remove, reason="Выбор игр")
    except discord.Forbidden:
        return "⚠️ Боту не хватает прав выдать роль — сообщи администрации."
    text = ("🎮 Твои игры: " + ", ".join(f"**{g}**" for g in chosen)) if chosen else "Ты убрал все игры."
    if chosen:
        text += "\nКатегории этих игр появились в списке каналов слева."
    return text + await status_line(member)


async def current_games(member: discord.Member) -> set[str]:
    names = {r.name for r in [*member.roles, *await stashed_roles(member)]}
    return {g["name"] for g in config.GAMES if g["role"] in names}


# ---------- состояние анкеты ----------
async def birthday_of(member: discord.Member):
    return await db.fetchone("SELECT day, month, year FROM birthdays WHERE guild_id=? AND user_id=?",
                             (member.guild.id, member.id))


async def next_step(member: discord.Member) -> str:
    """Первый незаполненный шаг или «done»."""
    if not any(r.name in GENDER_NAMES for r in member.roles):
        return "gender"
    row = await birthday_of(member)
    if not row or not row[2] or (is_pending(member) and
                                 not await db.get_setting(member.guild.id, f"bday_ok:{member.id}")):
        return "bday"
    if is_pending(member):
        if not await db.get_setting(member.guild.id, f"games_ok:{member.id}"):
            return "games"
    elif not await current_games(member):
        return "games"
    return "done"


def progress(step: str) -> str:
    if step == "done":
        return "🟢 🟢 🟢"
    n = STEP_NAMES[step][0]
    return " ".join("🟢" if i < n else "🔵" if i == n else "⚪" for i in (1, 2, 3))


async def wiz_games(member: discord.Member) -> set[str]:
    """Игры, отмеченные в окне (хранятся в базе — окно работает и после перезапуска бота)."""
    raw = await db.get_setting(member.guild.id, f"wiz_games:{member.id}")
    if raw is None:
        return set() if is_pending(member) else await current_games(member)
    return {x for x in raw.split("|") if x}


async def set_wiz_games(member: discord.Member, chosen: set[str]):
    await db.set_setting(member.guild.id, f"wiz_games:{member.id}", "|".join(sorted(chosen)))


async def render(member: discord.Member, step: str, note: str = "", chosen: set[str] | None = None):
    """Экран анкеты для шага: (embed, view)."""
    if step == "done":
        g = next((label for r, _, label in config.GENDERS if any(x.name == r for x in member.roles)), "—")
        row = await birthday_of(member)
        bday = f"{row[0]} {MONTHS[row[1]]} {row[2]}" if row and row[2] else "—"
        games = ", ".join(sorted(await current_games(member))) or "—"
        e = discord.Embed(title=f"{progress(step)}  Анкета заполнена!", colour=discord.Colour.green(),
                          description=(note + "\n\n" if note else "") +
                          f"🚻 **Пол:** {g}\n🎂 **День рождения:** {bday}\n🎮 **Игры:** {games}\n\n"
                          "Игры можно поменять кнопкой ниже.\n"
                          "Пол и дату рождения меняет только **администрация** — если ошибся, напиши админу.")
        return e, DoneView()

    num, name = STEP_NAMES[step]
    e = discord.Embed(title=f"{progress(step)}  Шаг {num} из 3 — {name}", colour=COLOUR)
    if step == "gender":
        e.description = "Выбери свой пол:"
        view = GenderStep()
    elif step == "bday":
        e.description = ("Нажми кнопку и введи **день, месяц и год** рождения.\n"
                         "В свой день рождения получишь поздравление от всего сервера 🎉")
        view = BirthdayStep()
    elif step == "privacy":
        e.description = ("**Показывать твой день рождения всем на сервере?**\n"
                         "Если да — в этот день весь сервер увидит поздравление в 📅・календарь.\n"
                         "Если нет — поздравлю лично в ЛС.")
        view = PrivacyStep()
    else:
        if chosen is None:  # зашли на шаг игр: новичок — с чистого листа, остальные — с того, что есть
            chosen = set() if is_pending(member) else await current_games(member)
            await set_wiz_games(member, chosen)
        picked = ", ".join(f"**{x}**" for x in sorted(chosen)) or "пока ничего"
        e.description = (f"Нажимай на игры, в которые играешь — выбранные горят **зелёным**.\n"
                         f"Выбрано: {picked}\n\nКогда закончишь — жми **✅ Подтвердить**.")
        view = GamesStep(chosen)
    if note:
        e.description = note + "\n\n" + e.description
    return e, view


async def show(interaction: discord.Interaction, step: str | None = None, note: str = "", chosen=None):
    """Перерисовать окно анкеты (ответ на кнопку или окно ввода)."""
    member = await interaction.guild.fetch_member(interaction.user.id)
    step = step or await next_step(member)
    if step == "done" and is_pending(member):
        note = (note + "\n" if note else "") + (await finish_if_complete(member)).strip()
        member = await interaction.guild.fetch_member(member.id)
    embed, view = await render(member, step, note, chosen)
    await interaction.edit_original_response(content=None, embed=embed, view=view)


class Step(discord.ui.View):
    """Кнопки анкеты постоянные (timeout=None + custom_id) — работают даже после перезапуска бота."""

    def __init__(self):
        super().__init__(timeout=None)


# ---------- шаг 1: пол ----------
class GenderStep(Step):
    def __init__(self):
        super().__init__()
        for role_name, emoji, label in config.GENDERS:
            btn = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.primary,
                                    custom_id=f"wiz:gender:{role_name}")
            btn.callback = self._pick(role_name, label)
            self.add_item(btn)

    def _pick(self, role_name: str, label: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            guild, member = interaction.guild, interaction.user
            if any(r.name in GENDER_NAMES for r in member.roles):  # пол меняет только администрация
                return await show(interaction, note="🚻 Пол уже выбран. Сменить его может только администрация.")
            role = discord.utils.get(guild.roles, name=role_name)
            try:
                others = [r for r in member.roles if r.name in GENDER_NAMES and r != role]
                if others:
                    await member.remove_roles(*others, reason="Выбор пола")
                if role and role not in member.roles:
                    await member.add_roles(role, reason="Выбор пола")
            except discord.Forbidden:
                return await show(interaction, "gender", "⚠️ Боту не хватает прав выдать роль — сообщи администрации.")
            await show(interaction, note=f"✅ Пол: **{label}**")
        return callback


# ---------- шаг 2: день рождения ----------
class BirthdayModal(discord.ui.Modal, title="🎂 Твой день рождения"):
    day = discord.ui.TextInput(label="День (1-31)", placeholder="15", max_length=2)
    month = discord.ui.TextInput(label="Месяц (1-12)", placeholder="7", max_length=2)
    year = discord.ui.TextInput(label="Год рождения", placeholder="2005", min_length=4, max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            d, m, y = int(self.day.value), int(self.month.value), int(self.year.value)
        except ValueError:
            return await show(interaction, "bday", "⚠️ Вводи только цифры 🙂")
        if err := validate(d, m, y):
            return await show(interaction, "bday", f"⚠️ {err}")
        member = await interaction.guild.fetch_member(interaction.user.id)
        if await next_step(member) != "bday":  # дату меняет только администрация
            return await show(interaction, note="🎂 Дата рождения уже указана. Если ошибся — напиши администрации.")
        await save_birthday(interaction.guild.id, interaction.user.id, d, m, y)
        await db.set_setting(interaction.guild.id, f"bday_ok:{interaction.user.id}", "1")
        await sync_member(await interaction.guild.fetch_member(interaction.user.id))
        await show(interaction, "privacy", f"✅ Записал: **{d} {MONTHS[m]} {y}**")


class BirthdayStep(Step):
    @discord.ui.button(label="Ввести дату рождения", emoji="🎂", style=discord.ButtonStyle.success,
                       custom_id="wiz:bday")
    async def enter(self, interaction: discord.Interaction, _):
        if await next_step(await interaction.guild.fetch_member(interaction.user.id)) != "bday":
            return await interaction.response.send_message(
                "🎂 Дата рождения уже указана. Если ошибся — напиши администрации, она поменяет.", ephemeral=True)
        await interaction.response.send_modal(BirthdayModal())


class PrivacyStep(Step):
    async def _set(self, interaction: discord.Interaction, public: bool):
        await interaction.response.defer()
        await set_public(interaction.guild.id, interaction.user.id, public)
        await show(interaction, note="🎉 Весь сервер поздравит тебя в 📅・календарь" if public
                   else "🤫 Дата останется секретом — поздравлю в ЛС")

    @discord.ui.button(label="Да, пусть все знают", emoji="🎉", style=discord.ButtonStyle.success,
                       custom_id="wiz:priv:yes")
    async def yes(self, interaction, _):
        await self._set(interaction, True)

    @discord.ui.button(label="Нет, держать в секрете", emoji="🤫", style=discord.ButtonStyle.secondary,
                       custom_id="wiz:priv:no")
    async def no(self, interaction, _):
        await self._set(interaction, False)


# ---------- шаг 3: игры ----------
class GamesStep(Step):
    def __init__(self, chosen: set[str] = frozenset()):
        super().__init__()
        for i, game in enumerate(config.GAMES):
            btn = discord.ui.Button(label=game["name"], emoji=game["emoji"], row=i // 4,
                                    custom_id=f"wiz:game:{i}",
                                    style=discord.ButtonStyle.success if game["name"] in chosen
                                    else discord.ButtonStyle.secondary)
            btn.callback = self._toggle(game["name"])
            self.add_item(btn)
        confirm = discord.ui.Button(label="Подтвердить", emoji="✅", style=discord.ButtonStyle.primary, row=2,
                                    custom_id="wiz:games:ok")
        confirm.callback = self._confirm
        self.add_item(confirm)

    def _toggle(self, name: str):
        async def callback(interaction: discord.Interaction):
            # Быстро и без потерь: нажатия одного человека идут строго по очереди (иначе два быстрых
            # клика читали старый выбор и затирали друг друга), и ответ — одно обновление окна, без лишних запросов.
            async with GAME_LOCKS.setdefault(interaction.user.id, asyncio.Lock()):
                chosen = await wiz_games(interaction.user) ^ {name}
                await set_wiz_games(interaction.user, chosen)
                embed, view = await render(interaction.user, "games", chosen=chosen)
                await interaction.response.edit_message(embed=embed, view=view)
        return callback

    async def _confirm(self, interaction: discord.Interaction):
        await interaction.response.defer()
        async with GAME_LOCKS.setdefault(interaction.user.id, asyncio.Lock()):  # дождаться последнего клика
            chosen = await wiz_games(interaction.user)
        if not chosen:
            return await show(interaction, "games", "⚠️ Выбери **хотя бы одну** игру — нажми на неё, "
                                                    "чтобы она загорелась зелёным.", chosen=chosen)
        text = await apply_games(interaction.user, chosen)
        await show(interaction, note=text.split("\n")[0])


# ---------- после анкеты: изменить ----------
class DoneView(Step):
    @discord.ui.button(label="Изменить игры", emoji="🎮", custom_id="wiz:edit:games")
    async def games(self, interaction, _):
        await interaction.response.defer()
        await show(interaction, "games")


# ---------- кнопка в #👋・старт ----------
class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Заполнить анкету", emoji="📝", style=discord.ButtonStyle.success,
                       custom_id="onboard:start")
    async def start(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = await interaction.guild.fetch_member(interaction.user.id)
        step = await next_step(member)
        if step == "done" and is_pending(member):
            await finish_if_complete(member)
            member = await interaction.guild.fetch_member(member.id)
        embed, view = await render(member, step)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def post_panels(bot: commands.Bot, channel: discord.TextChannel):
    """Удаляет старые панели бота в канале и отправляет новую."""
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    games = " · ".join(f"{g['emoji']} {g['name']}" for g in config.GAMES)
    welcome = discord.Embed(
        title=f"👋 Добро пожаловать на {config.SERVER_NAME}!",
        description=(
            "🔒 **Сервер откроется, когда ты заполнишь анкету** — это меньше минуты.\n\n"
            "**Как заполнить:**\n"
            "Нажми **📝 Заполнить анкету** ниже — откроется окно, которое видишь только ты.\n"
            "Бот проведёт по шагам, просто нажимай кнопки:\n\n"
            "**Шаг 1.** 🚻 Пол — Парень или Девушка\n"
            "**Шаг 2.** 🎂 День рождения — день, месяц и год (и можно ли показывать его всем)\n"
            f"**Шаг 3.** 🎮 Игры — отметь свои и нажми **✅ Подтвердить**\n{games}\n\n"
            "Готово — сервер откроется сам 🎉\n"
            "Потом здесь же можно **изменить игры** — снова нажми кнопку.\n"
            "⚠️ Пол и дату рождения выбирай внимательно: поменять их может только **администрация**.\n\n"
            f"📜 Перед этим прочитай {rules.mention if (rules := rules_channel(channel.guild)) else config.CH_RULES}"
        ),
        colour=COLOUR,
    )
    await channel.send(embed=welcome, view=StartView())


class Onboarding(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(StartView())
        for view in (GenderStep(), BirthdayStep(), PrivacyStep(), GamesStep(), DoneView()):
            bot.add_view(view)  # шаги анкеты работают и после перезапуска

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Новичок получает 🔒 Анкета — видит только старт и правила, пока не заполнит анкету."""
        if member.bot or config.is_ghost(member):
            return
        pending = discord.utils.get(member.guild.roles, name=config.ROLE_PENDING)
        for key in ("games_ok", "bday_ok"):  # перезаход — анкету проходить заново, все 3 шага
            await db.set_setting(member.guild.id, f"{key}:{member.id}", "")
        await db.execute("DELETE FROM settings WHERE guild_id=? AND key=?", (member.guild.id, f"wiz_games:{member.id}"))
        try:
            if pending:
                await member.add_roles(pending, reason="Новичок: нужно заполнить анкету")
            await self.hold_roles(member, set(member.roles))
        except discord.Forbidden:
            log.warning("Нет прав на роли новичка — подними роль бота выше")
        channel = discord.utils.get(member.guild.text_channels, name=config.CH_WELCOME)
        if channel:
            try:  # в ЛС, а не в канал — чтобы #старт не засорялся
                await member.send(f"👋 Привет! Добро пожаловать на **{member.guild.name}**.\n"
                                  f"Чтобы открыть сервер, зайди в {channel.mention} и нажми **📝 Заполнить анкету** — "
                                  "это меньше минуты.")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        """Пока бот был выключен, другие боты могли выдать новичкам 👻 или игры — забираем.
        И убираем из #старт всё лишнее от бота (старые «привет!»), оставляя только панель."""
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=config.CH_WELCOME)
            if channel:
                async for msg in channel.history(limit=50):
                    if msg.author == self.bot.user and not msg.components:
                        await msg.delete()
            pending = discord.utils.get(guild.roles, name=config.ROLE_PENDING)
            for member in list(pending.members) if pending else []:
                await self.hold_roles(member, set(member.roles))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Пока анкета не заполнена, 👻 и игровые роли (их выдают другие боты и анкета Discord)
        открыли бы каналы в обход 🔒 — придерживаем их и выдаём после анкеты."""
        if is_pending(after):
            await self.hold_roles(after, set(after.roles) - set(before.roles))

    async def hold_roles(self, member: discord.Member, added: set[discord.Role]):
        if not is_pending(member):
            return
        games = [r for r in added if r.name in DEPT_ROLE_NAMES]
        base = [r for r in added if r.name == config.ROLE_BASE]
        if not games and not base:
            return
        try:
            await member.remove_roles(*games, *base, reason="Выдаётся после анкеты")
        except discord.Forbidden:
            return
        if games:
            await set_stash(member, list({*await stashed_roles(member), *games}))

    @app_commands.command(name="panels", description="Отправить заново панель в #👋・старт")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def panels(self, interaction: discord.Interaction):
        channel = discord.utils.get(interaction.guild.text_channels, name=config.CH_WELCOME)
        if not channel:
            return await interaction.response.send_message("Канала нет — запусти /setup", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await post_panels(self.bot, channel)
        await interaction.followup.send(f"✅ Панель в {channel.mention} обновлена", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Onboarding(bot))
