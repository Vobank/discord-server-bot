"""Админ-панель с кнопками в #админ-панель: роли, админы отделов, модерация, объявления, статистика."""
import datetime

import discord
from discord.ext import commands

import config
import db
import perms
import punish
import role_info
from cogs.birthdays import MONTHS, save_birthday, validate
from utils import finish_if_complete

COLOUR = discord.Colour.dark_red()


async def log_action(guild: discord.Guild, text: str):
    ch = discord.utils.get(guild.text_channels, name=config.CH_ADMIN_LOG)
    if ch:
        await ch.send(embed=discord.Embed(description=text, colour=COLOUR, timestamp=discord.utils.utcnow()),
                      allowed_mentions=discord.AllowedMentions.none())


def role_problem(actor: discord.Member, role: discord.Role, check_actor: bool = True) -> str | None:
    guild = actor.guild
    if role.is_default() or role.managed:
        return f"**{role.name}** — системная роль, её нельзя выдать"
    if role >= guild.me.top_role:
        return f"**{role.name}** выше роли бота — подними бота в списке ролей"
    if check_actor and actor != guild.owner and role >= actor.top_role:
        return f"**{role.name}** не ниже твоей самой высокой роли"
    return None


def target_problem(actor: discord.Member, target: discord.Member) -> str | None:
    guild = actor.guild
    if target == actor:
        return "Нельзя применить к себе"
    if target == guild.owner:
        return "Владельца сервера трогать нельзя"
    if target.top_role >= guild.me.top_role:
        return "Этот участник выше бота по ролям"
    if actor != guild.owner and target.top_role >= actor.top_role:
        return "У этого участника роль не ниже твоей"
    return None


def as_member(guild: discord.Guild, user) -> discord.Member | None:
    return user if isinstance(user, discord.Member) else guild.get_member(user.id)


def hint(title: str, text: str) -> discord.Embed:
    return discord.Embed(title=title, description=text, colour=COLOUR)


class StaffView(discord.ui.View):
    """Меню, доступное только тем, у кого есть право на функцию feature."""

    def __init__(self, feature: str):
        super().__init__(timeout=600)
        self.feature = feature

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not await perms.deny(interaction, self.feature)

    async def finish(self, interaction: discord.Interaction, text: str):
        """Заменяет сообщение с меню итогом (меню исчезает)."""
        await interaction.edit_original_response(content=text, embed=None, view=None)


# ---------- Роли ----------
def manageable_roles(actor: discord.Member) -> list[discord.Role]:
    """Роли, которые этот человек может выдавать через бота (сверху вниз, как в настройках)."""
    return [r for r in sorted(actor.guild.roles, key=lambda r: r.position, reverse=True)
            if role_problem(actor, r) is None]


def role_desc(role: discord.Role) -> str:
    """Подпись под ролью в меню: кому выдавать + сколько людей (лимит Discord — 100 символов)."""
    count = f"{len(role.members)} чел."
    who = role_info.info(role.name)
    if not who:
        return f"Сейчас у {count}"
    return f"{who[:100 - len(count) - 3]} · {count}"


USER_HINT ="👤 Кому? Начни печатать ник для поиска"


