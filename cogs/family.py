"""Заявки в семью: #📝・заявка-в-семью (кнопка) → анкета в 3 шага → #💭・request-in-famq
(пинг руководства и HR, тред для обсуждения, ✅/❌ голосование) → Принять (испытательный срок) / Отклонить."""
import json
import time

import discord
from discord.ext import commands

import config
import db

COLOUR = discord.Colour(0xFF6A00)  # ярко-оранжевый, как 🧡
COOLDOWN_DAYS = 7

# Вопросы по шагам (в окно Discord влезает максимум 5). (ключ, вопрос, эмодзи, подсказка, длинный ответ)
STEPS = [
    ("🎭 Персонаж", [
        ("ic_name", "IC Имя Фамилия", "🎭", "Имя и фамилия персонажа", False),
        ("level", "Уровень персонажа", "📈", "Например: 19", False),
        ("surname", "Готовы сменить фамилию в течение 3-х дней?", "✍️", "Да / нет", False),
        ("faction", "Готовы сидеть в одной фракции с фамкой?", "🏛️", "Если нет — почему", True),
        ("style", "Уклон игры: RP, стрельба, контент, фарм…", "🎯", "Например: RP игра", False),
    ]),
    ("👤 О тебе", [
        ("ooc_name", "OOC Имя", "👤", "Как тебя зовут в жизни", False),
        ("ooc_age", "OOC Возраст", "🎂", "Сколько тебе лет", False),
        ("time", "Как часто уделяете время игре? Когда?", "⏰", "Например: каждый день вечером", False),
        ("since", "Как давно играете? Сколько играете?", "📅", "Например: с 2021 года", False),
        ("why", "Почему хотите вступить в семью?", "💭", "Расскажи честно", True),
    ]),
    ("🤝 Семья", [
        ("family", "Как вы понимаете слово «семья»?", "🤝", "Своими словами", True),
    ]),
]
QUESTIONS = [q for _, qs in STEPS for q in qs]
DRAFTS: dict[tuple[int, int], dict] = {}   # незаконченные анкеты: (сервер, человек) -> ответы


def is_reviewer(member: discord.Member) -> bool:
    names = {n for n, *_ in config.FAMILY_ROLES}
    return member.guild_permissions.administrator or any(r.name in names for r in member.roles)


async def dm(user, embed):
    try:
        await user.send(embed=embed)
    except discord.HTTPException:
        pass


def build_embed(member: discord.abc.User, answers: dict, status: str | None = None) -> discord.Embed:
    e = discord.Embed(title=f"🧡 Заявка в семью {config.FAMILY_NAME}", colour=COLOUR,
                      timestamp=discord.utils.utcnow())
    for key, label, emoji, *_ in QUESTIONS:
        e.add_field(name=f"{emoji} {label}", value=(answers.get(key) or "—")[:1024], inline=False)
    e.add_field(name="💬 Ваш дискорд", value=f"{member.mention} · `{member.name}`", inline=False)
    if status:
        e.add_field(name="📌 Статус", value=status, inline=False)
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"by {member.name}")
    return e


class StepModal(discord.ui.Modal):
    def __init__(self, step: int):
        title, questions = STEPS[step]
        super().__init__(title=f"🧡 Заявка {step + 1}/{len(STEPS)} · {title}"[:45])
        self.step, self.inputs = step, {}
        for key, label, _, hint, long in questions:
            field = discord.ui.TextInput(label=label[:45], placeholder=hint, max_length=600,
                                         style=discord.TextStyle.paragraph if long else discord.TextStyle.short)
            self.inputs[key] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        key = (interaction.guild.id, interaction.user.id)
        DRAFTS.setdefault(key, {}).update({k: f.value for k, f in self.inputs.items()})
        if self.step + 1 < len(STEPS):
            nxt = self.step + 1
            view = NextStepView(nxt)
            return await interaction.response.send_message(
                f"✅ Шаг {self.step + 1} из {len(STEPS)} готов. Жми, чтобы продолжить 👇", view=view, ephemeral=True)
        await submit(interaction, DRAFTS.pop(key))


