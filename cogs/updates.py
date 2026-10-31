"""🤖 Обновления: Дворецкий коротко рассказывает в #🤖・обновления, что добавили, что изменили и что в планах.
Пишут высшие админы (право «Администратор») командой /update: окно с тремя разделами → предпросмотр →
«Опубликовать». Под каждым постом кнопки «💡 Предложить улучшение» и «💬 Другое»: написанное видят только
админы — в #📮・предложения (категория админки), там можно ответить человеку в ЛС от имени бота.
Пост можно подготовить и файлом: runtime/update_post.json ({"added": [...], "changed": [...], "planned": [...],
"intro": "…", "number": 1 — если нужен свой номер}) — бот опубликует его сам в течение 20 секунд (так обновления публикует разработчик)."""
import datetime
import json
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import db

log = logging.getLogger(__name__)
COLOUR = discord.Colour.from_rgb(*config.ACCENT)
POST_FILE = os.path.join("runtime", "update_post.json")
SECTIONS = (("added", "✨ Добавили"), ("changed", "🔧 Изменили"), ("planned", "🗓️ В планах"))
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")


def lines(text: str) -> list[str]:
    """Каждая строка — пункт; маркеры «-», «•», «*» в начале убираем."""
    return [s.strip().lstrip("-•*·").strip() for s in (text or "").splitlines() if s.strip().lstrip("-•*·").strip()]


def post_embed(number: int, post: dict) -> discord.Embed:
    now = datetime.datetime.now(config.TIMEZONE)
    e = discord.Embed(title=f"Обновление №{number} · {now.day} {MONTHS[now.month - 1]}",
                      description=(post.get("intro") or "").strip()[:1000] or None, colour=COLOUR)
    for key, name in SECTIONS:
        items = post.get(key) or []
        if items:
            e.add_field(name=name, value="\n".join(f"• {s}" for s in items)[:1024], inline=False)
    e.set_footer(text="Есть идея или что-то не так? Жми кнопку ниже — прочитают админы")
    return e


async def remembered(guild: discord.Guild, key: str, name: str) -> discord.TextChannel | None:
    """Канал по запомненному id (переименование не мешает), иначе по названию — и запоминаем его id."""
    cid = await db.get_setting(guild.id, key)
    channel = guild.get_channel(int(cid)) if cid else None
    channel = channel or discord.utils.get(guild.text_channels, name=name)
    if channel and str(channel.id) != cid:
        await db.set_setting(guild.id, key, str(channel.id))
    return channel


async def updates_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """#обновления в категории «информация»: читают все, пишет только бот."""
    if channel := await remembered(guild, "updates_channel", config.CH_UPDATES):
        return channel
    category = discord.utils.find(lambda c: config.CAT_INFO in c.name, guild.categories)
    over = {guild.default_role: discord.PermissionOverwrite(send_messages=False, create_public_threads=False,
                                                            create_private_threads=False, add_reactions=True),
            guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True, attach_files=True)}
    channel = await guild.create_text_channel(config.CH_UPDATES, category=category, overwrites=over,
                                              topic="Что нового на сервере — пишет Дворецкий",
                                              reason="Канал обновлений")
    await db.set_setting(guild.id, "updates_channel", str(channel.id))
    return channel


async def feedback_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """#📮・предложения в категории админки — видят только админы (права как у категории)."""
    if channel := await remembered(guild, "feedback_channel", config.CH_FEEDBACK):
        return channel
    category = discord.utils.find(lambda c: config.CAT_ADMIN in c.name, guild.categories)
    if not category:
        return None
    channel = await category.create_text_channel(config.CH_FEEDBACK, reason="Предложения из обновлений",
                                                 topic="Предложения и сообщения из #обновления — видят только админы")
    await db.set_setting(guild.id, "feedback_channel", str(channel.id))
    return channel


async def publish(guild: discord.Guild, post: dict) -> discord.Message | None:
    channel = await updates_channel(guild)
    if not channel:
        return None
    number = int(post.get("number") or 0) or int(await db.get_setting(guild.id, "update_counter", "0")) + 1
    msg = await channel.send(embed=post_embed(number, post), view=UpdateButtons())
    await db.set_setting(guild.id, "update_counter", str(number))
    return msg


