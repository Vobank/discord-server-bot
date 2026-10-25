"""/setup — строит сервер с нуля или достраивает существующий. Ничего не удаляет и не трогает существующие
каналы и права: в старые категории только ДОБАВЛЯЕТ права ролям mini Admin. Что строить — модули в настройках.
Можно запускать сколько угодно раз."""
import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import perms
import utils

READONLY = dict(
    send_messages=False, add_reactions=False, send_messages_in_threads=False,
    create_public_threads=False, create_private_threads=False,
)
# Права mini Admin — действуют ТОЛЬКО в категории его отдела (каналы удалять/создавать не может)
MINI_ADMIN = discord.PermissionOverwrite(
    view_channel=True, read_message_history=True, send_messages=True, send_messages_in_threads=True,
    manage_messages=True, manage_threads=True, create_public_threads=True,   # удалять/закреплять, ветки
    embed_links=True, attach_files=True, add_reactions=True, use_external_emojis=True, use_external_stickers=True,
    mention_everyone=True,                                                    # пинг дойдёт только до отдела
    connect=True, speak=True, stream=True, mute_members=True, deafen_members=True, move_members=True,
    priority_speaker=True,
)
MINI_ADMIN_COLOUR = discord.Colour(0x6B5BFF)  # как у роли «mini Admin»
GAME_CHOICES = [app_commands.Choice(name=g["name"], value=g["name"]) for g in config.GAMES]


def copy_ow(ow: discord.PermissionOverwrite) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite.from_pair(*ow.pair())


async def ensure_role(guild: discord.Guild, name: str, **kwargs) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, reason="/setup", **kwargs)
    return role


async def ensure_category(guild: discord.Guild, name: str, overwrites) -> discord.CategoryChannel:
    """Только для категорий бота: создаёт или приводит права к нужным."""
    cat = discord.utils.get(guild.categories, name=name)
    if cat is None:
        cat = await guild.create_category(name, overwrites=overwrites, reason="/setup")
    else:
        await cat.edit(overwrites=overwrites)
    return cat


def child_overwrites(category: discord.CategoryChannel, readonly_for=()):
    overwrites = {t: copy_ow(ow) for t, ow in category.overwrites.items()}
    for target in readonly_for:
        ow = overwrites.get(target, discord.PermissionOverwrite())
        ow.update(**READONLY)
        overwrites[target] = ow
    return overwrites


class Place:
    """Категория для новых каналов. Ищется по id/названию и создаётся, только когда в неё правда кладём канал —
    поэтому на уже настроенном сервере /setup не плодит пустых категорий."""

    def __init__(self, guild: discord.Guild, name: str, category_id: int | None = None):
        self.guild, self.name, self.category_id = guild, name, category_id

    async def get(self) -> discord.CategoryChannel:
        cat = utils.find_channel(self.guild, self.name, self.category_id, "category")
        if cat is None:
            cat = await self.guild.create_category(self.name, reason="/setup")
        return cat


async def ensure_text(where, name: str, readonly_for=(), topic=None):
    """Создаёт канал бота, если его нет. Существующий не трогает. Возвращает (канал, создан_ли).
    where — категория или Place."""
    ch = discord.utils.get(where.guild.text_channels, name=name)  # по всему серверу: канал могли перенести
    if ch:
        return ch, False
    category = await where.get() if isinstance(where, Place) else where
    ch = await category.create_text_channel(name, overwrites=child_overwrites(category, readonly_for), topic=topic)
    return ch, True


async def ensure_voice(where, name: str) -> discord.VoiceChannel:
    ch = discord.utils.get(where.guild.voice_channels, name=name)
    if ch is None:
        category = await where.get() if isinstance(where, Place) else where
        ch = await category.create_voice_channel(name, overwrites=child_overwrites(category))
    return ch


async def add_overwrite(channel, target, ow: discord.PermissionOverwrite) -> bool:
    """Добавляет права одной роли, не трогая остальные. True — если что-то поменялось."""
    if channel.overwrites_for(target) == ow:
        return False
    await channel.set_permissions(target, overwrite=ow, reason="/setup: права mini Admin")
    return True


def is_private(channel, everyone: discord.Role, game_role: discord.Role) -> bool:
    """Закрытые служебные каналы (логи и т.п.) — mini Admin туда не пускаем."""
    return channel.overwrites_for(everyone).view_channel is False and \
        channel.overwrites_for(game_role).view_channel is not True


class ServerSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Построить или достроить сервер: роли, каналы, панели (ничего не удаляет)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        report = await build_server(self.bot, interaction.guild)
        await interaction.followup.send("✅ Сервер настроен!\n" + "\n".join(f"• {r}" for r in report), ephemeral=True)

    @app_commands.command(name="setup-check", description="Показать, что /setup создаст (ничего не меняет)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_check(self, interaction: discord.Interaction):
        items = missing_items(interaction.guild)
        text = ("✅ Всё уже на месте — /setup только обновит панели." if not items else
                "/setup создаст:\n" + "\n".join(f"• {i}" for i in items))
        await interaction.response.send_message(text[:1990], ephemeral=True)

    # --- mini Admin отделов (то же, что кнопка 🛡️ в админ-панели) ---
    dept = app_commands.Group(
        name="dept-admin", description="mini Admin отделов (админы отдельных игр)",
        default_permissions=discord.Permissions(administrator=True), guild_only=True,
    )

    @dept.command(name="add", description="Назначить mini Admin отдела")
    @app_commands.choices(game=GAME_CHOICES)
    async def dept_add(self, interaction: discord.Interaction, member: discord.Member, game: app_commands.Choice[str]):
        role = discord.utils.get(interaction.guild.roles, name=config.admin_role_name(game.value))
        if role is None:
            return await interaction.response.send_message("Сначала запусти /setup", ephemeral=True)
        await member.add_roles(role, reason=f"mini Admin, назначил {interaction.user}")
        await interaction.response.send_message(f"✅ {member.mention} теперь **{role.name}**", ephemeral=True)

    @dept.command(name="remove", description="Снять mini Admin отдела")
    @app_commands.choices(game=GAME_CHOICES)
    async def dept_remove(self, interaction: discord.Interaction, member: discord.Member, game: app_commands.Choice[str]):
        role = discord.utils.get(interaction.guild.roles, name=config.admin_role_name(game.value))
        if role and role in member.roles:
            await member.remove_roles(role, reason=f"Снял {interaction.user}")
        await interaction.response.send_message(f"✅ {member.mention} больше не mini Admin {game.value}", ephemeral=True)


def missing_items(g: discord.Guild) -> list[str]:
    """Что /setup создаст на этом сервере (ничего не меняет). Пусто — всё уже есть."""
    on = config.enabled
    roles = {r.name for r in g.roles}
    texts = {c.name for c in g.text_channels}
    voices = {c.name for c in g.voice_channels}
    cats = {c.name for c in g.categories}
    want_roles = [config.ROLE_BASE, config.ROLE_PENDING, config.ROLE_STAFF, config.ROLE_HEAD_ADMIN, config.ROLE_HEAD_MOD,
                  config.ROLE_MOD, *(r for r, *_ in config.GENDERS), *(n for n, _ in config.CUSTOM_ROLES)]
    want_texts = [config.CH_WELCOME, config.CH_JOINS, config.CH_NEWS, config.CH_MEMES, config.CH_ADMIN_PANEL,
                  config.CH_MINI_PANEL, config.CH_ADMIN_CHAT, config.CH_ADMIN_LOG, config.CH_MOD_PANEL, config.CH_MOD_CHAT]
    want_voices, want_cats = [], [config.CAT_ADMIN]
    for game in config.GAMES:
        want_roles += [*config.dept_roles(game), config.admin_role_name(game["name"])]
        if "category_id" not in game:
            want_cats.append(game["category"])
    if on("levels"):
        want_roles += [*config.LEVEL_ROLES.values(), *(a["role"] for a in config.ACHIEVEMENTS)]
        want_texts += [config.CH_LEVELS, config.CH_ACHIEVEMENTS, config.CH_RATINGS]
    if on("birthdays"):
        want_roles.append(config.ROLE_BIRTHDAY)
        want_texts.append(config.CH_BIRTHDAYS)
    if on("community"):
        want_texts += [config.CH_IDEAS, config.CH_STARBOARD]
    if on("voice_rooms"):
        want_voices.append(config.VOICE_CREATOR)
    if on("adult_channels"):
        want_roles += [config.ROLE_GIRLS_18, config.ROLE_BOYS_18]
        want_texts += [config.CH_GIRLS, config.CH_BOYS]
    if on("family"):
        want_roles += [*(n for n, *_ in config.FAMILY_ROLES), config.ROLE_FAMILY_PROBATION, config.ROLE_FAMILY_MEMBER]
        want_cats.append(config.CAT_FAMILY)
        want_texts += [config.CH_FAMILY_APPLY, config.CH_FAMILY_REQUESTS, config.CH_FAMILY_PROBATION,
                       config.CH_FAMILY_HR, config.CH_FAMILY_HR_REPORTS]
    if on("applications"):
        want_cats.append(config.CAT_APPLY)
        want_texts += [config.CH_APPLY, config.CH_APPLY_REVIEW]
        want_voices.append(config.VC_APPLY)
    if on("cinema"):
        want_roles.append(config.ROLE_CINEMA)
        want_cats.append(config.CAT_CINEMA)
        want_texts += [config.CH_CINEMA_AFISHA, config.CH_CINEMA_WISHLIST, config.CH_CINEMA_TALK, config.CH_CINEMA_SETUP]
        want_voices.append(config.VC_CINEMA)
    out = [f"🎭 роль «{n}»" for n in dict.fromkeys(want_roles) if n not in roles]
    out += [f"📁 категория «{n}»" for n in dict.fromkeys(want_cats) if n not in cats]
    out += [f"💬 канал «{n}»" for n in dict.fromkeys(want_texts) if n not in texts]
    out += [f"🔊 голосовой «{n}»" for n in dict.fromkeys(want_voices) if n not in voices]
    for found, name in ((utils.rules_channel(g), config.CH_RULES), (utils.general_channel(g), config.CH_GENERAL)):
        if found is None:
            out.append(f"💬 канал «{name}»")
    if on("voice_rooms") and utils.rooms_panel_channel(g) is None:
        out.append(f"💬 канал «{config.CH_ROOMS_PANEL}»")
    if on("server_stats") and not any(v.name.startswith(config.STATS_PREFIX) for v in g.voice_channels):
        out.append(f"🔊 счётчик «{config.STATS_PREFIX}N»")
    for game in config.GAMES:
        if "category_id" in game and not isinstance(g.get_channel(game["category_id"]), discord.CategoryChannel):
            out.append(f"⚠️ категория отдела {game['name']} с id {game['category_id']} не найдена")
    return out


async def build_server(bot: commands.Bot, g: discord.Guild) -> list[str]:
    on = config.enabled
    everyone = g.default_role
    hidden = discord.PermissionOverwrite(view_channel=False)
    visible = discord.PermissionOverwrite(view_channel=True)
    report = []

    if config.BOT_NICKNAME and g.me.nick != config.BOT_NICKNAME:
        try:
            await g.me.edit(nick=config.BOT_NICKNAME)
        except discord.HTTPException:
            pass

    # --- Роли ---
    if not discord.utils.get(g.roles, name=config.ROLE_BASE):
        report.append(f"✅ Базовая роль «{config.ROLE_BASE}» — выдаётся после анкеты")
    base = await ensure_role(g, config.ROLE_BASE)
    for role_name, *_ in config.GENDERS:
        await ensure_role(g, role_name)
    if on("levels"):
        for role_name in config.LEVEL_ROLES.values():
            await ensure_role(g, role_name, colour=discord.Colour.gold(), hoist=True)
    staff = await ensure_role(g, config.ROLE_STAFF, colour=discord.Colour.dark_red(), hoist=True)
    if not discord.utils.get(g.roles, name=config.ROLE_HEAD_ADMIN):
        report.append(f"👑 Роли «{config.ROLE_HEAD_ADMIN}» и «{config.ROLE_HEAD_MOD}»")
    await ensure_role(g, config.ROLE_HEAD_ADMIN, colour=discord.Colour(0xFF4500), hoist=True,
                      permissions=discord.Permissions(administrator=True))
    head_mod = await ensure_role(g, config.ROLE_HEAD_MOD, colour=discord.Colour(0xF1C40F), hoist=True,
                                 permissions=discord.Permissions(
                                     kick_members=True, ban_members=True, moderate_members=True, view_audit_log=True,
                                     manage_messages=True, manage_threads=True, manage_nicknames=True,
                                     mute_members=True, deafen_members=True, move_members=True, mention_everyone=True,
                                     manage_events=True, create_events=True, priority_speaker=True))
    if not discord.utils.get(g.roles, name=config.ROLE_MOD):
        report.append(f"🛡️ Роль «{config.ROLE_MOD}» + мод-панель и мод-чат")
    mod = await ensure_role(g, config.ROLE_MOD, colour=discord.Colour(0x2ECC71), hoist=True,
                            permissions=discord.Permissions(
                                moderate_members=True, manage_messages=True, manage_threads=True,
                                mute_members=True, deafen_members=True, move_members=True, view_audit_log=True))
    if on("birthdays"):
        await ensure_role(g, config.ROLE_BIRTHDAY, colour=discord.Colour(0xFF69B4), hoist=True)
    for name, colour in config.CUSTOM_ROLES:
        role = discord.utils.get(g.roles, name=name)
        if role is None:
            await g.create_role(name=name, colour=discord.Colour(colour), reason="/setup: именная роль")
            report.append(f"🎨 Роль «{name}»")
        elif role.colour.value != colour:
            await role.edit(colour=discord.Colour(colour))
    for role_name, nick_part in config.CUSTOM_ROLE_OWNERS.items():
        role = discord.utils.get(g.roles, name=role_name)
        owner = discord.utils.find(lambda m: nick_part.lower() in m.display_name.lower(), g.members)
        if role and owner and role not in owner.roles:
            await owner.add_roles(role, reason="/setup: именная роль")
            report.append(f"🎁 {owner.mention} получил(а) «{role_name}»")
    if on("adult_channels"):
        await ensure_role(g, config.ROLE_GIRLS_18)
        await ensure_role(g, config.ROLE_BOYS_18)
    if on("levels"):
        new_ach = [a["role"] for a in config.ACHIEVEMENTS if not discord.utils.get(g.roles, name=a["role"])]
        for ach in config.ACHIEVEMENTS:
            await ensure_role(g, ach["role"], colour=discord.Colour(ach["colour"]))
        if new_ach:
            report.append(f"🏆 Роли за достижения: {', '.join(new_ach)}")

    # Категории сервера создаются, только если в них правда нужно положить новый канал
    info = Place(g, config.CAT_INFO)
    main = Place(g, config.CAT_MAIN, config.CAT_MAIN_ID)
    activity = Place(g, config.CAT_ACTIVITY)
    voice = Place(g, config.CAT_VOICE)

    # --- Информация: правила, старт (анкета), новички, новости ---
    rules = utils.rules_channel(g)
    if rules is None:
        rules, _ = await ensure_text(info, config.CH_RULES, readonly_for=[everyone], topic="Правила сервера")
        from cogs.rules import post_rules
        await post_rules(bot, rules)
        report.append(f"{rules.mention} — правила (текст — в rules.json, потом /rules)")
    welcome, created = await ensure_text(info, config.CH_WELCOME, readonly_for=[everyone],
                                         topic="Анкета: пол, день рождения и игры")
    if created:
        await welcome.move(beginning=True)
        report.append(f"{welcome.mention} — анкета и выбор игр")
    joins, created = await ensure_text(info, config.CH_JOINS, readonly_for=[everyone],
                                       topic="Здесь бот встречает каждого нового участника 🎉")
    if created:
        report.append(f"{joins.mention} — карточка приветствия новичков")
    if joins.category == welcome.category and joins.position > welcome.position:
        await joins.move(before=welcome)
    news, created = await ensure_text(info, config.CH_NEWS, readonly_for=[everyone], topic="Новости сервера")
    if created:
        report.append(f"{news.mention} — новости")

    # --- Общение ---
    general = utils.general_channel(g)
    if general is None:
        general, _ = await ensure_text(main, config.CH_GENERAL, topic="Общий чат")
        report.append(f"{general.mention} — общий чат")
    memes, created = await ensure_text(main, config.CH_MEMES, topic="Мемы и приколы")
    if created:
        report.append(f"{memes.mention} — мемы")

    # --- Активность: календарь, уровни, достижения, идеи, зал славы ---
    if on("birthdays"):
        bdays, created = await ensure_text(activity, config.CH_BIRTHDAYS, readonly_for=[everyone],
                                           topic=f"Дни рождения и праздники — бот поздравляет в "
                                                 f"{config.tz(f'{config.BIRTHDAY_HOUR}:00')}")
        if created:
            report.append(f"{bdays.mention} — поздравления")
    if on("levels"):
        levels, created = await ensure_text(activity, config.CH_LEVELS, readonly_for=[everyone],
                                            topic="Уровни за сообщения. /rank — твой уровень, /top — топ")
        if created:
            report.append(f"{levels.mention} — уровни")
        ach_ch, created = await ensure_text(activity, config.CH_ACHIEVEMENTS, readonly_for=[everyone],
                                            topic="Полученные достижения")
        if created:
            report.append(f"{ach_ch.mention} — достижения")
    ideas = None
    if on("community"):
        ideas, created = await ensure_text(activity, config.CH_IDEAS,
                                           topic="Предлагай идеи для сервера — голосуем 👍 / 👎")
        if created:
            await ideas.set_permissions(everyone, send_messages=False, add_reactions=True, create_public_threads=False,
                                        send_messages_in_threads=True)
            report.append(f"{ideas.mention} — идеи с голосованием")
        stars, created = await ensure_text(activity, config.CH_STARBOARD, readonly_for=[everyone],
                                           topic=f"Зал славы: сообщения, набравшие {config.STAR_COUNT} {config.STAR_EMOJI}")
        if created:
            report.append(f"{stars.mention} — зал славы (ставь {config.STAR_EMOJI} на крутые сообщения)")

    # --- Голосовые: счётчик, личные комнаты ---
    if on("server_stats") and not any(v.name.startswith(config.STATS_PREFIX) for v in g.voice_channels):
        cat = await voice.get()
        counter = await cat.create_voice_channel(
            f"{config.STATS_PREFIX}{len([m for m in g.members if not m.bot])}",
            overwrites={**child_overwrites(cat), everyone: discord.PermissionOverwrite(connect=False)})
        await counter.move(beginning=True)
        report.append("👥 Счётчик участников")
    rooms_ch = None
    if on("voice_rooms"):
        rooms_ch = utils.rooms_panel_channel(g)
        if rooms_ch is None:
            rooms_ch, _ = await ensure_text(voice, config.CH_ROOMS_PANEL, readonly_for=[everyone],
                                            topic="Кнопки управления своей голосовой комнатой")
            report.append(f"{rooms_ch.mention} — управление личными комнатами")
        if not discord.utils.get(g.voice_channels, name=config.VOICE_CREATOR):
            creator = await ensure_voice(voice, config.VOICE_CREATOR)
            await db.execute("INSERT OR IGNORE INTO voice_creators (channel_id) VALUES (?)", (creator.id,))
            report.append(f"🔊 «{config.VOICE_CREATOR}» — зайди, и бот создаст тебе личную комнату")
        # все «・Создать канал» на сервере работают через этого бота
        added = 0
        for vc in g.voice_channels:
            if (vc.name.endswith("Создать канал") or vc.name == config.VOICE_CREATOR) and not await db.fetchone(
                    "SELECT 1 FROM voice_creators WHERE channel_id=?", (vc.id,)):
                await db.execute("INSERT INTO voice_creators (channel_id) VALUES (?)", (vc.id,))
                added += 1
        if added:
            report.append(f"🔊 «Создать канал» теперь работает через бота: {added} шт.")

    # --- 18+ каналы для девочек и мальчиков (пол + 18 лет по ДР, проверка только ботом) ---
    if on("adult_channels"):
        for name, role_name, topic in (
                (config.CH_GIRLS, config.ROLE_GIRLS_18, "Только для девочек 18+. Мальчикам вход строго запрещён."),
                (config.CH_BOYS, config.ROLE_BOYS_18, "Только для мальчиков 18+. Девочкам вход строго запрещён.")):
            role = discord.utils.get(g.roles, name=role_name)
            if not discord.utils.get(g.text_channels, name=name):
                ch = await (await main.get()).create_text_channel(name, topic=topic, overwrites={
                    everyone: discord.PermissionOverwrite(view_channel=False),
                    role: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                                      embed_links=True, read_message_history=True)})
                if general.category == ch.category:
                    await ch.move(after=general)
                report.append(f"{ch.mention} — для {role_name}")

    # --- Отделы ---
    mini_roles = []
    for game in config.GAMES:
        game_role = await ensure_role(g, game["role"], hoist=True)
        mini = await ensure_role(g, config.admin_role_name(game["name"]), colour=MINI_ADMIN_COLOUR)
        mini_roles.append(mini)
        for extra in game.get("extra_roles", []):
            await ensure_role(g, extra)

        if "category_id" in game:
            cat = g.get_channel(game["category_id"])
            if not isinstance(cat, discord.CategoryChannel):
                report.append(f"⚠️ Категория {game['name']} не найдена (id {game['category_id']})")
                continue
            changed = await add_overwrite(cat, mini, MINI_ADMIN)
            for ch in cat.channels:
                if not is_private(ch, everyone, game_role):
                    changed |= await add_overwrite(ch, mini, MINI_ADMIN)
            if changed:
                report.append(f"{game['emoji']} {game['name']}: добавлены права для «{mini.name}» (остальное не тронуто)")
        else:
            overwrites = {everyone: hidden, game_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                          mini: MINI_ADMIN, base: hidden}
            existed = discord.utils.get(g.categories, name=game["category"]) is not None
            cat = await ensure_category(g, game["category"], overwrites)
            e = game["emoji"]
            await ensure_text(cat, f"{e}・новости", readonly_for=[game_role])
            await ensure_text(cat, f"{e}・чат")
            await ensure_text(cat, f"{e}・скриншоты")
            creator = await ensure_voice(cat, f"{e}・Создать канал")
            await db.execute("INSERT OR IGNORE INTO voice_creators (channel_id) VALUES (?)", (creator.id,))
            for ch in cat.channels:
                await add_overwrite(ch, mini, MINI_ADMIN)
            if not existed:
                report.append(f"{e} {game['name']}: создана категория с каналами")

    # --- Семья: заявки в семью, probation, HR ---
    fam_apply = None
    if on("family"):
        family_roles = []
        for name, colour, _ in config.FAMILY_ROLES:
            if not discord.utils.get(g.roles, name=name):
                report.append(f"🧡 Роль «{name}»")
            family_roles.append(await ensure_role(g, name, colour=discord.Colour(colour), hoist=True))
        probation_role = await ensure_role(g, config.ROLE_FAMILY_PROBATION, colour=discord.Colour(0xFFB347))
        family_member = await ensure_role(g, config.ROLE_FAMILY_MEMBER, colour=discord.Colour(0xE67E22))
        fam_cat = discord.utils.get(g.categories, name=config.CAT_FAMILY)
        if fam_cat is None:
            after = g.get_channel(config.FAMILY_AFTER_CATEGORY_ID) if config.FAMILY_AFTER_CATEGORY_ID else None
            fam_cat = await g.create_category(config.CAT_FAMILY, overwrites={
                everyone: hidden, **{r: visible for r in family_roles}},
                position=(after.position + 1) if after else None, reason="/setup: семья")
            report.append(f"🧡 Категория семьи {config.FAMILY_NAME}: заявка, заявки, испытательный срок, HR")
        fam_apply, created = await ensure_text(fam_cat, config.CH_FAMILY_APPLY,
                                               topic=f"Заявка в семью {config.FAMILY_NAME} — нажми кнопку")
        if created:
            await fam_apply.edit(overwrites={**child_overwrites(fam_cat),
                                             everyone: discord.PermissionOverwrite(view_channel=True, **READONLY)})
        await ensure_text(fam_cat, config.CH_FAMILY_REQUESTS, topic="Заявки в семью — обсуждаем в тредах, голосуем ✅/❌")
        probation_ch, created = await ensure_text(fam_cat, config.CH_FAMILY_PROBATION,
                                                  topic=f"Испытательный срок новичков семьи — "
                                                        f"{config.FAMILY_PROBATION_DAYS} дн.")
        if created:
            await probation_ch.edit(overwrites={**child_overwrites(fam_cat), probation_role: visible,
                                                family_member: visible})
        await ensure_text(fam_cat, config.CH_FAMILY_HR, topic="Чат HR")
        await ensure_text(fam_cat, config.CH_FAMILY_HR_REPORTS, topic="Отчёты HR")

    # --- Заявки в состав ---
    apply_ch = None
    if on("applications"):
        reviewers = [r for r in g.roles if r.name in config.APPLY_REVIEWERS]
        apply_cat = discord.utils.get(g.categories, name=config.CAT_APPLY)
        if apply_cat is None:
            apply_cat = await g.create_category(config.CAT_APPLY, overwrites={everyone: discord.PermissionOverwrite()},
                                                reason="/setup: заявки в состав")
            report.append("📝 Заявки в состав: подать заявку, заявки на рассмотрении, ожидание обзвона")
        apply_ch, _ = await ensure_text(apply_cat, config.CH_APPLY, readonly_for=[everyone],
                                        topic="Заявка в модераторы или администраторы")
        if discord.utils.get(g.text_channels, name=config.CH_APPLY_REVIEW) is None:
            await apply_cat.create_text_channel(config.CH_APPLY_REVIEW, topic="Анкеты кандидатов — только высший состав",
                                                overwrites={everyone: hidden, **{r: visible for r in reviewers}})
        if not discord.utils.get(g.voice_channels, name=config.VC_APPLY):
            await apply_cat.create_voice_channel(config.VC_APPLY, overwrites={
                everyone: discord.PermissionOverwrite(connect=True, speak=True),
                **{r: discord.PermissionOverwrite(mute_members=True, move_members=True) for r in reviewers}})

    # --- Кинотеатр ---
    afisha = wishlist = None
    if on("cinema"):
        await ensure_role(g, config.ROLE_CINEMA, colour=discord.Colour(0xE50914))
        cinema_cat = discord.utils.get(g.categories, name=config.CAT_CINEMA)
        if cinema_cat is None:
            cinema_cat = await g.create_category(config.CAT_CINEMA, overwrites={everyone: discord.PermissionOverwrite()},
                                                 position=(await main.get()).position + 1, reason="/setup: кинотеатр")
            report.append("🎬 Кинотеатр: афиша, подборка фильмов и кинозал")
        afisha, _ = await ensure_text(cinema_cat, config.CH_CINEMA_AFISHA, readonly_for=[everyone],
                                      topic="Анонсы фильмов и напоминания. 🔔 — подписаться на уведомления")
        wishlist, _ = await ensure_text(cinema_cat, config.CH_CINEMA_WISHLIST, readonly_for=[everyone],
                                        topic="Предлагай фильмы — без повторов, потом голосуем 🍿")
        if wishlist.category == afisha.category and wishlist.position < afisha.position:
            await wishlist.move(after=afisha)
        if not discord.utils.get(g.voice_channels, name=config.VC_CINEMA):
            await cinema_cat.create_voice_channel(config.VC_CINEMA, overwrites={
                everyone: discord.PermissionOverwrite(connect=True, speak=True, stream=False),
                staff: discord.PermissionOverwrite(stream=True, priority_speaker=True, mute_members=True)})

    # --- Обязательная анкета: 🔒 Анкета видит только старт и правила ---
    pending = await ensure_role(g, config.ROLE_PENDING, colour=discord.Colour.dark_grey())
    locked = discord.PermissionOverwrite(view_channel=False)
    open_ro = discord.PermissionOverwrite(view_channel=True, read_message_history=True, **READONLY)
    gated = 0
    for ch in g.channels:
        if ch.id in (welcome.id, joins.id, rules.id):
            gated += await add_overwrite(ch, pending, open_ro)
        elif ch.overwrites_for(everyone).view_channel is not False:  # закрытые и так не видны
            gated += await add_overwrite(ch, pending, locked)
    if gated:
        report.append(f"🔒 Обязательная анкета: новичкам закрыто {gated} каналов до заполнения")

    # --- Админка ---
    admin_cat = await ensure_category(g, config.CAT_ADMIN, {everyone: hidden, staff: visible})
    panel, _ = await ensure_text(admin_cat, config.CH_ADMIN_PANEL, readonly_for=[staff])
    mini_panel, _ = await ensure_text(admin_cat, config.CH_MINI_PANEL)
    chat, _ = await ensure_text(admin_cat, config.CH_ADMIN_CHAT)
    await ensure_text(admin_cat, config.CH_ADMIN_LOG, readonly_for=[staff])
    ro_visible = discord.PermissionOverwrite(view_channel=True, **READONLY)
    await mini_panel.edit(overwrites={**child_overwrites(admin_cat, [staff]), **{r: ro_visible for r in mini_roles}})
    await chat.edit(overwrites={**child_overwrites(admin_cat), **{r: visible for r in mini_roles}})
    # Главный модератор видит всю админку (в каналах с кнопками — только читает, как и Администрация)
    button_channels = {config.CH_ADMIN_PANEL, config.CH_MINI_PANEL, config.CH_ADMIN_LOG, config.CH_MOD_PANEL}
    if on("levels"):
        await ensure_text(admin_cat, config.CH_RATINGS, readonly_for=[staff],
                          topic="Как получить достижения + таблицы достижений и уровней (обновляется само)")
        button_channels.add(config.CH_RATINGS)
    cinema_setup = None
    if on("cinema"):
        await ensure_text(admin_cat, config.CH_CINEMA_TALK, topic="Обсуждаем, что смотреть 🍿")
        cinema_setup, _ = await ensure_text(admin_cat, config.CH_CINEMA_SETUP, readonly_for=[staff],
                                            topic="Кнопки настройки кинотеатра")
        button_channels.add(config.CH_CINEMA_SETUP)
    # Модераторы видят только свои два канала (+ им видна админка через Главного модератора/Администрацию)
    mod_panel, _ = await ensure_text(admin_cat, config.CH_MOD_PANEL, readonly_for=[staff],
                                     topic="Кнопки модератора: предупреждения, тайм-ауты, история")
    mod_chat, _ = await ensure_text(admin_cat, config.CH_MOD_CHAT, topic="Общение модераторов")
    await add_overwrite(mod_panel, mod, ro_visible)
    await add_overwrite(mod_chat, mod, visible)
    await add_overwrite(admin_cat, head_mod, visible)
    for ch in admin_cat.channels:
        await add_overwrite(ch, head_mod, ro_visible if ch.name in button_channels else visible)
    if admin_cat.position < max(c.position for c in g.categories):
        await admin_cat.edit(position=max(c.position for c in g.categories) + 1)

    # --- Панели ---
    from cogs.admin_panel import post_admin_panel
    from cogs.mini_panel import post_mini_panel
    from cogs.mod_panel import post_mod_panel
    from cogs.onboarding import post_panels
    await post_panels(bot, welcome)
    await post_admin_panel(bot, panel)
    await post_mini_panel(bot, mini_panel)
    await post_mod_panel(bot, mod_panel)
    if apply_ch:
        from cogs.applications import post_apply_panel
        await post_apply_panel(bot, apply_ch)
    if fam_apply:
        from cogs.family import post_family_panel
        await post_family_panel(bot, fam_apply)
    if afisha and cinema_setup:
        from cogs.cinema import post_cinema_panels
        from cogs.films import post_wishlist_panel
        await post_cinema_panels(bot, afisha, cinema_setup)
        await post_wishlist_panel(bot, wishlist)
    if ideas:
        from cogs.community import post_ideas_panel
        await post_ideas_panel(bot, ideas)
    if rooms_ch:
        from cogs.voice_rooms import post_room_panel
        await post_room_panel(bot, rooms_ch)
    if ratings := bot.get_cog("Ratings"):
        await ratings.update(g)
    await perms.sync_panel_access(g)
    report.append("Панели обновлены")

    # --- Встроенная анкета Discord: все игры в вопросе «В какие игры вы играете?» ---
    report.extend(await sync_discord_onboarding(g, [joins, welcome]))

    # --- Порядок ролей ---
    report.extend(await arrange_roles(g))

    blocked = [r.name for r in bot_managed_roles(g) if r >= g.me.top_role]
    if blocked:
        report.append(f"⚠️ Роль бота ниже ролей: {', '.join(blocked)}. Подними роль бота выше них "
                      "(Настройки сервера → Роли), иначе бот не сможет их выдавать")
    return report


