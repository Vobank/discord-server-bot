"""Заявки в состав: #📝・подать-заявку (кнопки) → анкета → #📨・заявки-в-администрацию (видит высший состав)
→ ⏳ на обзвон / ✅ принять (выдаёт роль) / ❌ отклонить. Заявителю всё приходит в ЛС."""
import json
import time

import discord
from discord.ext import commands

import config
import db
import punish

COLOUR = discord.Colour(0x2ECC71)
KINDS = {
    "mod": {"title": "Модератор", "emoji": "🛡️", "role": config.ROLE_MOD},
    "admin": {"title": "Администратор", "emoji": "⚔️", "role": config.ROLE_STAFF},
}
STATUS = {"new": "🆕 Новая — ждёт рассмотрения", "call": "⏳ Вызван на обзвон", "accepted": "✅ Принят",
          "rejected": "❌ Отклонён"}
QUESTIONS = [
    ("reason", "Почему хочешь в состав?", "Причина желания попасть в администрацию"),
    ("goals", "Чего хочешь добиться?", "Цели нахождения на этой должности"),
    ("experience", "Опыт модерации / администрирования", "Где и кем был, что делал (если не было — так и напиши)"),
    ("online", "Сколько времени готов уделять?", "Например: каждый день по 2-3 часа, вечером"),
]


def is_reviewer(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.name in config.APPLY_REVIEWERS for r in member.roles)


async def app_by_message(message_id: int):
    row = await db.fetchone("SELECT id, guild_id, user_id, kind, answers, status FROM applications "
                            "WHERE message_id=?", (message_id,))
    return dict(zip(("id", "guild_id", "user_id", "kind", "answers", "status"), row)) if row else None


async def dm(user: discord.abc.User, embed: discord.Embed):
    try:
        await user.send(embed=embed)
    except discord.HTTPException:
        pass


async def build_embed(guild: discord.Guild, app: dict) -> discord.Embed:
    kind = KINDS[app["kind"]]
    member = guild.get_member(app["user_id"])
    answers = json.loads(app["answers"])
    e = discord.Embed(title=f"{kind['emoji']} Заявка в {kind['title'].lower()}ы · №{app['id']}",
                      colour={"accepted": discord.Colour.green(), "rejected": discord.Colour.red(),
                              "call": discord.Colour.gold()}.get(app["status"], COLOUR))
    if member:
        e.set_thumbnail(url=member.display_avatar.url)
        row = await db.fetchone("SELECT year FROM birthdays WHERE guild_id=? AND user_id=?", (guild.id, member.id))
        age = f"{time.localtime().tm_year - row[0]}" if row and row[0] else "не указан"
        e.add_field(name="👤 Кто", value=f"{member.mention}\n`{member.name}`")
        e.add_field(name="🎭 Текущая роль", value=member.top_role.mention)
        e.add_field(name="📅 На сервере с", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "—")
        e.add_field(name="🎂 Возраст", value=age)
        e.add_field(name="⚠️ Предупреждений", value=str(await punish.count_warns(guild.id, member.id)))
    else:
        e.add_field(name="👤 Кто", value=f"<@{app['user_id']}> (вышел с сервера)")
    for key, label, _ in QUESTIONS:
        e.add_field(name=label, value=answers.get(key, "—")[:1024], inline=False)
    e.add_field(name="Статус", value=STATUS[app["status"]], inline=False)
    return e