# ---------- /update: окно → предпросмотр → опубликовать ----------
class UpdateModal(discord.ui.Modal):
    def __init__(self, post: dict | None = None):
        super().__init__(title="🤖 Обновление от Дворецкого")
        post = post or {}
        hint = "Каждый пункт — с новой строки, коротко"
        self.fields = {}
        for key, name in SECTIONS:
            field = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=False, max_length=900,
                                         default="\n".join(post.get(key) or []) or None,
                                         placeholder="Фильмы с ИИ: выбираешь точный вариант\nЗначки достижений")
            self.fields[key] = field
            self.add_item(discord.ui.Label(text=name, description=hint, component=field))
        self.intro = discord.ui.TextInput(required=False, max_length=200, default=post.get("intro") or None,
                                          placeholder="Можно не писать")
        self.add_item(discord.ui.Label(text="Вступление (одна строка)", component=self.intro))

    async def on_submit(self, interaction: discord.Interaction):
        post = {key: lines(field.value) for key, field in self.fields.items()} | {"intro": self.intro.value.strip()}
        if not any(post[key] for key, _ in SECTIONS):
            return await interaction.response.send_message("⚠️ Заполни хотя бы один раздел", ephemeral=True,
                                                           delete_after=15)
        number = int(await db.get_setting(interaction.guild.id, "update_counter", "0")) + 1
        await interaction.response.send_message("**Так будет выглядеть пост** — публиковать?",
                                                embed=post_embed(number, post), view=PreviewView(post), ephemeral=True)


class PreviewView(discord.ui.View):
    def __init__(self, post: dict):
        super().__init__(timeout=900)
        self.post = post

    @discord.ui.button(label="Опубликовать", emoji="📢", style=discord.ButtonStyle.success)
    async def send(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="⏳ Публикую…", embed=None, view=None)
        msg = await publish(interaction.guild, self.post)
        await interaction.edit_original_response(content=f"✅ Опубликовано: {msg.jump_url}" if msg else
                                                 "⚠️ Не получилось создать канал обновлений")

    @discord.ui.button(label="Исправить", emoji="✏️", style=discord.ButtonStyle.primary)
    async def fix(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(UpdateModal(self.post))
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Отмена", emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await interaction.delete_original_response()


# ---------- кнопки под постом: предложение или другое → видят только админы ----------
KINDS = {"idea": ("💡", "Предложение по улучшению", discord.Colour.gold()),
         "other": ("💬", "Сообщение администрации", discord.Colour.blurple())}


class FeedbackModal(discord.ui.Modal):
    def __init__(self, kind: str):
        emoji, name, _ = KINDS[kind]
        super().__init__(title=f"{emoji} {name}")
        self.kind = kind
        self.head = discord.ui.TextInput(max_length=100, placeholder="Коротко, о чём")
        self.add_item(discord.ui.Label(text="Тема", component=self.head))
        self.body = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=1500,
                                         placeholder="Что улучшить и как — или что случилось" if kind == "idea"
                                         else "Ошибка, жалоба, вопрос — что угодно")
        self.add_item(discord.ui.Label(text="Подробнее", description="Это увидят только админы", component=self.body))

    async def on_submit(self, interaction: discord.Interaction):
        g, user = interaction.guild, interaction.user
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = await feedback_channel(g)
        if not channel:
            return await interaction.followup.send("⚠️ Сейчас не получилось отправить — попробуй позже", ephemeral=True)
        await db.execute("INSERT INTO feedback (guild_id, user_id, kind, title, text, created_at) VALUES (?,?,?,?,?,?)",
                         (g.id, user.id, self.kind, self.head.value, self.body.value, int(time.time())))
        (fid,) = await db.fetchone("SELECT last_insert_rowid()")
        msg = await channel.send(embed=feedback_embed(fid, user, self.kind, self.head.value, self.body.value),
                                 view=FeedbackAdminView())
        await db.execute("UPDATE feedback SET message_id=? WHERE id=?", (msg.id, fid))
        await interaction.followup.send("✅ Отправил админам — если они ответят, напишу тебе в ЛС.", ephemeral=True)


def feedback_embed(fid: int, user: discord.abc.User, kind: str, title: str, text: str) -> discord.Embed:
    emoji, name, colour = KINDS[kind]
    e = discord.Embed(title=f"{emoji} {title}", description=text, colour=colour, timestamp=discord.utils.utcnow())
    e.set_author(name=f"{name} №{fid} · {user.display_name}", icon_url=user.display_avatar.url)
    e.add_field(name="От кого", value=user.mention)
    e.add_field(name="Статус", value="🆕 Новое")
    return e


class UpdateButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Предложить улучшение", emoji="💡", style=discord.ButtonStyle.success,
                       custom_id="upd:idea")
    async def idea(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(FeedbackModal("idea"))

    @discord.ui.button(label="Другое", emoji="💬", custom_id="upd:other")
    async def other(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(FeedbackModal("other"))


class ReplyModal(discord.ui.Modal, title="✉️ Ответ в ЛС от Дворецкого"):
    answer = discord.ui.TextInput(label="Ответ", style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, row: tuple, message: discord.Message):
        super().__init__()
        self.row, self.message = row, message

    async def on_submit(self, interaction: discord.Interaction):
        fid, user_id, kind, title = self.row
        await interaction.response.defer(ephemeral=True, thinking=True)
        member = interaction.guild.get_member(user_id)
        sent = False
        if member:
            try:
                await member.send(embed=discord.Embed(
                    title=f"✉️ Ответ на «{title}»", description=self.answer.value, colour=COLOUR)
                    .set_footer(text=f"Сервер {interaction.guild.name} · {KINDS[kind][1].lower()} №{fid}"))
                sent = True
            except discord.HTTPException:
                pass
        await set_status(self.message, f"✉️ Ответили ({interaction.user.display_name})"
                         + ("" if sent else " — ЛС закрыты, не дошло"), answer=self.answer.value)
        await db.execute("UPDATE feedback SET status='answered' WHERE id=?", (fid,))
        await interaction.followup.send("✅ Ответ отправлен в ЛС" if sent else "⚠️ У человека закрыты ЛС — "
                                        "ответ сохранён только здесь", ephemeral=True)


async def set_status(message: discord.Message, status: str, answer: str | None = None):
    e = message.embeds[0]
    e.set_field_at(1, name="Статус", value=status)
    if answer:
        e.add_field(name="Ответ", value=answer[:1024], inline=False)
    await message.edit(embed=e)


class FeedbackAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def row(self, interaction: discord.Interaction):
        return await db.fetchone("SELECT id, user_id, kind, title FROM feedback WHERE message_id=?",
                                 (interaction.message.id,))

    @discord.ui.button(label="Ответить в ЛС", emoji="✉️", style=discord.ButtonStyle.primary, custom_id="fb:reply")
    async def reply(self, interaction: discord.Interaction, _):
        row = await self.row(interaction)
        if not row:
            return await interaction.response.send_message("Не нашёл это сообщение в базе", ephemeral=True,
                                                           delete_after=15)
        await interaction.response.send_modal(ReplyModal(row, interaction.message))

    @discord.ui.button(label="Готово", emoji="✅", style=discord.ButtonStyle.success, custom_id="fb:done")
    async def done(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await set_status(interaction.message, f"✅ Готово ({interaction.user.display_name})")
        await db.execute("UPDATE feedback SET status='done' WHERE message_id=?", (interaction.message.id,))


class Updates(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(UpdateButtons())
        bot.add_view(FeedbackAdminView())
        self.from_file.start()

    def cog_unload(self):
        self.from_file.cancel()

    @app_commands.command(name="update", description="(Высшие админы) Пост об обновлении от имени Дворецкого")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def update(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Это могут только высшие админы", ephemeral=True,
                                                           delete_after=15)
        await interaction.response.send_modal(UpdateModal())

    @tasks.loop(seconds=20)
    async def from_file(self):
        """Готовый пост от разработчика: runtime/update_post.json → публикуем и удаляем файл."""
        if not os.path.exists(POST_FILE):
            return
        try:
            with open(POST_FILE, encoding="utf-8") as f:
                post = json.load(f)
            os.remove(POST_FILE)
        except (OSError, ValueError):
            log.exception("Не прочитался %s", POST_FILE)
            return
        for guild in self.bot.guilds:
            msg = await publish(guild, post)
            log.info("Опубликовано обновление: %s", msg.jump_url if msg else "канала нет")

    @from_file.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                await updates_channel(guild)
                await feedback_channel(guild)
            except discord.HTTPException:
                log.exception("Не создались каналы обновлений")


async def setup(bot: commands.Bot):
    await bot.add_cog(Updates(bot))
