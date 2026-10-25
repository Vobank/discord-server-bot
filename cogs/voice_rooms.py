"""Личные голосовые: зашёл в «・Создать канал» — бот создал комнату с твоим ником, опустела — удалил.
Каналы-создатели хранятся в таблице voice_creators (их добавляет /setup).
Управление: кнопки в #🎮・управление или команды /room."""
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import perms

NOT_OWNER = "🔊 Зайди в **свою** комнату (через любой «・Создать канал»), чтобы ею управлять."


async def owned_room(member: discord.Member) -> discord.VoiceChannel | None:
    voice = member.voice
    if voice and voice.channel:
        row = await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (voice.channel.id,))
        if row and row[0] == member.id:
            return voice.channel
    return None


async def set_locked(ch: discord.VoiceChannel, locked: bool):
    targets = [t for t in ch.overwrites if isinstance(t, discord.Role)]
    if locked and ch.guild.default_role not in targets:
        targets.append(ch.guild.default_role)
    for target in targets:
        ow = ch.overwrites_for(target)
        ow.connect = False if locked else None
        await ch.set_permissions(target, overwrite=ow)


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
    ow.speak = None if can_speak else False
    await ch.set_permissions(member, overwrite=ow if not ow.is_empty() else None)


async def unblock(ch: discord.VoiceChannel, member: discord.Member):
    ow = ch.overwrites_for(member)
    ow.connect = None
    await ch.set_permissions(member, overwrite=ow if not ow.is_empty() else None)


async def room_info(ch: discord.VoiceChannel) -> discord.Embed:
    row = await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (ch.id,))
    everyone = ch.overwrites_for(ch.guild.default_role)
    locked = everyone.connect is False
    hidden = everyone.view_channel is False
    trusted, blocked, muted = [], [], []
    for t, ow in ch.overwrites.items():
        if isinstance(t, discord.Member) and (not row or t.id != row[0]):
            if ow.connect is True:
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
    e.add_field(name="⛔ Заблокированы", value=", ".join(blocked) or "—", inline=False)
    e.add_field(name="🔇 Заглушены", value=", ".join(muted) or "—", inline=False)
    return e


async def let_in(ch: discord.VoiceChannel, member: discord.Member):
    await ch.set_permissions(member, view_channel=True, connect=True)


async def kick_out(ch: discord.VoiceChannel, member: discord.Member):
    await ch.set_permissions(member, connect=False)
    if member.voice and member.voice.channel == ch:
        await member.move_to(None)


async def transfer(ch: discord.VoiceChannel, old: discord.Member, new: discord.Member):
    await db.execute("UPDATE temp_voice SET owner_id=? WHERE channel_id=?", (new.id, ch.id))
    owner_ow = ch.overwrites_for(old)
    await ch.set_permissions(old, overwrite=None)
    await ch.set_permissions(new, overwrite=owner_ow)


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
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True, delete_after=15)
        await interaction.response.send_message(await self.apply(ch, self.value.value), ephemeral=True, delete_after=15)


