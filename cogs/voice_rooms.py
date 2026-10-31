"""Личные голосовые: зашёл в «・Создать канал» — бот создал комнату с твоим ником, опустела — удалил.
Каналы-создатели хранятся в таблице voice_creators (их добавляет /setup).
Управление: панель в чате комнаты (раз в 2 минуты бот опускает её вниз) или команды /room.
Кнопки музыки (песня, радио, очередь, подборка) — для всех, кто сидит в комнате, остальное — для хозяина.
Закрытая комната: зайти может любой, но новенький ничего не слышит, молчит и не пишет в чат, пока хозяин
не нажмёт «Пустить» — бот сам спрашивает его в чате комнаты (таблица voice_waiting)."""
import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import db
import perms

NOT_OWNER = "🔊 Зайди в **свою** комнату (через любой «・Создать канал»), чтобы ею управлять."
LOCKED_TEXT = ("🔒 Комната закрыта. Зайти может любой, но новенький ничего не слышит, не говорит и не пишет, "
               "пока ты не пустишь. Когда кто-то зайдёт, я спрошу тебя в чате комнаты.")
MUSIC_BUTTONS = {"room:music", "room:radio", "room:queue", "room:picks"}  # ими пользуются все, кто в комнате
PANEL_EVERY = 2  # минуты: панель снова внизу, если в чате появились сообщения
GONE = 60        # через сколько секунд исчезают ответы бота в комнате
# что закрытая комната запрещает тем, кого ещё не пустили (и разрешает пущенным)
GUEST_PERMS = ("speak", "stream", "send_messages", "read_message_history")


async def owned_room(member: discord.Member) -> discord.VoiceChannel | None:
    voice = member.voice
    if voice and voice.channel:
        row = await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (voice.channel.id,))
        if row and row[0] == member.id:
            return voice.channel
    return None


def is_locked(ch: discord.VoiceChannel) -> bool:
    return ch.overwrites_for(ch.guild.default_role).speak is False


def admitted(ch: discord.VoiceChannel, member: discord.Member) -> bool:
    return ch.overwrites_for(member).speak is True


async def admit(ch: discord.VoiceChannel, member: discord.Member):
    """Пустить в закрытую комнату: слышит, говорит, пишет."""
    ow = ch.overwrites_for(member)
    ow.update(view_channel=True, connect=True, **{perm: True for perm in GUEST_PERMS})
    await ch.set_permissions(member, overwrite=ow)


