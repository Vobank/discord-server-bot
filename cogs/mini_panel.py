"""Панель mini Admin в #🧩・mini-панель: каждый mini Admin управляет ТОЛЬКО своим отделом —
роли отдела, предупреждения и тайм-ауты его участникам, голосовые, медленный режим,
закрытие каналов и объявления в каналах отдела."""
import discord
from discord.ext import commands

import config
import punish
from cogs.admin_panel import AnnounceModal, as_member, hint, log_action, role_problem

MINI_COLOUR = discord.Colour(0x6B5BFF)
NO_DEPT = "⛔ Эта панель для mini Admin отделов. Тебе пока не назначен ни один отдел."
MINI_DURATIONS = [("10 минут", 600), ("1 час", 3600), ("6 часов", 21600), ("1 день", 86400), ("Снять тайм-аут", 0)]
SLOWMODES = [("Выключить", 0), ("5 секунд", 5), ("15 секунд", 15), ("30 секунд", 30), ("1 минута", 60),
             ("5 минут", 300), ("15 минут", 900)]


def my_depts(member: discord.Member) -> list[dict]:
    """Отделы, которыми управляет человек. Администрация и админы — всеми."""
    names = {r.name for r in member.roles}
    if member.guild_permissions.administrator or names & config.STAFF_ROLES:
        return list(config.GAMES)
    return [g for g in config.GAMES if config.admin_role_name(g["name"]) in names]


def dept_category(guild: discord.Guild, game: dict) -> discord.CategoryChannel | None:
    if "category_id" in game:
        return guild.get_channel(game["category_id"])
    return discord.utils.get(guild.categories, name=game["category"])


def dept_role_objs(guild: discord.Guild, game: dict) -> list[discord.Role]:
    return [r for name in config.dept_roles(game) if (r := discord.utils.get(guild.roles, name=name))]


def is_protected(member: discord.Member) -> bool:
    """Администрацию и других mini Admin mini Admin трогать не может."""
    if member.guild_permissions.administrator or member == member.guild.owner:
        return True
    return any(r.name in config.MOD_ROLES or r.name.startswith(config.MINI_PREFIX.strip()) for r in member.roles)


def tag(game: dict) -> str:
    return f"{game['emoji']} {game['name']}"


def target_problem(interaction: discord.Interaction, game: dict, t: discord.Member) -> str | None:
    if not set(dept_role_objs(interaction.guild, game)).intersection(t.roles):
        return f"{t.mention} не участник отдела {tag(game)} — его наказывает Администрация"
    if t == interaction.user or is_protected(t):
        return "Этого человека трогать нельзя"
    if t.top_role >= interaction.guild.me.top_role:
        return "Участник выше бота по ролям"
    return None


async def show(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View, edit: bool):
    if edit:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def choose_dept(interaction: discord.Interaction, then):
    """Один отдел — сразу открываем меню; несколько — сначала спрашиваем какой."""
    depts = my_depts(interaction.user)
    if not depts:
        return await interaction.response.send_message(NO_DEPT, ephemeral=True)
    if len(depts) == 1:
        return await then(interaction, depts[0], False)

    select = discord.ui.Select(placeholder="🧩 Выбери отдел",
                               options=[discord.SelectOption(label=g["name"], emoji=g["emoji"]) for g in depts])

    async def picked(i: discord.Interaction):
        await then(i, config.GAME_BY_NAME[select.values[0]], True)

    select.callback = picked
    view = discord.ui.View(timeout=300)
    view.add_item(select)
    await interaction.response.send_message(embed=hint("🧩 Какой отдел?", "У тебя несколько отделов — выбери нужный."),
                                            view=view, ephemeral=True)


class DeptView(discord.ui.View):
    """Меню одного отдела: пользоваться может только его mini Admin."""

    def __init__(self, game: dict):
        super().__init__(timeout=600)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await dept_allowed(interaction, self.game)


async def dept_allowed(interaction: discord.Interaction, game: dict) -> bool:
    if game in my_depts(interaction.user):
        return True
    await interaction.response.send_message(f"⛔ Ты не mini Admin отдела {game['name']}", ephemeral=True)
    return False