class PickMemberView(discord.ui.View):
    def __init__(self, placeholder: str, action):
        super().__init__(timeout=300)
        self.action = action
        self.pick.placeholder = placeholder

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="-")
    async def pick(self, interaction: discord.Interaction, select):
        ch = await owned_room(interaction.user)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True, delete_after=15)
        target = select.values[0]
        target = target if isinstance(target, discord.Member) else interaction.guild.get_member(target.id)
        if not target or target == interaction.user:
            return await interaction.response.send_message("Выбери другого человека 🙂", ephemeral=True, delete_after=15)
        await interaction.response.edit_message(content=await self.action(ch, interaction.user, target), view=None)
        await asyncio.sleep(15)  # убираем, чтобы не копилось
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
        if (interaction.data or {}).get("custom_id") == "room:claim" or await owned_room(interaction.user):
            return True
        await interaction.response.send_message(NOT_OWNER, ephemeral=True, delete_after=15)
        return False

    @discord.ui.button(label="Название", emoji="✏️", custom_id="room:name", row=0)
    async def name(self, interaction, _):
        await interaction.response.send_modal(TextModal("✏️ Название комнаты", "Новое название", 90, rename))

    @discord.ui.button(label="Лимит", emoji="👥", custom_id="room:limit", row=0)
    async def limit(self, interaction, _):
        await interaction.response.send_modal(TextModal("👥 Лимит людей", "Сколько человек (0 = без лимита)", 2, limit))

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="room:lock", row=0)
    async def lock(self, interaction, _):
        await set_locked(await owned_room(interaction.user), True)
        await interaction.response.send_message("🔒 Комната закрыта — зайдут только те, кого ты пустишь", ephemeral=True, delete_after=15)

    @discord.ui.button(label="Открыть", emoji="🔓", style=discord.ButtonStyle.success, custom_id="room:unlock", row=0)
    async def unlock(self, interaction, _):
        await set_locked(await owned_room(interaction.user), False)
        await interaction.response.send_message("🔓 Комната открыта для всех", ephemeral=True, delete_after=15)

    @discord.ui.button(label="Пустить", emoji="✅", custom_id="room:allow", row=1)
    async def allow(self, interaction, _):
        async def act(ch, me, target):
            await let_in(ch, target)
            return f"✅ {target.mention} может зайти в комнату"
        await interaction.response.send_message(view=PickMemberView("Кого пустить?", act), ephemeral=True, delete_after=15)

    @discord.ui.button(label="Выгнать", emoji="👢", custom_id="room:kick", row=1)
    async def kick(self, interaction, _):
        async def act(ch, me, target):
            await kick_out(ch, target)
            return f"👢 {target.mention} выгнан и больше не сможет зайти"
        await interaction.response.send_message(view=PickMemberView("Кого выгнать?", act), ephemeral=True, delete_after=15)

    @discord.ui.button(label="Разблокировать", emoji="♻️", custom_id="room:unblock", row=1)
    async def unblock_btn(self, interaction, _):
        async def act(ch, me, target):
            await unblock(ch, target)
            return f"♻️ {target.mention} снова может зайти"
        await interaction.response.send_message(view=PickMemberView("Кого разблокировать?", act), ephemeral=True, delete_after=15)

    @discord.ui.button(label="Передать", emoji="👑", custom_id="room:owner", row=1)
    async def owner(self, interaction, _):
        async def act(ch, me, target):
            await transfer(ch, me, target)
            return f"👑 Теперь комнатой управляет {target.mention}"
        await interaction.response.send_message(view=PickMemberView("Кому передать комнату?", act), ephemeral=True, delete_after=15)

    @discord.ui.button(label="Скрыть", emoji="👁️", custom_id="room:hide", row=2)
    async def hide(self, interaction, _):
        await set_hidden(await owned_room(interaction.user), True)
        await interaction.response.send_message("👁️ Комната скрыта из списка — её видят только те, кто внутри "
                                                "или кого ты пустил", ephemeral=True, delete_after=15)

    @discord.ui.button(label="Показать", emoji="👀", custom_id="room:show", row=2)
    async def show(self, interaction, _):
        await set_hidden(await owned_room(interaction.user), False)
        await interaction.response.send_message("👀 Комната снова видна всем", ephemeral=True, delete_after=15)

    @discord.ui.button(label="Заглушить", emoji="🔇", custom_id="room:mute", row=2)
    async def mute(self, interaction, _):
        async def act(ch, me, target):
            await set_voice(ch, target, False)
            return f"🔇 {target.mention} не может говорить в твоей комнате"
        await interaction.response.send_message(view=PickMemberView("Кого заглушить?", act), ephemeral=True, delete_after=15)

    @discord.ui.button(label="Разглушить", emoji="🔊", custom_id="room:unmute", row=2)
    async def unmute(self, interaction, _):
        async def act(ch, me, target):
            await set_voice(ch, target, True)
            return f"🔊 {target.mention} снова может говорить"
        await interaction.response.send_message(view=PickMemberView("Кого разглушить?", act), ephemeral=True, delete_after=15)

    @discord.ui.button(label="Инфо", emoji="ℹ️", custom_id="room:info", row=3)
    async def info(self, interaction, _):
        await interaction.response.send_message(embed=await room_info(await owned_room(interaction.user)),
                                                ephemeral=True, delete_after=60)

    @discord.ui.button(label="Забрать комнату", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="room:claim",
                       row=3)
    async def claim(self, interaction, _):
        voice = interaction.user.voice
        ch = voice.channel if voice else None
        row = ch and await db.fetchone("SELECT owner_id FROM temp_voice WHERE channel_id=?", (ch.id,))
        if not row:
            return await interaction.response.send_message("🔊 Зайди в чью-то личную комнату", ephemeral=True, delete_after=15)
        if row[0] == interaction.user.id:
            return await interaction.response.send_message("Это и так твоя комната 🙂", ephemeral=True, delete_after=15)
        if any(m.id == row[0] for m in ch.members):
            return await interaction.response.send_message("Хозяин ещё в комнате — попроси его передать её тебе",
                                                           ephemeral=True, delete_after=15)
        old = ch.guild.get_member(row[0])
        if old:
            await transfer(ch, old, interaction.user)
        else:
            await db.execute("UPDATE temp_voice SET owner_id=? WHERE channel_id=?", (interaction.user.id, ch.id))
            await ch.set_permissions(interaction.user, view_channel=True, connect=True, speak=True,
                                     manage_channels=True, move_members=True, mute_members=True)
        await interaction.response.send_message(f"🙋 Хозяин ушёл — теперь {ch.mention} твоя", ephemeral=True, delete_after=15)