class RoleView(StaffView):
    def __init__(self, add: bool, actor: discord.Member):
        super().__init__("roles")
        self.add = add
        self.users = []
        self.picked: dict[str, list[str]] = {}
        self.apply.label = "✅ Выдать" if add else "➖ Забрать"
        self.apply.style = discord.ButtonStyle.success if add else discord.ButtonStyle.danger

        # Свой список ролей: в нём ВСЕ роли, которые можно выдать (по 25 в одном меню, до 3 меню)
        roles = manageable_roles(actor)[:75]
        self.has_roles = bool(roles)
        for i in range(0, len(roles), 25):
            chunk = roles[i:i + 25]
            part = f" — список {i // 25 + 1}" if len(roles) > 25 else ""
            select = discord.ui.Select(
                placeholder=f"🎭 Какие роли?{part}", min_values=0, max_values=len(chunk), row=1 + i // 25,
                options=[discord.SelectOption(label=r.name[:100], value=str(r.id), description=role_desc(r))
                         for r in chunk])
            select.callback = self._remember(select)
            self.add_item(select)

    def _remember(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            self.picked[select.custom_id] = select.values
            await interaction.response.defer()
        return callback

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder=USER_HINT, min_values=1, max_values=10, row=0)
    async def pick_users(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.users = select.values
        await interaction.response.defer()

    @discord.ui.button(label="Применить", row=4)
    async def apply(self, interaction: discord.Interaction, _):
        g = interaction.guild
        if not self.has_roles:
            return await interaction.response.send_message(
                "Нет ролей, которые ты можешь выдавать. Роль бота и твоя роль должны быть выше них.", ephemeral=True)
        selected = [g.get_role(int(rid)) for ids in self.picked.values() for rid in ids]
        selected = [r for r in selected if r]
        if not self.users or not selected:
            return await interaction.response.send_message("Выбери людей и роли в меню выше 👆", ephemeral=True)
        if problems := [p for r in selected if (p := role_problem(interaction.user, r))]:
            return await interaction.response.send_message("⚠️ " + "\n".join(problems), ephemeral=True)
        await interaction.response.defer()

        members = [m for u in self.users if (m := as_member(g, u))]
        reason = f"Админ-панель: {interaction.user}"
        for m in members:
            if self.add:
                await m.add_roles(*selected, reason=reason)
            else:
                await m.remove_roles(*selected, reason=reason)

        roles = ", ".join(r.mention for r in selected)
        people = ", ".join(m.mention for m in members)
        verb = "выдал" if self.add else "забрал"
        await self.finish(interaction, f"✅ Готово: {roles} → {people}")
        await log_action(g, f"🎭 {interaction.user.mention} {verb} {roles} — {people}")


# ---------- Админы отделов ----------
class DeptView(StaffView):
    def __init__(self):
        super().__init__("dept")
        self.users, self.games = [], []

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Кого? Начни печатать ник для поиска", min_values=1, max_values=10)
    async def pick_users(self, interaction: discord.Interaction, select):
        self.users = select.values
        await interaction.response.defer()

    @discord.ui.select(placeholder="🎮 Какой отдел?", min_values=1, max_values=len(config.GAMES),
                       options=[discord.SelectOption(label=g["name"], emoji=g["emoji"]) for g in config.GAMES])
    async def pick_games(self, interaction: discord.Interaction, select):
        self.games = select.values
        await interaction.response.defer()

    async def _apply(self, interaction: discord.Interaction, add: bool):
        if not self.users or not self.games:
            return await interaction.response.send_message("Выбери людей и отдел 👆", ephemeral=True)
        g = interaction.guild
        roles = [r for name in self.games if (r := discord.utils.get(g.roles, name=config.admin_role_name(name)))]
        if not roles:
            return await interaction.response.send_message("Роли админов не найдены — запусти /setup", ephemeral=True)
        if problems := [p for r in roles if (p := role_problem(interaction.user, r))]:
            return await interaction.response.send_message("⚠️ " + "\n".join(problems), ephemeral=True)
        await interaction.response.defer()
        members = [m for u in self.users if (m := as_member(g, u))]
        for m in members:
            if add:
                await m.add_roles(*roles, reason=f"Админ отдела: {interaction.user}")
            else:
                await m.remove_roles(*roles, reason=f"Снят с отдела: {interaction.user}")
        text = (f"{'🛡️ Назначены' if add else '🚫 Сняты'}: {', '.join(m.mention for m in members)} — "
                f"{', '.join(r.mention for r in roles)}")
        await self.finish(interaction, text)
        await log_action(g, f"{interaction.user.mention}: {text}")

    @discord.ui.button(label="Назначить", emoji="🛡️", style=discord.ButtonStyle.success)
    async def assign(self, interaction: discord.Interaction, _):
        await self._apply(interaction, True)

    @discord.ui.button(label="Снять", emoji="🚫", style=discord.ButtonStyle.danger)
    async def unassign(self, interaction: discord.Interaction, _):
        await self._apply(interaction, False)


# ---------- Модерация (общее меню из punish.py) ----------
DURATIONS = [("10 минут", 600), ("1 час", 3600), ("6 часов", 21600), ("1 день", 86400),
             ("7 дней", 604800), ("28 дней", 2419200), ("Снять тайм-аут", 0)]


PUNISH_HINT = ("Выбери человека, причину из правил (или «Другое») и нажми кнопку внизу.\n"
               "Нарушитель получит в ЛС, за что наказан, всё попадёт в историю и #📋・логи.")


def admin_flow(action: str) -> punish.PunishFlow:
    async def allowed(interaction: discord.Interaction) -> bool:
        return not await perms.deny(interaction, action)

    async def check(interaction: discord.Interaction, target: discord.Member):
        return target_problem(interaction.user, target)

    return punish.PunishFlow(action, allowed, check, DURATIONS)


class HistoryView(StaffView):
    def __init__(self):
        super().__init__("history")

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Чью историю показать? Начни печатать ник")
    async def pick_user(self, interaction: discord.Interaction, select):
        await interaction.response.send_message(embed=await punish.history_embed(interaction.guild, select.values[0]),
                                                ephemeral=True)

# ---------- Объявление ----------
class AnnounceModal(discord.ui.Modal, title="📢 Объявление"):
    head = discord.ui.TextInput(label="Заголовок", max_length=200)
    body = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph, max_length=3500)
    ping = discord.ui.TextInput(label="Пинговать @everyone? (да/нет)", default="нет", max_length=3)

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=self.head.value, description=self.body.value, colour=discord.Colour.blurple(),
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"Администрация • {interaction.user.display_name}")
        ping = self.ping.value.strip().lower() in ("да", "yes", "+", "д")
        await self.channel.send(content="@everyone" if ping else None, embed=embed,
                                allowed_mentions=discord.AllowedMentions(everyone=ping))
        await interaction.response.send_message(f"✅ Отправлено в {self.channel.mention}", ephemeral=True)
        await log_action(interaction.guild, f"📢 {interaction.user.mention} — объявление в {self.channel.mention}: "
                                            f"**{self.head.value}**")