# ---------- Роли отдела ----------
class DeptRoleView(DeptView):
    def __init__(self, game: dict, guild: discord.Guild, add: bool):
        super().__init__(game)
        self.add, self.users, self.roles = add, [], []
        roles = dept_role_objs(guild, game)
        self.pick_roles.options = [discord.SelectOption(label=r.name, value=str(r.id),
                                                        description=f"Сейчас у {len(r.members)} чел.") for r in roles]
        self.pick_roles.max_values = max(1, len(roles))
        self.apply.label = "✅ Выдать" if add else "➖ Забрать"
        self.apply.style = discord.ButtonStyle.success if add else discord.ButtonStyle.danger

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Кому? Начни печатать ник для поиска",
                       min_values=1, max_values=10)
    async def pick_users(self, interaction: discord.Interaction, select):
        self.users = select.values
        await interaction.response.defer()

    @discord.ui.select(placeholder="🎭 Какие роли отдела?", options=[discord.SelectOption(label="-")])
    async def pick_roles(self, interaction: discord.Interaction, select):
        self.roles = [r for rid in select.values if (r := interaction.guild.get_role(int(rid)))]
        await interaction.response.defer()

    @discord.ui.button(label="Применить")
    async def apply(self, interaction: discord.Interaction, _):
        if not self.users or not self.roles:
            return await interaction.response.send_message("Выбери людей и роли 👆", ephemeral=True)
        if problems := [p for r in self.roles if (p := role_problem(interaction.user, r, check_actor=False))]:
            return await interaction.response.send_message("⚠️ " + "\n".join(problems), ephemeral=True)
        await interaction.response.defer()
        g = interaction.guild
        members = [m for u in self.users if (m := as_member(g, u))]
        for m in members:
            if self.add:
                await m.add_roles(*self.roles, reason=f"mini Admin {interaction.user}")
            else:
                await m.remove_roles(*self.roles, reason=f"mini Admin {interaction.user}")
        roles = ", ".join(r.mention for r in self.roles)
        people = ", ".join(m.mention for m in members)
        await interaction.edit_original_response(content=f"✅ Готово: {roles} → {people}", embed=None, view=None)
        await log_action(g, f"[{tag(self.game)}] {interaction.user.mention} {'выдал' if self.add else 'забрал'} "
                            f"{roles} — {people}")


# ---------- Наказания в отделе (меню из punish.py) ----------
def dept_flow(game: dict, action: str) -> punish.PunishFlow:
    async def allowed(interaction):
        return await dept_allowed(interaction, game)

    async def check(interaction, target):
        return target_problem(interaction, game, target)

    return punish.PunishFlow(action, allowed, check, MINI_DURATIONS, dept=tag(game))


class VoiceKickView(DeptView):
    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Кого выгнать из голосового?")
    async def pick_user(self, interaction: discord.Interaction, select):
        t = as_member(interaction.guild, select.values[0])
        cat = dept_category(interaction.guild, self.game)
        if not t or not t.voice or not t.voice.channel or t.voice.channel.category != cat:
            return await interaction.response.send_message(
                f"⚠️ {t.mention if t else 'Он'} не сидит в голосовом канале отдела {tag(self.game)}", ephemeral=True)
        if t == interaction.user or is_protected(t):
            return await interaction.response.send_message("⚠️ Этого человека трогать нельзя", ephemeral=True)
        channel = t.voice.channel
        await t.move_to(None, reason=f"mini Admin {interaction.user}")
        await interaction.response.send_message(f"🔇 {t.mention} выгнан из {channel.mention}", ephemeral=True)
        await log_action(interaction.guild, f"[{tag(self.game)}] {interaction.user.mention} выгнал {t.mention} "
                                            f"из голосового {channel.mention}")


# ---------- Каналы отдела: медленный режим, закрыть/открыть, объявления ----------
def channel_options(guild: discord.Guild, game: dict) -> list[discord.SelectOption]:
    cat = dept_category(guild, game)
    chans = [c for c in (cat.text_channels if cat else []) if c.permissions_for(guild.me).send_messages][:25]
    return [discord.SelectOption(label=c.name[:100], value=str(c.id),
                                 description=("🔐 закрыт · " if is_locked(c, game) else "") +
                                             (f"🐢 {c.slowmode_delay} сек" if c.slowmode_delay else "")[:100] or None)
            for c in chans] or [discord.SelectOption(label="Нет каналов", value="0")]


def is_locked(channel: discord.TextChannel, game: dict) -> bool:
    role = discord.utils.get(channel.guild.roles, name=game["role"])
    return bool(role) and channel.overwrites_for(role).send_messages is False and \
        channel.topic is not None and "🔐" in channel.topic