async def release(member: discord.Member):
    """Снять «ждёт у входа»: вернуть слух и убрать сообщение-вопрос. Не в голосовом — снимем, когда зайдёт."""
    row = await db.fetchone("SELECT channel_id, msg_id FROM voice_waiting WHERE guild_id=? AND user_id=?",
                            (member.guild.id, member.id))
    if not row:
        return
    channel_id, msg_id = row
    room = member.guild.get_channel(channel_id) if channel_id else None
    if room and msg_id:
        try:
            await room.get_partial_message(msg_id).delete()
        except discord.HTTPException:
            pass
    if member.voice and member.voice.channel:
        try:
            await member.edit(deafen=False, reason="Пустили или ушёл из закрытой комнаты")
        except discord.HTTPException:
            pass
        await db.execute("DELETE FROM voice_waiting WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
    else:
        await db.execute("UPDATE voice_waiting SET channel_id=0, msg_id=0 WHERE guild_id=? AND user_id=?",
                         (member.guild.id, member.id))


async def set_locked(ch: discord.VoiceChannel, locked: bool):
    """Закрыто: зайти может любой, но пока хозяин не пустит — ничего не слышит, молчит и не пишет.
    Кто уже сидит в комнате, когда её закрывают, — свои."""
    targets = [t for t in ch.overwrites if isinstance(t, discord.Role)]
    if locked and ch.guild.default_role not in targets:
        targets.append(ch.guild.default_role)
    for target in targets:
        ow = ch.overwrites_for(target)
        if target == ch.guild.default_role and ow.connect is False:
            ow.connect = None  # закрыта по-старому (вход был запрещён) — теперь заходить можно
        for perm in GUEST_PERMS:
            setattr(ow, perm, False if locked else None)
        await ch.set_permissions(target, overwrite=ow if not ow.is_empty() else None)
    if locked:
        for m in [*ch.members, ch.guild.me]:  # бот тоже свой: иначе в закрытой комнате не сможет играть музыку
            if (not m.bot or m == ch.guild.me) and not admitted(ch, m):
                await admit(ch, m)
    else:
        for (user_id,) in await db.fetchall("SELECT user_id FROM voice_waiting WHERE guild_id=? AND channel_id=?",
                                            (ch.guild.id, ch.id)):
            if m := ch.guild.get_member(user_id):
                await release(m)


async def set_hidden(ch: discord.VoiceChannel, hidden: bool):
    """Скрыть комнату из списка каналов (видят только те, кто внутри или кого пустили)."""
    targets = [t for t in ch.overwrites if isinstance(t, discord.Role)]
    if hidden and ch.guild.default_role not in targets:
        targets.append(ch.guild.default_role)
    for target in targets:
        ow = ch.overwrites_for(target)
        ow.view_channel = False if hidden else None
        await ch.set_permissions(target, overwrite=ow)
    for m in ch.members:  # кто уже сидит — продолжает видеть
        if ch.overwrites_for(m).view_channel is not True:
            await ch.set_permissions(m, view_channel=True, connect=True)


async def set_voice(ch: discord.VoiceChannel, member: discord.Member, can_speak: bool):
    """Заглушить/разглушить в ЭТОЙ комнате (в других каналах человек говорит как обычно)."""
    ow = ch.overwrites_for(member)
    ow.speak = (True if is_locked(ch) else None) if can_speak else False  # в закрытой «молчать» — по умолчанию
    await ch.set_permissions(member, overwrite=ow if not ow.is_empty() else None)


async def unblock(ch: discord.VoiceChannel, member: discord.Member):
    ow = ch.overwrites_for(member)
    ow.connect = None
    await ch.set_permissions(member, overwrite=ow if not ow.is_empty() else None)


async def room_info(ch: discord.VoiceChannel) -> discord.Embed:
    row = await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (ch.id,))
    everyone = ch.overwrites_for(ch.guild.default_role)
    locked = is_locked(ch)
    hidden = everyone.view_channel is False
    trusted, blocked, muted = [], [], []
    waiting = [f"<@{uid}>" for (uid,) in await db.fetchall(
        "SELECT user_id FROM voice_waiting WHERE guild_id=? AND channel_id=?", (ch.guild.id, ch.id))]
    for t, ow in ch.overwrites.items():
        if isinstance(t, discord.Member) and (not row or t.id != row[0]):
            if ow.connect is True or (locked and ow.speak is True):
                trusted.append(t.mention)
            if ow.connect is False:
                blocked.append(t.mention)
            if ow.speak is False:
                muted.append(t.mention)
    e = discord.Embed(title=f"ℹ️ {ch.name}", colour=discord.Colour.blurple())
    e.add_field(name="👑 Хозяин", value=f"<@{row[0]}>" if row else "—")
    e.add_field(name="👥 Сейчас / лимит", value=f"{len(ch.members)} / {ch.user_limit or '∞'}")
    e.add_field(name="Статус", value=("🔒 закрыта" if locked else "🔓 открыта") + " · " +
                                    ("👁️ скрыта" if hidden else "👀 видна всем"))
    e.add_field(name="✅ Пущены", value=", ".join(trusted) or "—", inline=False)
    if locked:
        e.add_field(name="🔔 Ждут у входа", value=", ".join(waiting) or "—", inline=False)
    e.add_field(name="⛔ Заблокированы", value=", ".join(blocked) or "—", inline=False)
    e.add_field(name="🔇 Заглушены", value=", ".join(muted) or "—", inline=False)
    return e


async def let_in(ch: discord.VoiceChannel, member: discord.Member):
    await admit(ch, member)
    await release(member)