class NextStepView(discord.ui.View):
    def __init__(self, step: int):
        super().__init__(timeout=900)
        self.step = step
        self.next.label = f"Дальше — шаг {step + 1}/{len(STEPS)}: {STEPS[step][0]}"

    @discord.ui.button(label="Дальше", emoji="➡️", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(StepModal(self.step))


async def submit(interaction: discord.Interaction, answers: dict):
    g = interaction.guild
    channel = discord.utils.get(g.text_channels, name=config.CH_FAMILY_REQUESTS)
    if not channel:
        return await interaction.response.send_message("Канал заявок не найден — сообщи HR", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    now = int(time.time())
    await db.execute("INSERT INTO applications (guild_id, user_id, kind, answers, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", (g.id, interaction.user.id, "family",
                                              json.dumps(answers, ensure_ascii=False), now, now))
    (app_id,) = await db.fetchone("SELECT last_insert_rowid()")
    pings = " ".join(r.mention for name, _, ping in config.FAMILY_ROLES if ping
                     and (r := discord.utils.get(g.roles, name=name)))
    msg = await channel.send(content=pings or None, embed=build_embed(interaction.user, answers),
                             view=FamilyReviewView(), allowed_mentions=discord.AllowedMentions(roles=True))
    await db.execute("UPDATE applications SET message_id=? WHERE id=?", (msg.id, app_id))
    for emoji in ("✅", "❌"):
        await msg.add_reaction(emoji)
    try:
        await msg.create_thread(name=f"Заявка в семью — {answers.get('ic_name', interaction.user.name)}"[:100])
    except discord.HTTPException:
        pass
    await interaction.followup.send("🧡 Заявка в семью отправлена! HR рассмотрит её и ответит **в личные сообщения**.",
                                    ephemeral=True)


class FamilyApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать заявку в семью", emoji="🧡", style=discord.ButtonStyle.success,
                       custom_id="family:apply")
    async def apply(self, interaction: discord.Interaction, _):
        g, m = interaction.guild, interaction.user
        member_role = discord.utils.get(g.roles, name=config.ROLE_FAMILY_MEMBER)
        if member_role and member_role in m.roles:
            return await interaction.response.send_message("Ты уже в семье 🧡", ephemeral=True)
        if await db.fetchone("SELECT 1 FROM applications WHERE guild_id=? AND user_id=? AND kind='family' "
                             "AND status IN ('new','call')", (g.id, m.id)):
            return await interaction.response.send_message("⏳ Твоя заявка уже на рассмотрении — дождись ответа.",
                                                           ephemeral=True)
        last = await db.fetchone("SELECT updated_at FROM applications WHERE guild_id=? AND user_id=? AND kind='family' "
                                 "AND status='rejected' ORDER BY updated_at DESC LIMIT 1", (g.id, m.id))
        if last and time.time() - last[0] < COOLDOWN_DAYS * 86400:
            return await interaction.response.send_message(
                f"❌ Прошлую заявку отклонили. Новую можно подать <t:{last[0] + COOLDOWN_DAYS * 86400}:R>.",
                ephemeral=True)
        DRAFTS.pop((g.id, m.id), None)
        await interaction.response.send_modal(StepModal(0))


class RejectModal(discord.ui.Modal, title="❌ Причина отказа"):
    reason = discord.ui.TextInput(label="Почему отказ? (придёт заявителю)", style=discord.TextStyle.paragraph,
                                  max_length=500)

    def __init__(self, message: discord.Message):
        super().__init__()
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        await decide(interaction, self.message, False, self.reason.value)


async def decide(interaction: discord.Interaction, message: discord.Message, accepted: bool, reason: str = ""):
    row = await db.fetchone("SELECT id, user_id, answers FROM applications WHERE message_id=?", (message.id,))
    if not row:
        return await interaction.response.send_message("Заявка не найдена в базе", ephemeral=True)
    app_id, user_id, answers = row
    g = interaction.guild
    member = g.get_member(user_id)
    await interaction.response.defer(ephemeral=True, thinking=True)
    if accepted:
        role = discord.utils.get(g.roles, name=config.ROLE_FAMILY_PROBATION)
        if member and role:
            await member.add_roles(role, reason=f"Заявка в семью принята: {interaction.user}")
        probation = discord.utils.get(g.text_channels, name=config.CH_FAMILY_PROBATION)
        status = f"✅ Принят на испытательный срок ({config.FAMILY_PROBATION_DAYS} дн.) · {interaction.user.mention}"
        if member:
            await dm(member, discord.Embed(
                title=f"🧡 Добро пожаловать в семью {config.FAMILY_NAME}!",
                description=f"Твоя заявка одобрена — ты на **испытательном сроке {config.FAMILY_PROBATION_DAYS} дн.** — загляни в "
                            f"{probation.mention if probation else 'канал probation'} на сервере **{g.name}**.\n"
                            "Не забудь сменить фамилию в течение 3-х дней!", colour=COLOUR))
    else:
        status = f"❌ Отклонён · {interaction.user.mention}\nПричина: {reason}"
        if member:
            await dm(member, discord.Embed(title=f"❌ Заявка в семью {config.FAMILY_NAME} отклонена",
                                           description=f"**Причина:** {reason}\n\nНовую заявку можно подать "
                                                       f"через {COOLDOWN_DAYS} дн.", colour=discord.Colour.red()))
    await db.execute("UPDATE applications SET status=?, reviewer_id=?, updated_at=? WHERE id=?",
                     ("accepted" if accepted else "rejected", interaction.user.id, int(time.time()), app_id))
    user = member or await interaction.client.fetch_user(user_id)
    embed = build_embed(user, json.loads(answers), status)
    embed.colour = discord.Colour.green() if accepted else discord.Colour.red()
    await message.edit(embed=embed, view=None)
    await interaction.followup.send(status + (f"\nЧерез {config.FAMILY_PROBATION_DAYS} дн., после испытательного срока, выдай роль "
                                              f"«{config.ROLE_FAMILY_MEMBER}»." if accepted else ""), ephemeral=True)


class FamilyReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_reviewer(interaction.user):
            return True
        await interaction.response.send_message("⛔ Заявки в семью рассматривают руководство и HR", ephemeral=True)
        return False

    @discord.ui.button(label="Принять", emoji="✅", style=discord.ButtonStyle.success, custom_id="family:accept")
    async def accept(self, interaction, _):
        await decide(interaction, interaction.message, True)

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="family:reject")
    async def reject(self, interaction, _):
        await interaction.response.send_modal(RejectModal(interaction.message))


async def post_family_panel(bot: commands.Bot, channel: discord.TextChannel):
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    embed = discord.Embed(
        title=f"🧡 Заявка в семью {config.FAMILY_NAME}",
        description=(
            f"Хочешь в семью **{config.FAMILY_NAME}**{(' на ' + config.FAMILY_GAME) if config.FAMILY_GAME else ''}? Заполни анкету — 3 коротких шага.\n\n"
            "🎭 **Персонаж** — имя, уровень, готовность сменить фамилию\n"
            "👤 **О тебе** — возраст, сколько играешь, почему к нам\n"
            "🤝 **Семья** — что для тебя значит это слово\n\n"
            "Заявку рассмотрят основатель, заместители и HR. Ответ придёт **в личные сообщения**.\n"
            f"После одобрения — **испытательный срок {config.FAMILY_PROBATION_DAYS} дн.**, и не забудь сменить фамилию в течение 3-х дней."
        ),
        colour=COLOUR,
    )
    await channel.send(embed=embed, view=FamilyApplyView())


class Family(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(FamilyApplyView())
        bot.add_view(FamilyReviewView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Family(bot))