# ---------- Подача ----------
class ApplyModal(discord.ui.Modal):
    def __init__(self, kind: str):
        super().__init__(title=f"{KINDS[kind]['emoji']} Заявка: {KINDS[kind]['title']}")
        self.kind = kind
        self.fields = {}
        for key, label, placeholder in QUESTIONS:
            field = discord.ui.TextInput(label=label, placeholder=placeholder, min_length=10, max_length=800,
                                         style=discord.TextStyle.short if key == "online"
                                         else discord.TextStyle.paragraph)
            self.fields[key] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        g = interaction.guild
        review = discord.utils.get(g.text_channels, name=config.CH_APPLY_REVIEW)
        if not review:
            return await interaction.response.send_message("Канал заявок не найден — сообщи администрации",
                                                           ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = {k: f.value for k, f in self.fields.items()}
        now = int(time.time())
        await db.execute("INSERT INTO applications (guild_id, user_id, kind, answers, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?)", (g.id, interaction.user.id, self.kind,
                                                  json.dumps(answers, ensure_ascii=False), now, now))
        (app_id,) = await db.fetchone("SELECT last_insert_rowid()")
        app = {"id": app_id, "guild_id": g.id, "user_id": interaction.user.id, "kind": self.kind,
               "answers": json.dumps(answers, ensure_ascii=False), "status": "new"}
        pings = " ".join(r.mention for r in g.roles if r.name in (config.ROLE_HEAD_ADMIN, config.ROLE_HEAD_MOD))
        msg = await review.send(content=f"📨 Новая заявка! {pings}", embed=await build_embed(g, app),
                                view=ReviewView(), allowed_mentions=discord.AllowedMentions(roles=True))
        await db.execute("UPDATE applications SET message_id=? WHERE id=?", (msg.id, app_id))
        await interaction.followup.send(
            "✅ Заявка отправлена! Её рассмотрит высший состав (обычно до 2 дней).\n"
            "Ответ придёт **в личные сообщения** — не закрывай ЛС от сервера.", ephemeral=True)


class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def start(self, interaction: discord.Interaction, kind: str):
        m = interaction.user
        role = discord.utils.get(interaction.guild.roles, name=KINDS[kind]["role"])
        if role and role in m.roles:
            return await interaction.response.send_message(f"У тебя уже есть роль {role.mention} 🙂", ephemeral=True)
        open_app = await db.fetchone("SELECT id FROM applications WHERE guild_id=? AND user_id=? AND kind IN ('mod','admin') "
                                     "AND status IN ('new','call')", (interaction.guild.id, m.id))
        if open_app:
            return await interaction.response.send_message(
                f"⏳ У тебя уже есть заявка №{open_app[0]} на рассмотрении — дождись ответа.", ephemeral=True)
        last = await db.fetchone("SELECT updated_at FROM applications WHERE guild_id=? AND user_id=? AND kind IN ('mod','admin') "
                                 "AND status='rejected' ORDER BY updated_at DESC LIMIT 1", (interaction.guild.id, m.id))
        wait = config.APPLY_COOLDOWN_DAYS * 86400
        if last and time.time() - last[0] < wait:
            return await interaction.response.send_message(
                f"❌ Прошлую заявку отклонили. Новую можно подать <t:{last[0] + wait}:R>.", ephemeral=True)
        await interaction.response.send_modal(ApplyModal(kind))

    @discord.ui.button(label="Модератор", emoji="🛡️", style=discord.ButtonStyle.success, custom_id="apply:mod")
    async def mod(self, interaction, _):
        await self.start(interaction, "mod")

    @discord.ui.button(label="Администратор", emoji="⚔️", style=discord.ButtonStyle.primary, custom_id="apply:admin")
    async def admin(self, interaction, _):
        await self.start(interaction, "admin")


# ---------- Рассмотрение ----------
class RejectModal(discord.ui.Modal, title="❌ Причина отказа"):
    reason = discord.ui.TextInput(label="Почему отказ? (придёт заявителю)", style=discord.TextStyle.paragraph,
                                  max_length=500)

    def __init__(self, message: discord.Message):
        super().__init__()
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        await finish(interaction, self.message, "rejected", self.reason.value)


async def finish(interaction: discord.Interaction, message: discord.Message, status: str, reason: str = ""):
    app = await app_by_message(message.id)
    if not app:
        return await interaction.response.send_message("Заявка не найдена в базе", ephemeral=True)
    g, kind = interaction.guild, KINDS[app["kind"]]
    member = g.get_member(app["user_id"])
    await interaction.response.defer(ephemeral=True, thinking=True)

    if status == "accepted":
        role = discord.utils.get(g.roles, name=kind["role"])
        if member and role:
            await member.add_roles(role, reason=f"Заявка №{app['id']} принята: {interaction.user}")
        text = f"✅ {member.mention if member else 'Заявитель'} принят — выдана роль **{kind['role']}**"
        if member:
            await dm(member, discord.Embed(title=f"🎉 Тебя приняли: {kind['title']}!",
                                           description=f"Заявка №{app['id']} на сервере **{g.name}** одобрена. "
                                                       f"Тебе выдана роль **{kind['role']}** — добро пожаловать "
                                                       "в состав! Панель найдёшь в админке.",
                                           colour=discord.Colour.green()))
    elif status == "rejected":
        text = f"❌ Заявка отклонена. Причина: {reason}"
        if member:
            await dm(member, discord.Embed(title=f"❌ Заявка №{app['id']} отклонена",
                                           description=f"**Причина:** {reason}\n\nНовую заявку можно подать через "
                                                       f"{config.APPLY_COOLDOWN_DAYS} дн.",
                                           colour=discord.Colour.red()))
    else:  # call
        voice = discord.utils.get(g.voice_channels, name=config.VC_APPLY)
        await message.add_reaction("⏳")
        text = f"⏳ {member.mention if member else 'Заявитель'} вызван на обзвон"
        if member:
            await dm(member, discord.Embed(
                title="⏳ Тебя ждут на обзвон!",
                description=f"Заявка №{app['id']} прошла первый этап. **В течение суток** зайди в "
                            f"{voice.mention if voice else 'канал ожидания обзвона'} на сервере **{g.name}** — "
                            "тебя опросят по правилам сервера.", colour=discord.Colour.gold()))

    await db.execute("UPDATE applications SET status=?, reviewer_id=?, updated_at=? WHERE id=?",
                     (status, interaction.user.id, int(time.time()), app["id"]))
    app["status"] = status
    embed = await build_embed(g, app)
    embed.set_footer(text=f"{STATUS[status]} · {interaction.user.display_name}"
                          + (f" · {reason[:100]}" if reason else ""))
    await message.edit(embed=embed, view=None if status in ("accepted", "rejected") else ReviewView())
    await interaction.followup.send(text, ephemeral=True)
    from cogs.admin_panel import log_action
    await log_action(g, f"📨 Заявка №{app['id']} ({kind['title']}): {text} · {interaction.user.mention}")


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_reviewer(interaction.user):
            return True
        await interaction.response.send_message("⛔ Заявки рассматривает только высший состав", ephemeral=True)
        return False

    @discord.ui.button(label="На обзвон", emoji="⏳", style=discord.ButtonStyle.secondary, custom_id="review:call")
    async def call(self, interaction, _):
        await finish(interaction, interaction.message, "call")

    @discord.ui.button(label="Принять", emoji="✅", style=discord.ButtonStyle.success, custom_id="review:accept")
    async def accept(self, interaction, _):
        await finish(interaction, interaction.message, "accepted")

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="review:reject")
    async def reject(self, interaction, _):
        await interaction.response.send_modal(RejectModal(interaction.message))