GAMES_PROMPT_TITLE = "В какие игры вы играете? После выбора вы получите доступ к соответствующим каналам."


async def sync_discord_onboarding(g: discord.Guild, must_see: list) -> list[str]:
    """Встроенная анкета Discord: недостающие игры в «В какие игры вы играете?» и наши каналы
    (старт, новички) — в каналы по умолчанию, иначе новичок их не увидит в списке."""
    try:
        ob = await g.onboarding()
    except discord.HTTPException:
        return []
    report = []
    defaults = list(ob.default_channels)
    missing = [c for c in must_see if c.id not in {d.id for d in defaults}]
    if missing:
        try:
            await g.edit_onboarding(default_channels=defaults + missing, reason="/setup: каналы по умолчанию")
            report.append(f"🧭 Анкета Discord: каналы по умолчанию + {', '.join(c.mention for c in missing)}")
        except discord.HTTPException as e:
            report.append(f"⚠️ Не смог добавить каналы в анкету Discord: {e}")
    prompts = list(ob.prompts)
    prompt = next((p for p in prompts if "игры" in p.title.lower()), None)
    if prompt is None:
        prompt = discord.OnboardingPrompt(type=discord.OnboardingPromptType.multiple_choice,
                                          title=GAMES_PROMPT_TITLE, options=[], single_select=False,
                                          required=False, in_onboarding=False)
        prompts.append(prompt)
    have = {rid for o in prompt.options for rid in o.role_ids}
    added = []
    for game in config.GAMES:
        role = discord.utils.get(g.roles, name=game["role"])
        if role and role.id not in have:
            prompt.options.append(discord.OnboardingPromptOption(title=game["name"], emoji=game["emoji"], roles=[role]))
            added.append(game["name"])
    if not added:
        return report
    try:
        await g.edit_onboarding(prompts=prompts, reason="/setup: все игры в анкете Discord")
        report.append(f"🧭 Анкета Discord: добавлены игры {', '.join(added)}")
    except discord.HTTPException as e:
        report.append(f"⚠️ Не смог обновить игры в анкете Discord: {e}")
    return report