class DeptChannelView(DeptView):
    LABELS = {"announce": "✍️ Написать", "slow": "🐢 Применить", "lock": "🔐 Закрыть / открыть"}

    def __init__(self, game: dict, guild: discord.Guild, mode: str):
        super().__init__(game)
        self.mode, self.channel, self.slow = mode, None, 30
        self.pick_channel.options = channel_options(guild, game)
        self.go.label = self.LABELS[mode]
        if mode == "slow":
            self.pick_slow.options = [discord.SelectOption(label=n, value=str(s), default=(s == 30)) for n, s in SLOWMODES]
        else:
            self.remove_item(self.pick_slow)

    @discord.ui.select(placeholder="# Какой канал отдела?", options=[discord.SelectOption(label="-")], row=0)
    async def pick_channel(self, interaction: discord.Interaction, select):
        self.channel = interaction.guild.get_channel(int(select.values[0]))
        await interaction.response.defer()

    @discord.ui.select(placeholder="🐢 Задержка между сообщениями", options=[discord.SelectOption(label="-")], row=1)
    async def pick_slow(self, interaction: discord.Interaction, select):
        self.slow = int(select.values[0])
        await interaction.response.defer()

    @discord.ui.button(label="Далее", style=discord.ButtonStyle.primary, row=2)
    async def go(self, interaction: discord.Interaction, _):
        ch = self.channel
        if not ch:
            return await interaction.response.send_message("Выбери канал 👆", ephemeral=True)
        if self.mode == "announce":
            return await interaction.response.send_modal(AnnounceModal(ch))
        if self.mode == "slow":
            await ch.edit(slowmode_delay=self.slow, reason=f"mini Admin {interaction.user}")
            name = next(n for n, s in SLOWMODES if s == self.slow)
            text = f"🐢 {ch.mention}: медленный режим — **{name}**"
        else:
            text = await self.toggle_lock(ch, interaction.user)
        await interaction.response.send_message(text, ephemeral=True)
        await log_action(interaction.guild, f"[{tag(self.game)}] {interaction.user.mention}: {text}")

    async def toggle_lock(self, ch: discord.TextChannel, who: discord.Member) -> str:
        """Закрыть: участники отдела только читают. Открыть: вернуть как было (право снова наследуется)."""
        roles = dept_role_objs(ch.guild, self.game)
        lock = not is_locked(ch, self.game)
        for role in roles:
            ow = ch.overwrites_for(role)
            ow.send_messages = False if lock else None
            await ch.set_permissions(role, overwrite=ow, reason=f"mini Admin {who}")
        topic = (ch.topic or "").replace(" 🔐 Канал временно закрыт", "")
        await ch.edit(topic=(topic + " 🔐 Канал временно закрыт") if lock else (topic or None))
        if lock:
            await ch.send("🔐 Канал временно закрыт администрацией отдела.")
            return f"🔐 {ch.mention} закрыт — участники отдела могут только читать"
        await ch.send("🔓 Канал снова открыт.")
        return f"🔓 {ch.mention} открыт"


# ---------- Открытие меню ----------
async def open_roles(interaction, game, edit, add):
    if not dept_role_objs(interaction.guild, game):
        return await interaction.response.send_message("У отдела нет ролей — запусти /setup", ephemeral=True)
    verb = "Выдать" if add else "Забрать"
    await show(interaction, hint(f"{tag(game)}: {verb.lower()} доступ",
                                 f"Выбери людей и роли отдела, затем **{verb}**.\nРоль отдела открывает его каналы."),
               DeptRoleView(game, interaction.guild, add), edit)


async def open_punish(interaction, game, edit, action):
    emoji, name = punish.ACTIONS[action]
    note = "максимум на 1 день" if action == "timeout" else \
        f"каждое {punish.WARN_LIMIT}-е — авто-тайм-аут на 1 день"
    await show(interaction, hint(f"{tag(game)}: {emoji} {name}",
                                 f"Только участникам твоего отдела, {note}.\n"
                                 "Выбери человека и причину из правил — нарушитель получит ЛС."),
               dept_flow(game, action), edit)


async def open_voice(interaction, game, edit):
    await show(interaction, hint(f"{tag(game)}: 🔇 выгнать из голосового",
                                 "Отключит человека от голосового канала отдела."), VoiceKickView(game), edit)


async def open_channel(interaction, game, edit, mode):
    titles = {"announce": "📢 объявление", "slow": "🐢 медленный режим",
              "lock": "🔐 закрыть / открыть канал"}
    await show(interaction, hint(f"{tag(game)}: {titles[mode]}", "Выбери канал отдела."),
               DeptChannelView(game, interaction.guild, mode), edit)


async def open_stats(interaction, game, edit):
    g = interaction.guild
    roles = dept_role_objs(g, game)
    mini = discord.utils.get(g.roles, name=config.admin_role_name(game["name"]))
    cat = dept_category(g, game)
    e = discord.Embed(title=f"📊 {tag(game)}", colour=MINI_COLOUR)
    for r in roles:
        e.add_field(name=r.name, value=f"**{len(r.members)}** чел.")
    e.add_field(name="mini Admin", value=", ".join(m.mention for m in mini.members) if mini and mini.members else "—",
                inline=False)
    if cat:
        e.add_field(name="Каналов", value=str(len(cat.channels)))
        e.add_field(name="Сейчас в голосовых", value=str(sum(len(v.members) for v in cat.voice_channels)))
    if edit:
        await interaction.response.edit_message(embed=e, view=None)
    else:
        await interaction.response.send_message(embed=e, ephemeral=True)