async def post_apply_panel(bot: commands.Bot, channel: discord.TextChannel):
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    voice = discord.utils.get(channel.guild.voice_channels, name=config.VC_APPLY)
    embed = discord.Embed(
        title="📝 Вступление в состав сервера",
        description=(
            "Хочешь помогать серверу? Подай заявку — это займёт пару минут.\n\n"
            "🛡️ **Модератор** — следит за порядком в чатах и голосовых: предупреждения и тайм-ауты.\n"
            "⚔️ **Администратор** — помогает управлять сервером: роли, отделы, мероприятия.\n\n"
            "**Как это работает**\n"
            "**1.** Нажми кнопку и заполни анкету честно — все 4 пункта обязательны.\n"
            "**2.** Заявку рассматривает высший состав, срок — до 2 дней. Ответ придёт в ЛС.\n"
            f"**3.** Если позовут на обзвон — в течение суток зайди в {voice.mention if voice else '🎙️・Ожидание обзвона'}. "
            "Будут спрашивать правила — перечитай их заранее.\n\n"
            "*Порядок и ответственность — основа команды.*"
        ),
        colour=COLOUR,
    )
    await channel.send(embed=embed, view=ApplyView())


class Applications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(ApplyView())
        bot.add_view(ReviewView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Applications(bot))