async def arrange_roles(g: discord.Guild) -> list[str]:
    """Расставляет роли (всё, что ниже роли бота): администрация → mini Admin → именинник → пол → боты →
    уровни → достижения → игры → киноман → 👻 → 🔒. Неизвестные роли — внизу, в прежнем порядке."""
    me = g.me.top_role
    below = [r for r in sorted(g.roles, key=lambda r: -r.position) if r < me and not r.is_default()]

    def named(*names):
        return [r for n in names if (r := discord.utils.get(below, name=n))]

    family = [n for n, *_ in config.FAMILY_ROLES]
    order = named(*family[:2])  # основатель семьи и его правая рука — на самом верху
    order += named(config.ROLE_HEAD_ADMIN, "Админ", config.ROLE_HEAD_MOD, config.ROLE_STAFF, config.ROLE_MOD)
    order += named(*(config.admin_role_name(gm["name"]) for gm in config.GAMES))
    order += named(*family[2:])  # Старший HR → HR Manager → Ответственный
    order += named(config.ROLE_BIRTHDAY)
    order += named(*(n for n, _ in config.CUSTOM_ROLES))
    known = set(config.STAFF_ROLES | config.MOD_ROLES) | {config.ROLE_BASE, config.ROLE_PENDING, config.ROLE_CINEMA,
            config.ROLE_GIRLS_18, config.ROLE_BOYS_18, config.ROLE_FAMILY_PROBATION, config.ROLE_BIRTHDAY,
            *config.LEVEL_ROLES.values(), *(a["role"] for a in config.ACHIEVEMENTS), *(r for r, *_ in config.GENDERS),
            *(n for gm in config.GAMES for n in config.dept_roles(gm)), *(n for n, *_ in config.FAMILY_ROLES),
            *(config.admin_role_name(gm["name"]) for gm in config.GAMES)}
    shop = set(config.SHOP_ROLES)
    order += [r for r in below if not r.managed and r.name not in known | shop and r not in order]  # созданные вручную
    order += named(*(r for r, *_ in config.GENDERS))
    order += [r for r in below if r.managed and not r.is_premium_subscriber()   # роли ботов
              and r.name not in config.LIMITED_BOT_ROLES]
    order += named(*(config.LEVEL_ROLES[k] for k in sorted(config.LEVEL_ROLES, reverse=True)))
    order += named(*(a["role"] for a in reversed(config.ACHIEVEMENTS)))
    order += named(*(n for gm in config.GAMES for n in config.dept_roles(gm)))
    order += named(config.ROLE_FAMILY_PROBATION)
    order += named(config.ROLE_CINEMA, config.ROLE_GIRLS_18, config.ROLE_BOYS_18, config.ROLE_BASE, config.ROLE_PENDING)
    order += [r for r in below if r not in order and r.name not in config.LIMITED_BOT_ROLES and r.name not in shop]
    # в самом низу: роли «ограниченных» ботов (Akemi), под ними — только роли их магазина
    order += named(*config.LIMITED_BOT_ROLES)
    order += named(*config.SHOP_ROLES)
    positions = {r: me.position - 1 - i for i, r in enumerate(order)}
    if all(r.position == p for r, p in positions.items()):
        return []
    await g.edit_role_positions(positions, reason="/setup: порядок ролей")
    return ["🎭 Роли расставлены по иерархии"]


def bot_managed_roles(g: discord.Guild) -> list[discord.Role]:
    """Роли, которые бот выдаёт сам: база, пол, игры, отделы, уровни, Администрация."""
    names = {config.ROLE_BASE, config.ROLE_PENDING, config.ROLE_STAFF, config.ROLE_MOD, config.ROLE_BIRTHDAY, config.ROLE_CINEMA, config.ROLE_GIRLS_18, config.ROLE_BOYS_18, config.ROLE_FAMILY_PROBATION, *(n for n, *_ in config.FAMILY_ROLES),
             *config.LEVEL_ROLES.values(), *(a["role"] for a in config.ACHIEVEMENTS), *(r for r, *_ in config.GENDERS)}
    for game in config.GAMES:
        names.update(config.dept_roles(game))
        names.add(config.admin_role_name(game["name"]))
    return [r for r in g.roles if r.name in names]


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerSetup(bot))