class AnnounceView(StaffView):
    def __init__(self):
        super().__init__("announce")
        self.channel = None

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="# В какой канал?",
                       channel_types=[discord.ChannelType.text, discord.ChannelType.news])
    async def pick_channel(self, interaction: discord.Interaction, select):
        self.channel = select.values[0].resolve() or interaction.guild.get_channel(select.values[0].id)
        await interaction.response.defer()

    @discord.ui.button(label="✍️ Написать", style=discord.ButtonStyle.primary)
    async def write(self, interaction: discord.Interaction, _):
        if not self.channel:
            return await interaction.response.send_message("Выбери канал 👆", ephemeral=True)
        await interaction.response.send_modal(AnnounceModal(self.channel))


# ---------- ДР участнику ----------
class BirthdayForModal(discord.ui.Modal):
    day = discord.ui.TextInput(label="День (1-31)", max_length=2)
    month = discord.ui.TextInput(label="Месяц (1-12)", max_length=2)
    year = discord.ui.TextInput(label="Год рождения", min_length=4, max_length=4)

    def __init__(self, member: discord.Member):
        super().__init__(title=f"🎂 ДР: {member.display_name}"[:45])
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            d, m = int(self.day.value), int(self.month.value)
            y = int(self.year.value)
        except ValueError:
            return await interaction.response.send_message("Только цифры 🙂", ephemeral=True)
        if err := validate(d, m, y):
            return await interaction.response.send_message(err, ephemeral=True)
        await save_birthday(interaction.guild.id, self.member.id, d, m, y)
        member = self.member
        status = await finish_if_complete(member)
        from cogs.adult_channels import sync_member
        await sync_member(await interaction.guild.fetch_member(member.id))
        await interaction.response.send_message(f"✅ {member.mention}: {d} {MONTHS[m]}{status}", ephemeral=True)
        await log_action(interaction.guild, f"🎂 {interaction.user.mention} указал ДР {member.mention}: {d} {MONTHS[m]}")


class BirthdayForView(StaffView):
    def __init__(self):
        super().__init__("bday")

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Кому указать ДР? Начни печатать ник")
    async def pick_user(self, interaction: discord.Interaction, select):
        member = as_member(interaction.guild, select.values[0])
        await interaction.response.send_modal(BirthdayForModal(member))