class KnockView(discord.ui.View):
    """«🔔 Ждёт у входа» в чате закрытой комнаты: хозяин пускает или выгоняет одной кнопкой."""

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        room = await owned_room(interaction.user)
        if room and room.id == interaction.channel_id:
            return True
        await interaction.response.send_message("🔒 Пускать в комнату может только её хозяин", ephemeral=True,
                                                delete_after=GONE)
        return False

    @staticmethod
    async def guest(interaction: discord.Interaction) -> discord.Member | None:
        row = await db.fetchone("SELECT user_id FROM voice_waiting WHERE guild_id=? AND msg_id=?",
                                (interaction.guild.id, interaction.message.id))
        return interaction.guild.get_member(row[0]) if row else None

    async def gone(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Пустить", emoji="✅", style=discord.ButtonStyle.success, custom_id="knock:in")
    async def let(self, interaction: discord.Interaction, _):
        guest = await self.guest(interaction)
        if not guest:
            return await self.gone(interaction)
        await interaction.response.defer()
        await let_in(interaction.channel, guest)
        await interaction.channel.send(f"✅ {guest.mention} в комнате: теперь слышит всех и может говорить",
                                       delete_after=GONE, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="Выгнать", emoji="👢", style=discord.ButtonStyle.danger, custom_id="knock:out")
    async def out(self, interaction: discord.Interaction, _):
        guest = await self.guest(interaction)
        if not guest:
            return await self.gone(interaction)
        await interaction.response.defer()
        await kick_out(interaction.channel, guest)
        await release(guest)


async def kick_out(ch: discord.VoiceChannel, member: discord.Member):
    await ch.set_permissions(member, connect=False)
    if member.voice and member.voice.channel == ch:
        await member.move_to(None)


def rename_for(ch: discord.VoiceChannel, new: discord.Member, old: discord.Member | None = None):
    """Комната называлась по нику хозяина — теперь называется по нику нового. Своё название
    (например «🎮・Катка») не трогаем. В фоне: Discord разрешает переименовать канал лишь 2 раза за 10 минут,
    и при частой передаче переименование подождёт, а кнопки — нет."""
    emoji, sep, name = ch.name.partition("・")
    if not sep:
        emoji, name = "🔊", ch.name
    if old is not None and name != old.display_name and not (len(ch.name) == 100 and old.display_name.startswith(name)):
        return

    async def run():
        try:
            await ch.edit(name=f"{emoji}・{new.display_name}"[:100], reason=f"Комнату передали {new}")
        except discord.HTTPException:
            pass
    asyncio.create_task(run())


async def transfer(ch: discord.VoiceChannel, old: discord.Member, new: discord.Member):
    await db.execute("UPDATE temp_voice SET owner_id=? WHERE channel_id=?", (new.id, ch.id))
    owner_ow = ch.overwrites_for(old)
    await ch.set_permissions(old, overwrite=None)
    await ch.set_permissions(new, overwrite=owner_ow)
    rename_for(ch, new, old)


# ---------- Панель в #🎮・управление ----------
class TextModal(discord.ui.Modal):
    def __init__(self, title: str, label: str, max_length: int, apply):
        super().__init__(title=title)
        self.apply = apply
        self.value = discord.ui.TextInput(label=label, max_length=max_length)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        ch = await owned_room(interaction.user)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True, delete_after=GONE)
        await interaction.response.send_message(await self.apply(ch, self.value.value), ephemeral=True, delete_after=GONE)


class PickMemberView(discord.ui.View):
    def __init__(self, placeholder: str, action):
        super().__init__(timeout=300)
        self.action = action
        self.pick.placeholder = placeholder

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="-")
    async def pick(self, interaction: discord.Interaction, select):
        ch = await owned_room(interaction.user)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True, delete_after=GONE)
        target = select.values[0]
        target = target if isinstance(target, discord.Member) else interaction.guild.get_member(target.id)
        if not target or target == interaction.user:
            return await interaction.response.send_message("Выбери другого человека 🙂", ephemeral=True, delete_after=GONE)
        await interaction.response.edit_message(content=await self.action(ch, interaction.user, target), view=None)
        await asyncio.sleep(GONE)  # убираем, чтобы не копилось
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass


async def rename(ch, value):
    await ch.edit(name=value)
    return f"✏️ Комната теперь называется **{value}**"


async def limit(ch, value):
    try:
        n = max(0, min(99, int(value)))
    except ValueError:
        return "Нужна цифра от 0 до 99"
    await ch.edit(user_limit=n)
    return f"👥 Лимит: **{n or 'без лимита'}**"


class RoomPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = (interaction.data or {}).get("custom_id")
        if custom_id == "room:help":  # помощь — всем
            return True
        if custom_id in MUSIC_BUTTONS:
            voice = interaction.user.voice
            if voice and voice.channel and voice.channel.id == interaction.channel_id:
                return True
            await interaction.response.send_message("🎧 Зайди в эту комнату, чтобы включать музыку",
                                                    ephemeral=True, delete_after=GONE)
            return False
        if custom_id == "room:claim" or await owned_room(interaction.user):
            return True
        await interaction.response.send_message(NOT_OWNER, ephemeral=True, delete_after=GONE)
        return False

    @staticmethod
    def music(interaction: discord.Interaction):
        return interaction.client.get_cog("Music")

    @discord.ui.button(label="Название", emoji="✏️", custom_id="room:name", row=0)
    async def name(self, interaction, _):
        await interaction.response.send_modal(TextModal("✏️ Название комнаты", "Новое название", 90, rename))

    @discord.ui.button(label="Лимит", emoji="👥", custom_id="room:limit", row=0)
    async def limit(self, interaction, _):
        await interaction.response.send_modal(TextModal("👥 Лимит людей", "Сколько человек (0 = без лимита)", 2, limit))

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="room:lock", row=0)
    async def lock(self, interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await set_locked(await owned_room(interaction.user), True)
        await interaction.followup.send(LOCKED_TEXT, ephemeral=True)

    @discord.ui.button(label="Открыть", emoji="🔓", style=discord.ButtonStyle.success, custom_id="room:unlock", row=0)
    async def unlock(self, interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await set_locked(await owned_room(interaction.user), False)
        await interaction.followup.send("🔓 Комната открыта для всех: все слышат и говорят", ephemeral=True)

    @discord.ui.button(label="Пустить", emoji="✅", custom_id="room:allow", row=1)
    async def allow(self, interaction, _):
        async def act(ch, me, target):
            await let_in(ch, target)
            return f"✅ {target.mention} может зайти в комнату"
        await interaction.response.send_message(view=PickMemberView("Кого пустить?", act), ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Выгнать", emoji="👢", custom_id="room:kick", row=1)
    async def kick(self, interaction, _):
        async def act(ch, me, target):
            await kick_out(ch, target)
            return f"👢 {target.mention} выгнан и больше не сможет зайти"
        await interaction.response.send_message(view=PickMemberView("Кого выгнать?", act), ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Разблокировать", emoji="♻️", custom_id="room:unblock", row=1)
    async def unblock_btn(self, interaction, _):
        async def act(ch, me, target):
            await unblock(ch, target)
            return f"♻️ {target.mention} снова может зайти"
        await interaction.response.send_message(view=PickMemberView("Кого разблокировать?", act), ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Передать", emoji="👑", custom_id="room:owner", row=1)
    async def owner(self, interaction, _):
        async def act(ch, me, target):
            await transfer(ch, me, target)
            return f"👑 Теперь комнатой управляет {target.mention}"
        await interaction.response.send_message(view=PickMemberView("Кому передать комнату?", act), ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Скрыть", emoji="👁️", custom_id="room:hide", row=2)
    async def hide(self, interaction, _):
        await set_hidden(await owned_room(interaction.user), True)
        await interaction.response.send_message("👁️ Комната скрыта из списка — её видят только те, кто внутри "
                                                "или кого ты пустил", ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Показать", emoji="👀", custom_id="room:show", row=2)
    async def show(self, interaction, _):
        await set_hidden(await owned_room(interaction.user), False)
        await interaction.response.send_message("👀 Комната снова видна всем", ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Заглушить", emoji="🔇", custom_id="room:mute", row=2)
    async def mute(self, interaction, _):
        async def act(ch, me, target):
            await set_voice(ch, target, False)
            return f"🔇 {target.mention} не может говорить в твоей комнате"
        await interaction.response.send_message(view=PickMemberView("Кого заглушить?", act), ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Разглушить", emoji="🔊", custom_id="room:unmute", row=2)
    async def unmute(self, interaction, _):
        async def act(ch, me, target):
            await set_voice(ch, target, True)
            return f"🔊 {target.mention} снова может говорить"
        await interaction.response.send_message(view=PickMemberView("Кого разглушить?", act), ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Инфо", emoji="ℹ️", custom_id="room:info", row=3)
    async def info(self, interaction, _):
        await interaction.response.send_message(embed=await room_info(await owned_room(interaction.user)),
                                                ephemeral=True, delete_after=2 * GONE)

    @discord.ui.button(label="Помощь", emoji="❓", custom_id="room:help", row=3)
    async def help(self, interaction, _):
        await interaction.response.send_message(embed=help_embed(), ephemeral=True, delete_after=3 * GONE)

    @discord.ui.button(label="Забрать комнату", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="room:claim",
                       row=3)
    async def claim(self, interaction, _):
        voice = interaction.user.voice
        ch = voice.channel if voice else None
        row = ch and await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (ch.id,))
        if not row:
            return await interaction.response.send_message("🔊 Зайди в чью-то личную комнату", ephemeral=True, delete_after=GONE)
        if row[0] == interaction.user.id:
            return await interaction.response.send_message("Это и так твоя комната 🙂", ephemeral=True, delete_after=GONE)
        if any(m.id == row[0] for m in ch.members):
            return await interaction.response.send_message("Хозяин ещё в комнате — попроси его передать её тебе",
                                                           ephemeral=True, delete_after=GONE)
        old = ch.guild.get_member(row[0])
        if old:
            await transfer(ch, old, interaction.user)
        else:
            await db.execute("UPDATE temp_voice SET owner_id=? WHERE channel_id=?", (interaction.user.id, ch.id))
            await ch.set_permissions(interaction.user, view_channel=True, connect=True, speak=True,
                                     manage_channels=True, move_members=True, mute_members=True)
            rename_for(ch, interaction.user)  # прежний хозяин ушёл с сервера — его ника не знаем
        if is_locked(ch):
            await admit(ch, interaction.user)
        await interaction.response.send_message(f"🙋 Хозяин ушёл — теперь {ch.mention} твоя", ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Музыка", emoji="🎵", style=discord.ButtonStyle.success, custom_id="room:music", row=4)
    async def music_btn(self, interaction, _):
        from cogs.music import SongModal
        await interaction.response.send_modal(SongModal(self.music(interaction)))

    @discord.ui.button(label="Радио", emoji="📻", custom_id="room:radio", row=4)
    async def radio_btn(self, interaction, _):
        from cogs.music import RadioView
        await interaction.response.send_message("📻 Какую станцию включить?", view=RadioView(self.music(interaction)),
                                                ephemeral=True, delete_after=120)

    @discord.ui.button(label="Очередь", emoji="📄", custom_id="room:queue", row=4)
    async def queue_btn(self, interaction, _):
        from cogs.music import queue_embed
        st = self.music(interaction).state(interaction.guild.id)
        await interaction.response.send_message(embed=queue_embed(st), ephemeral=True, delete_after=120)

    @discord.ui.button(label="Подборка", emoji="⭐", custom_id="room:picks", row=4)
    async def picks_btn(self, interaction, _):
        await self.music(interaction).show_picks(interaction)


PANEL_TITLE = "🎛️ Управление комнатой"


def panel_embed(owner: discord.Member) -> discord.Embed:
    """Панель в чате комнаты — коротко, чтобы не занимала полчата. Что делают кнопки — по кнопке «Помощь»."""
    return discord.Embed(title=PANEL_TITLE, description=f"👑 {owner.mention} · ❓ **Помощь** — что делают кнопки",
                         colour=discord.Colour.blurple())


def help_embed() -> discord.Embed:
    return discord.Embed(
        title="❓ Что делают кнопки",
        description=(
            "Это личная комната хозяина. Когда все выйдут, она удалится сама.\n\n"
            "✏️ **Название** · 👥 **Лимит** людей\n"
            "🔒 **Закрыть** — зайти может любой, но ничего не слышит и молчит, пока ты не пустишь · "
            "🔓 **Открыть** для всех\n"
            "✅ **Пустить** · 👢 **Выгнать** и запретить вход · ♻️ **Разблокировать**\n"
            "👑 **Передать** комнату другому\n"
            "👁️ **Скрыть** из списка каналов · 👀 **Показать**\n"
            "🔇 **Заглушить** / 🔊 **Разглушить** человека — только в твоей комнате\n"
            "ℹ️ **Инфо** — кто пущен, заблокирован, заглушен\n"
            "🙋 **Забрать комнату** — если хозяин ушёл, а ты остался\n\n"
            "🎵 **Музыка** — название, ссылка или опиши песню, ИИ угадает · 📻 **Радио** · 📄 **Очередь** · "
            "⭐ **Подборка** песен сервера\n\n"
            "Музыку включает любой, кто в комнате, остальными кнопками пользуется хозяин. "
            "Ответы бота видишь только ты, и они исчезают сами.\n\n"
            "Панель бот раз в 2 минуты опускает вниз чата: старую убирает, новую присылает. "
            "Ваши сообщения он не трогает."
        ),
        colour=discord.Colour.blurple(),
    )


async def post_room_panel(bot: commands.Bot, channel: discord.TextChannel):
    """В #🎮・управление — только инструкция: сама панель живёт в чате каждой комнаты."""
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    await channel.send(embed=discord.Embed(
        title="🔊 Личные голосовые комнаты",
        description=(
            "**1.** Зайди в любой **«・Создать канал»** — бот создаст комнату с твоим ником и перенесёт тебя туда.\n"
            "**2.** Открой **чат комнаты** — значок 💬 рядом с её названием (или нажми на комнату).\n"
            "**3.** Там уже ждёт **панель управления**: название, лимит, закрыть/открыть, пустить, выгнать, "
            "скрыть, заглушить, передать комнату и другое.\n\n"
            "У каждой комнаты своя панель — никто никому не мешает, а здесь ничего не засоряется.\n"
            "Потерял панель? Напиши в чате комнаты `/room panel`."),
        colour=discord.Colour.blurple()))


class VoiceRooms(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.panels: dict[int, int] = {}  # комната → сообщение с панелью
        bot.add_view(RoomPanelView())
        bot.add_view(KnockView())
        self.keep_panels_low.start()

    def cog_unload(self):
        self.keep_panels_low.cancel()

    async def send_panel(self, room: discord.VoiceChannel, owner: discord.Member | None):
        """Новая панель внизу чата комнаты, старая — удаляется."""
        old = self.panels.pop(room.id, None)
        if old:
            try:
                await room.get_partial_message(old).delete()
            except discord.HTTPException:
                pass
        if owner is None:
            return
        try:
            self.panels[room.id] = (await room.send(embed=panel_embed(owner), view=RoomPanelView())).id
        except discord.HTTPException:
            pass

    @tasks.loop(minutes=PANEL_EVERY)
    async def keep_panels_low(self):
        """Раз в 2 минуты: если в чате комнаты панель уехала вверх — присылаем её снова последним сообщением."""
        for channel_id, owner_id in await db.fetchall("SELECT channel_id, owner_id FROM temp_voice"):
            room = self.bot.get_channel(channel_id)
            if not isinstance(room, discord.VoiceChannel) or not room.members:
                continue
            panel = self.panels.get(room.id)
            if panel is None:  # бот перезапускался — ищем свою панель в чате
                try:
                    async for msg in room.history(limit=50):
                        if msg.author == self.bot.user and any(getattr(c, "custom_id", None) == "room:name"
                                                               for row in msg.components for c in row.children):
                            if msg.embeds and msg.embeds[0].title != PANEL_TITLE:  # старая длинная панель
                                await msg.delete()
                                break
                            panel = self.panels[room.id] = msg.id
                            break
                except discord.HTTPException:
                    continue
            if panel is not None and room.last_message_id == panel:
                continue
            await self.send_panel(room, room.guild.get_member(owner_id))

    @keep_panels_low.before_loop
    async def before_panels(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        # После перезапуска удаляем пустые комнаты, которые остались
        for (channel_id,) in await db.fetchall("SELECT channel_id FROM temp_voice"):
            ch = self.bot.get_channel(channel_id)
            if ch is None:
                await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (channel_id,))
            else:
                await self.cleanup(ch)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel:
            return
        waiting = await db.fetchone("SELECT channel_id FROM voice_waiting WHERE guild_id=? AND user_id=?",
                                    (member.guild.id, member.id))
        if waiting and (after.channel is None or waiting[0] != after.channel.id):
            await release(member)  # ушёл от двери закрытой комнаты — снова всё слышит
        if after.channel and await db.fetchone("SELECT 1 FROM voice_creators WHERE channel_id=?", (after.channel.id,)):
            await self.create_room(member, after.channel)
        elif after.channel:
            await self.at_door(member, after.channel)
        if before.channel:
            await self.cleanup(before.channel)

    async def at_door(self, member: discord.Member, room):
        """Зашёл в закрытую комнату и его ещё не пускали: ничего не слышит и молчит, хозяина спрашиваем в чате."""
        if member.bot or not isinstance(room, discord.VoiceChannel) or not is_locked(room):
            return
        row = await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (room.id,))
        if not row or row[0] == member.id or admitted(room, member) or member.guild_permissions.administrator:
            return
        try:
            await member.edit(deafen=True, reason="Ждёт у входа в закрытую комнату")
        except discord.HTTPException:
            pass
        knock = None
        try:
            knock = await room.send(f"🔔 {member.mention} ждёт у входа: пока ничего не слышит и не может говорить. "
                                    f"<@{row[0]}>, пустить?", view=KnockView(),
                                    allowed_mentions=discord.AllowedMentions(users=[discord.Object(row[0])]))
        except discord.HTTPException:
            pass
        await db.execute("INSERT OR REPLACE INTO voice_waiting (guild_id, user_id, channel_id, msg_id) VALUES (?,?,?,?)",
                         (member.guild.id, member.id, room.id, knock.id if knock else 0))

    async def create_room(self, member: discord.Member, creator: discord.VoiceChannel):
        if member.bot:
            return
        if not await perms.allowed(member, "rooms"):
            await member.move_to(None)
            try:
                await member.send("⛔ Тебе нельзя создавать личные комнаты на этом сервере.")
            except discord.HTTPException:
                pass
            return
        overwrites = dict(creator.overwrites)
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True, manage_channels=True,
            move_members=True, mute_members=True,
        )
        emoji = creator.name.split("・")[0] if "・" in creator.name else "🔊"
        room = await member.guild.create_voice_channel(
            f"{emoji}・{member.display_name}"[:100], category=creator.category, overwrites=overwrites,
            position=creator.position + 1, reason=f"Личная комната {member}",
        )
        await db.execute("INSERT INTO temp_voice (channel_id, owner_id) VALUES (?,?)", (room.id, member.id))
        try:
            await member.move_to(room)
        except discord.HTTPException:
            await self.cleanup(room)
            return
        await self.send_panel(room, member)

    async def cleanup(self, channel):
        if not isinstance(channel, discord.VoiceChannel) or channel.members:
            return
        if await db.fetchone("SELECT 1 FROM temp_voice WHERE channel_id=?", (channel.id,)):
            await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (channel.id,))
            self.panels.pop(channel.id, None)
            try:
                await channel.delete(reason="Комната опустела")
            except discord.NotFound:
                pass

    async def own_room(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        if ch := await owned_room(interaction.user):
            return ch
        await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        return None

    room = app_commands.Group(name="room", description="Управление своей голосовой комнатой", guild_only=True)

    @room.command(name="panel", description="Показать панель управления в чате своей комнаты")
    async def room_panel(self, interaction: discord.Interaction):
        if ch := await self.own_room(interaction):
            await self.send_panel(ch, interaction.user)
            await interaction.response.send_message(f"✅ Панель в чате {ch.mention}", ephemeral=True, delete_after=GONE)

    @room.command(name="name", description="Переименовать свою комнату")
    async def room_name(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 90]):
        if ch := await self.own_room(interaction):
            await interaction.response.send_message(await rename(ch, name), ephemeral=True)

    @room.command(name="limit", description="Лимит людей (0 = без лимита)")
    async def room_limit(self, interaction: discord.Interaction, count: app_commands.Range[int, 0, 99]):
        if ch := await self.own_room(interaction):
            await interaction.response.send_message(await limit(ch, str(count)), ephemeral=True)

    @room.command(name="lock", description="Закрыть комнату — новенькие молчат и не слышат, пока не пустишь")
    async def room_lock(self, interaction: discord.Interaction):
        if ch := await self.own_room(interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            await set_locked(ch, True)
            await interaction.followup.send(LOCKED_TEXT + " Пустить заранее: `/room invite`", ephemeral=True)

    @room.command(name="unlock", description="Открыть комнату для всех")
    async def room_unlock(self, interaction: discord.Interaction):
        if ch := await self.own_room(interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            await set_locked(ch, False)
            await interaction.followup.send("🔓 Комната открыта", ephemeral=True)

    @room.command(name="invite", description="Разрешить человеку зайти в закрытую комнату")
    async def room_invite(self, interaction: discord.Interaction, member: discord.Member):
        if ch := await self.own_room(interaction):
            await let_in(ch, member)
            await interaction.response.send_message(f"✅ {member.mention} может зайти", ephemeral=True)

    @room.command(name="kick", description="Выгнать человека из комнаты и запретить вход")
    async def room_kick(self, interaction: discord.Interaction, member: discord.Member):
        if ch := await self.own_room(interaction):
            if member == interaction.user:
                return await interaction.response.send_message("Себя выгнать нельзя 🙃", ephemeral=True)
            await kick_out(ch, member)
            await interaction.response.send_message(f"👢 {member.mention} выгнан", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceRooms(bot))