def panel_embed(owner: discord.Member) -> discord.Embed:
    return discord.Embed(
        title="🔊 Панель твоей комнаты",
        description=(
            f"{owner.mention}, это твоя комната. Когда все выйдут, она удалится сама.\n\n"
            "✏️ **Название** · 👥 **Лимит** людей\n"
            "🔒 **Закрыть** — зайдут только те, кого ты пустишь · 🔓 **Открыть** для всех\n"
            "✅ **Пустить** · 👢 **Выгнать** и запретить вход · ♻️ **Разблокировать**\n"
            "👑 **Передать** комнату другому\n"
            "👁️ **Скрыть** из списка каналов · 👀 **Показать**\n"
            "🔇 **Заглушить** / 🔊 **Разглушить** человека — только в твоей комнате\n"
            "ℹ️ **Инфо** — кто пущен, заблокирован, заглушен\n"
            "🙋 **Забрать комнату** — если хозяин ушёл, а ты остался\n\n"
            "Кнопками пользуется хозяин комнаты. Ответы бота видишь только ты, и они исчезают сами."
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
        bot.add_view(RoomPanelView())

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
        if after.channel and after.channel != before.channel and await db.fetchone(
                "SELECT 1 FROM voice_creators WHERE channel_id=?", (after.channel.id,)):
            await self.create_room(member, after.channel)
        if before.channel and before.channel != after.channel:
            await self.cleanup(before.channel)

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
        try:
            await room.send(embed=panel_embed(member), view=RoomPanelView())
        except discord.HTTPException:
            pass

    async def cleanup(self, channel):
        if not isinstance(channel, discord.VoiceChannel) or channel.members:
            return
        if await db.fetchone("SELECT 1 FROM temp_voice WHERE channel_id=?", (channel.id,)):
            await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (channel.id,))
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
            await ch.send(embed=panel_embed(interaction.user), view=RoomPanelView())
            await interaction.response.send_message(f"✅ Панель в чате {ch.mention}", ephemeral=True, delete_after=15)

    @room.command(name="name", description="Переименовать свою комнату")
    async def room_name(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 90]):
        if ch := await self.own_room(interaction):
            await interaction.response.send_message(await rename(ch, name), ephemeral=True)

    @room.command(name="limit", description="Лимит людей (0 = без лимита)")
    async def room_limit(self, interaction: discord.Interaction, count: app_commands.Range[int, 0, 99]):
        if ch := await self.own_room(interaction):
            await interaction.response.send_message(await limit(ch, str(count)), ephemeral=True)

    @room.command(name="lock", description="Закрыть комнату — зайти смогут только приглашённые")
    async def room_lock(self, interaction: discord.Interaction):
        if ch := await self.own_room(interaction):
            await set_locked(ch, True)
            await interaction.response.send_message("🔒 Комната закрыта. Пустить: `/room invite`", ephemeral=True)

    @room.command(name="unlock", description="Открыть комнату для всех")
    async def room_unlock(self, interaction: discord.Interaction):
        if ch := await self.own_room(interaction):
            await set_locked(ch, False)
            await interaction.response.send_message("🔓 Комната открыта", ephemeral=True)

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