# ---------- Статистика ----------
async def stats_embed(guild: discord.Guild) -> discord.Embed:
    humans = [m for m in guild.members if not m.bot]

    def count(name):
        role = discord.utils.get(guild.roles, name=name)
        return len([m for m in role.members if not m.bot]) if role else 0

    (bdays,) = await db.fetchone("SELECT COUNT(*) FROM birthdays WHERE guild_id=?", (guild.id,))
    (msgs,) = await db.fetchone("SELECT COALESCE(SUM(messages),0) FROM levels WHERE guild_id=?", (guild.id,))
    top = await db.fetchall("SELECT user_id, messages FROM levels WHERE guild_id=? ORDER BY messages DESC LIMIT 3",
                            (guild.id,))
    timeouts = len([m for m in humans if m.is_timed_out()])

    e = discord.Embed(title=f"📊 Статистика: {guild.name}", colour=COLOUR)
    e.add_field(name="👥 Люди", value=f"Всего: **{len(humans)}**\nБотов: {guild.member_count - len(humans)}")
    no_gender = len([m for m in humans if not any(r.name in {n for n, *_ in config.GENDERS} for r in m.roles)])
    e.add_field(name="🚪 Анкета", value=f"Указали ДР: **{bdays}**\nБез пола: {no_gender}")
    e.add_field(name="🚻 Пол", value="\n".join(f"{label} ({n}): {count(n)}" for n, _, label in config.GENDERS))
    e.add_field(name="🎮 Игры", value="\n".join(f"{g['emoji']} {g['name']}: {count(g['role'])}" for g in config.GAMES))
    e.add_field(name="💬 Сообщений", value=f"**{msgs}**\nВ тайм-ауте: {timeouts}")
    e.add_field(name="🏆 Топ", value="\n".join(f"<@{u}> — {c}" for u, c in top) or "—")
    return e


# ---------- Доступ: кто чем может пользоваться ----------
def access_overview(guild: discord.Guild, current: dict[str, list[int]]) -> str:
    lines = []
    for key in perms.FEATURES:
        roles = [guild.get_role(r) for r in current.get(key, [])]
        roles = [r.mention for r in roles if r]
        lines.append(f"{perms.label(key)} — {', '.join(roles) if roles else '*' + perms.default_text(key) + '*'}")
    return "\n".join(lines)


async def load_access(guild: discord.Guild) -> dict[str, list[int]]:
    return {key: await perms.get_roles(guild.id, key) for key in perms.FEATURES}


ADMIN_ONLY = "⛔ Доступ настраивают только админы с правом «Администратор»"