async def open_history(interaction, game, edit):
    view = DeptView(game)
    select = discord.ui.UserSelect(placeholder="👤 Чью историю показать?")

    async def picked(i: discord.Interaction):
        await i.response.send_message(embed=await punish.history_embed(i.guild, select.values[0]), ephemeral=True)

    select.callback = picked
    view.add_item(select)
    await show(interaction, hint(f"{tag(game)}: 📋 история нарушений", "Выбери человека."), view, edit)


class MiniPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # 1 ряд — доступ
    @discord.ui.button(label="Выдать доступ", emoji="🎭", style=discord.ButtonStyle.success, custom_id="mini:add", row=0)
    async def add(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_roles(i, g, e, True))

    @discord.ui.button(label="Забрать доступ", emoji="➖", style=discord.ButtonStyle.secondary, custom_id="mini:rm", row=0)
    async def remove(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_roles(i, g, e, False))

    @discord.ui.button(label="Мой отдел", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="mini:stats", row=0)
    async def stats(self, interaction, _):
        await choose_dept(interaction, open_stats)

    # 2 ряд — люди
    @discord.ui.button(label="Предупреждение", emoji="⚠️", style=discord.ButtonStyle.secondary, custom_id="mini:warn", row=1)
    async def warn(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_punish(i, g, e, "warn"))

    @discord.ui.button(label="Тайм-аут", emoji="⏳", style=discord.ButtonStyle.danger, custom_id="mini:timeout", row=1)
    async def timeout_btn(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_punish(i, g, e, "timeout"))

    @discord.ui.button(label="Из голосового", emoji="🔇", style=discord.ButtonStyle.secondary, custom_id="mini:vkick", row=1)
    async def voice_kick(self, interaction, _):
        await choose_dept(interaction, open_voice)

    @discord.ui.button(label="История", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="mini:history", row=1)
    async def history(self, interaction, _):
        await choose_dept(interaction, open_history)

    # 3 ряд — каналы
    @discord.ui.button(label="Медленный режим", emoji="🐢", style=discord.ButtonStyle.secondary, custom_id="mini:slow", row=2)
    async def slow(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_channel(i, g, e, "slow"))

    @discord.ui.button(label="Закрыть/открыть", emoji="🔐", style=discord.ButtonStyle.secondary, custom_id="mini:lock", row=2)
    async def lock(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_channel(i, g, e, "lock"))

    @discord.ui.button(label="Объявление", emoji="📢", style=discord.ButtonStyle.primary, custom_id="mini:announce", row=2)
    async def announce(self, interaction, _):
        await choose_dept(interaction, lambda i, g, e: open_channel(i, g, e, "announce"))


async def post_mini_panel(bot: commands.Bot, channel: discord.TextChannel):
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    depts = "\n".join(f"{g['emoji']} **{g['name']}** — роль «{config.admin_role_name(g['name'])}»" for g in config.GAMES)
    embed = discord.Embed(
        title="🧩 Панель mini Admin",
        description=(
            "Здесь mini Admin управляет **только своим отделом**. Чужие отделы недоступны.\n\n"
            "**Доступ**\n"
            "🎭 **Выдать / ➖ Забрать доступ** — роли отдела (открывают его каналы)\n"
            "📊 **Мой отдел** — сколько людей, кто сейчас в голосовых\n\n"
            "**Участники отдела**\n"
            f"⚠️ **Предупреждение** — каждое {punish.WARN_LIMIT}-е даёт авто-тайм-аут на 1 день\n"
            "⏳ **Тайм-аут** — до 1 дня · 🔇 **Из голосового** — отключить от голосового\n"
            "📋 **История** — все наказания человека\n"
            "Причина выбирается из правил, нарушитель получает ЛС.\n\n"
            "**Каналы отдела**\n"
            "🐢 **Медленный режим** · 🔐 **Закрыть/открыть** · 📢 **Объявление**\n\n"
            "Ещё в каналах своего отдела ты можешь удалять отдельные сообщения и закреплять их, управлять ветками, "
            "мутить и перемещать в голосовых, пинговать @everyone (дойдёт только до отдела).\n\n"
            f"**Отделы:**\n{depts}\n\n"
            f"Все действия записываются в #{config.CH_ADMIN_LOG}."
        ),
        colour=MINI_COLOUR,
    )
    await channel.send(embed=embed, view=MiniPanelView())


class MiniPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(MiniPanelView())


async def setup(bot: commands.Bot):
    await bot.add_cog(MiniPanel(bot))