class AccessView(discord.ui.View):
    """Только для владельца и тех, у кого право «Администратор»."""

    def __init__(self, feature: str | None = None, current_roles=()):
        super().__init__(timeout=600)
        self.feature = feature
        self.roles = list(current_roles)
        for opt in self.pick_feature.options:
            opt.default = opt.value == feature
        if feature is None:
            self.remove_item(self.pick_roles)
            self.remove_item(self.save)
            self.remove_item(self.reset)
        else:
            self.pick_roles.default_values = list(current_roles)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(ADMIN_ONLY, ephemeral=True)
        return False

    @discord.ui.select(placeholder="⚙️ Какую функцию настроить?", row=0,
                       options=[discord.SelectOption(label=name, emoji=emoji, value=key)
                                for key, (name, emoji, *_) in perms.FEATURES.items()])
    async def pick_feature(self, interaction: discord.Interaction, select):
        key = select.values[0]
        roles = [r for rid in await perms.get_roles(interaction.guild.id, key) if (r := interaction.guild.get_role(rid))]
        embed = hint(f"🔐 {perms.label(key)}",
                     "Выбери роли, которым **можно** этим пользоваться, и нажми **Сохранить**.\n"
                     f"Если ролей нет — можно: *{perms.default_text(key)}*.\n"
                     "Админы с правом «Администратор» могут всё всегда.")
        await interaction.response.edit_message(embed=embed, view=AccessView(key, roles))

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🎭 Каким ролям разрешить?",
                       min_values=0, max_values=15, row=1)
    async def pick_roles(self, interaction: discord.Interaction, select):
        self.roles = list(select.values)
        await interaction.response.defer()

    async def _store(self, interaction: discord.Interaction, roles):
        g = interaction.guild
        await perms.set_roles(g.id, self.feature, [r.id for r in roles])
        await perms.sync_panel_access(g)
        who = ", ".join(r.mention for r in roles) or f"*{perms.default_text(self.feature)}* (по умолчанию)"
        await log_action(g, f"🔐 {interaction.user.mention}: **{perms.label(self.feature)}** → {who}")
        embed = hint("🔐 Доступ к функциям", f"✅ Сохранено: **{perms.label(self.feature)}** → {who}\n\n"
                                            + access_overview(g, await load_access(g)))
        await interaction.edit_original_response(embed=embed, view=AccessView())

    @discord.ui.button(label="Сохранить", emoji="💾", style=discord.ButtonStyle.success, row=2)
    async def save(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await self._store(interaction, self.roles)

    @discord.ui.button(label="По умолчанию", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def reset(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await self._store(interaction, [])


ROLE_HINT = ("**1.** В первом меню выбери людей. Discord показывает не всех — **начни печатать ник**, "
             "и нужный человек найдётся.\n"
             "**2.** Ниже отметь роли. Под каждой написано, **кому её выдавать**. "
             "🤖 — роль выдаёт бот сам, вручную лучше не трогать.\n"
             "**3.** Нажми **{verb}**.")


# ---------- Главная панель ----------
class AdminPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def open(self, interaction: discord.Interaction, feature: str, embed: discord.Embed, view: discord.ui.View):
        if await perms.deny(interaction, feature):
            return
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Выдать роль", emoji="🎭", style=discord.ButtonStyle.success, custom_id="adm:role_add", row=0)
    async def role_add(self, interaction, _):
        await self.open(interaction, "roles", hint("🎭 Выдать роль", ROLE_HINT.format(verb="Выдать")),
                        RoleView(True, interaction.user))

    @discord.ui.button(label="Забрать роль", emoji="➖", style=discord.ButtonStyle.secondary, custom_id="adm:role_rm", row=0)
    async def role_remove(self, interaction, _):
        await self.open(interaction, "roles", hint("➖ Забрать роль", ROLE_HINT.format(verb="Забрать")),
                        RoleView(False, interaction.user))

    @discord.ui.button(label="mini Admin отделов", emoji="🛡️", style=discord.ButtonStyle.primary, custom_id="adm:dept", row=0)
    async def dept(self, interaction, _):
        lines = []
        for g in config.GAMES:
            role = discord.utils.get(interaction.guild.roles, name=config.admin_role_name(g["name"]))
            people = ", ".join(m.mention for m in role.members) if role and role.members else "—"
            lines.append(f"{g['emoji']} **{g['name']}**: {people}")
        await self.open(interaction, "dept", hint("🛡️ mini Admin отделов",
                                                  "Сейчас:\n" + "\n".join(lines) +
                                                  "\n\nmini Admin управляет **только** своим отделом — у него своя панель в #🧩・mini-панель."),
                        DeptView())

    @discord.ui.button(label="Предупреждение", emoji="⚠️", style=discord.ButtonStyle.secondary, custom_id="adm:warn", row=1)
    async def warn_btn(self, interaction, _):
        await self.open(interaction, "warn", hint("⚠️ Предупреждение", PUNISH_HINT +
                                                  f"\nКаждое {punish.WARN_LIMIT}-е предупреждение — авто-тайм-аут на 1 день."),
                        admin_flow("warn"))

    @discord.ui.button(label="Тайм-аут", emoji="⏳", style=discord.ButtonStyle.secondary, custom_id="adm:timeout", row=1)
    async def timeout_btn(self, interaction, _):
        await self.open(interaction, "timeout", hint("⏳ Тайм-аут", "Человек не сможет писать и говорить.\n" + PUNISH_HINT),
                        admin_flow("timeout"))

    @discord.ui.button(label="Кик", emoji="👢", style=discord.ButtonStyle.secondary, custom_id="adm:kick", row=1)
    async def kick_btn(self, interaction, _):
        await self.open(interaction, "kick", hint("👢 Кик", "Выгнать с сервера (сможет зайти снова).\n" + PUNISH_HINT),
                        admin_flow("kick"))

    @discord.ui.button(label="Бан", emoji="🔨", style=discord.ButtonStyle.danger, custom_id="adm:ban", row=1)
    async def ban_btn(self, interaction, _):
        await self.open(interaction, "ban", hint("🔨 Бан", "Навсегда закрыть доступ к серверу.\n" + PUNISH_HINT),
                        admin_flow("ban"))

    @discord.ui.button(label="История нарушений", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="adm:history", row=3)
    async def history_btn(self, interaction, _):
        await self.open(interaction, "history", hint("📋 История нарушений", "Выбери человека — покажу все его наказания."),
                        HistoryView())

    @discord.ui.button(label="Объявление", emoji="📢", style=discord.ButtonStyle.primary, custom_id="adm:announce", row=2)
    async def announce(self, interaction, _):
        await self.open(interaction, "announce", hint("📢 Объявление", "Выбери канал и нажми **Написать**."),
                        AnnounceView())

    @discord.ui.button(label="ДР участнику", emoji="🎂", style=discord.ButtonStyle.secondary, custom_id="adm:bday", row=2)
    async def bday(self, interaction, _):
        await self.open(interaction, "bday", hint("🎂 День рождения",
                                                  "Выбери человека — откроется окно с датой.\n"
                                                  "Если у него уже выбран пол, сервер откроется."),
                        BirthdayForView())

    @discord.ui.button(label="Статистика", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="adm:stats", row=2)
    async def stats(self, interaction, _):
        if await perms.deny(interaction, "stats"):
            return
        await interaction.response.send_message(embed=await stats_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="Обновить панели", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="adm:panels", row=3)
    async def refresh(self, interaction, _):
        if await perms.deny(interaction, "panels"):
            return
        from cogs.mini_panel import post_mini_panel
        from cogs.onboarding import post_panels
        g = interaction.guild
        welcome = discord.utils.get(g.text_channels, name=config.CH_WELCOME)
        mini = discord.utils.get(g.text_channels, name=config.CH_MINI_PANEL)
        if not welcome:
            return await interaction.response.send_message("Каналов нет — запусти /setup", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await post_panels(self.bot, welcome)
        if mini:
            await post_mini_panel(self.bot, mini)
        await interaction.followup.send(f"✅ Панели в {welcome.mention}" + (f" и {mini.mention}" if mini else "")
                                        + " обновлены", ephemeral=True)

    @discord.ui.button(label="Доступ", emoji="🔐", style=discord.ButtonStyle.danger, custom_id="adm:access", row=3)
    async def access(self, interaction, _):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(ADMIN_ONLY, ephemeral=True)
        embed = hint("🔐 Доступ к функциям", "Выбери функцию в меню и укажи, каким ролям она разрешена.\n\n"
                                            + access_overview(interaction.guild, await load_access(interaction.guild)))
        await interaction.response.send_message(embed=embed, view=AccessView(), ephemeral=True)


async def post_admin_panel(bot: commands.Bot, channel: discord.TextChannel):
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    # Справочник: кому какую роль (сверху вниз, как в настройках сервера)
    ordered = [r.name for r in sorted(channel.guild.roles, key=lambda r: -r.position)
               if not r.managed and not r.is_default()]
    manual = [n for n in ordered if role_info.info(n) and not role_info.info(n).startswith(role_info.AUTO)]
    auto = [n for n in ordered if role_info.info(n).startswith(role_info.AUTO)]
    guide = discord.Embed(title="📖 Кому какую роль выдавать", colour=COLOUR,
                          description=role_info.guide_text(manual)[:4000])
    guide.add_field(name="🤖 Выдаёт бот сам — вручную не трогать",
                    value=", ".join(auto)[:1024] or "—", inline=False)
    await channel.send(embed=guide)
    embed = discord.Embed(
        title="🛠️ Панель администрации",
        description=(
            "Нажми кнопку — откроется меню, которое видишь **только ты**.\n\n"
            "🎭 **Выдать / ➖ Забрать роль** — сразу нескольким людям\n"
            "🛡️ **mini Admin отделов** — назначить, кто управляет отделом каждой игры\n"
            "⚠️ **Предупреждение** · ⏳ **Тайм-аут** · 👢 **Кик** · 🔨 **Бан** — причина выбирается из правил, "
            "нарушитель получает ЛС\n"
            "📋 **История нарушений** — все наказания человека\n"
            "📢 **Объявление** — красивый пост в любой канал\n"
            "🎂 **ДР участнику** — указать дату за человека\n"
            "📊 **Статистика** — сколько людей, кто во что играет\n"
            "🔄 **Обновить панели** — переотправить кнопки входа и игр\n"
            "🔐 **Доступ** — кому какие кнопки и функции разрешены\n\n"
            f"Все действия записываются в #{config.CH_ADMIN_LOG}."
        ),
        colour=COLOUR,
    )
    await channel.send(embed=embed, view=AdminPanelView(bot))


class AdminPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(AdminPanelView(bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminPanel(bot))
