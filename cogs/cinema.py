"""Кинотеатр: сеансы, анонс (10:00 / 13:00 / 18:00), напоминания, старт в «🎬・Кинозал» с активностью «Смотрим вместе».
Боты Discord не умеют сами показывать видео (демонстрация экрана — только у людей), поэтому на старте бот
открывает встроенную активность «Смотрим вместе» (YouTube) и даёт ссылку на фильм для других платформ.
Настройка — кнопками в #🎬・кино-настройки (админка)."""
import datetime
import logging
import os
import re

import aiohttp

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import db
import perms

COLOUR = discord.Colour(0xE50914)
# Свой кинозал (приложение внутри Discord, cinema/): адрес сайта и секрет, чтобы бот мог сообщать ему фильм
KINOZAL_URL = (os.getenv("KINOZAL_URL") or "").rstrip("/")
KINOZAL_SECRET = os.getenv("KINOZAL_SECRET") or ""
YOUTUBE = re.compile(r"(youtube\.com|youtu\.be)/", re.I)


def kinozal_ready() -> bool:
    return bool(KINOZAL_URL and KINOZAL_SECRET)


async def kinozal_set(voice: discord.VoiceChannel, url: str, title: str) -> bool:
    """Сообщить кинозалу, какой фильм показывать в этом голосовом канале."""
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{KINOZAL_URL}/api/now?channel={voice.id}", json={"url": url, "title": title},
                                 headers={"Authorization": f"Bearer {KINOZAL_SECRET}"},
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status == 200
    except Exception:
        log.exception("Кинозал не ответил")
        return False


def kinozal_web(voice: discord.VoiceChannel) -> str:
    """Тот же кинозал в обычном браузере: работает на любом сервере, без проверки приложения в Discord.
    Комната — по каналу, поэтому зрители в браузере и в Discord смотрят вместе."""
    return f"{KINOZAL_URL}/?room=ch-{voice.id}&channel={voice.id}"


def kinozal_buttons(view: discord.ui.View, voice: discord.VoiceChannel, invite: str | None):
    if invite:
        view.add_item(discord.ui.Button(label="Смотреть в Discord", emoji="🍿", url=invite))
    view.add_item(discord.ui.Button(label="Смотреть в браузере", emoji="🌐", url=kinozal_web(voice)))


async def kinozal_invite(bot: commands.Bot, voice: discord.VoiceChannel) -> str | None:
    """Ссылка, по которой кинозал открывается прямо в голосовом канале."""
    try:
        invite = await voice.create_invite(max_age=6 * 3600, target_type=discord.InviteTarget.embedded_application,
                                           target_application_id=bot.application_id, reason="Кино: кинозал")
        return invite.url
    except discord.HTTPException:
        log.exception("Не удалось открыть кинозал — включены ли Activities у приложения бота?")
        return None
log = logging.getLogger("cinema")
GONE = 30        # через сколько секунд исчезают ответы бота
MENU_GONE = 300  # меню, списки и предпросмотр — дольше, чтобы успеть выбрать
DEFAULTS = {
    "cinema_slots": "10:00,13:00,18:00",  # анонс — в ближайшее из этих времён после добавления сеанса
    "cinema_reminders": "60,10",
    "cinema_text_morning": ("🍿 **Сегодня кино!**\n\n🎬 **{film}**\n🕒 Начало в **{time}**\n{desc}\n\n"
                            "Сбор в {voice}. Хочешь напоминание — нажми «🔔 Уведомлять меня» ниже."),
    "cinema_text_reminder": "⏰ {role} До начала **{film}** осталось **{left}**! Сбор в {voice} 🍿",
    "cinema_text_start": ("🎬 **{film}** начинается! Заходи в {voice}\n\n"
                          "▶️ Жми кнопку ниже — фильм откроется прямо в Discord, у всех одновременно.\n{link}"),
}
TEXT_KEYS = {"cinema_text_morning": "📣 Анонс", "cinema_text_reminder": "⏰ Напоминание",
             "cinema_text_start": "🎬 Начало сеанса"}
PLACEHOLDERS = ("{film} — название · {time} — время · {date} — дата · {desc} — описание · {link} — ссылка · "
                "{left} — сколько осталось · {voice} — кинозал · {role} — пинг киноманов")


async def setting(guild_id: int, key: str) -> str:
    return await db.get_setting(guild_id, key, DEFAULTS[key])


def channels(guild: discord.Guild):
    return (discord.utils.get(guild.text_channels, name=config.CH_CINEMA_AFISHA),
            discord.utils.get(guild.voice_channels, name=config.VC_CINEMA),
            discord.utils.get(guild.roles, name=config.ROLE_CINEMA))


def fmt_left(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        h = minutes // 60
        return f"{h} час" + ("" if h == 1 else ("а" if h < 5 else "ов"))
    return f"{minutes} мин"


async def render(guild: discord.Guild, key: str, s: dict, left: int | None = None) -> str:
    afisha, voice, role = channels(guild)
    start = datetime.datetime.fromtimestamp(s["start_ts"], config.TIMEZONE)
    text = await setting(guild.id, key)
    return text.format_map(SafeDict(
        film=s["title"], time=config.tz(start.strftime("%H:%M")), date=start.strftime("%d.%m"),
        desc=s["description"] or "", link=s["link"] or "", left=fmt_left(left) if left else "",
        voice=voice.mention if voice else "кинозал", role=role.mention if role else "",
        afisha=afisha.mention if afisha else "афиша"))


async def with_card(guild: discord.Guild, s: dict, embed: discord.Embed, badge: str) -> list[discord.File]:
    """Картинка фильма (как карточка в подборке) в пост афиши. Не получилось нарисовать — пост без картинки."""
    try:
        from cogs import films
        file, f = await films.session_card(guild, s["title"], badge)
    except Exception:
        log.exception("Не удалось нарисовать карточку фильма для афиши")
        return []
    if f and f["description"] and not s["description"]:
        embed.description += "\n\n📝 " + f["description"][:700]
    embed.set_image(url="attachment://film.png")
    return [file]


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def row_to_session(r) -> dict:
    keys = ("id", "guild_id", "title", "start_ts", "link", "description", "morning_sent", "reminders_sent",
            "started", "event_id", "created_ts")
    return dict(zip(keys, r))


async def sessions(guild_id: int, upcoming_only: bool = True) -> list[dict]:
    q = "SELECT * FROM cinema_sessions WHERE guild_id=?" + (" AND started=0" if upcoming_only else "")
    return [row_to_session(r) for r in await db.fetchall(q + " ORDER BY start_ts", (guild_id,))]


def parse_slots(text: str) -> list[tuple[int, int]]:
    slots = []
    for part in text.replace(" ", "").split(","):
        if part:
            h, m = map(int, part.split(":"))
            datetime.time(h, m)  # проверка, что время настоящее
            slots.append((h, m))
    if not slots:
        raise ValueError("пусто")
    return sorted(slots)


def announce_time(s: dict, slots: list[tuple[int, int]]) -> datetime.datetime:
    """Анонс — в первое время из slots в день сеанса, не раньше момента добавления.
    Если все времена уже прошли или наступают позже начала фильма — сразу."""
    start = datetime.datetime.fromtimestamp(s["start_ts"], config.TIMEZONE)
    day_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    base = max(datetime.datetime.fromtimestamp(s.get("created_ts") or 0, config.TIMEZONE), day_start)
    for h, m in slots:
        t = day_start.replace(hour=h, minute=m)
        if t >= base:
            return t if t < start else base
    return base


def parse_start(date_s: str, time_s: str) -> datetime.datetime:
    try:
        return _parse_start(date_s, time_s)
    except ValueError as e:
        if any(w in str(e) for w in ("must be", "out of range")):
            raise ValueError("Такой даты или времени не бывает 🤔") from e
        raise


def _parse_start(date_s: str, time_s: str) -> datetime.datetime:
    now = datetime.datetime.now(config.TIMEZONE)
    m = re.fullmatch(r"\s*(\d{1,2})[.:](\d{2})\s*", time_s)
    if not m:
        raise ValueError("Время пиши так: 20:30")
    hh, mm = int(m[1]), int(m[2])
    if date_s.strip():
        d = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s*", date_s)
        if not d:
            raise ValueError("Дату пиши так: 25.10 или 25.10.2026")
        year = int(d[3]) if d[3] else now.year
        year += 2000 if year < 100 else 0
        start = datetime.datetime(year, int(d[2]), int(d[1]), hh, mm, tzinfo=config.TIMEZONE)
        if not d[3] and start < now:
            start = start.replace(year=year + 1)
    else:
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if start <= now:
        raise ValueError("Это время уже прошло")
    return start


# ---------- Публичная часть: кнопки в афише ----------
class AfishaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Уведомлять меня", emoji="🔔", style=discord.ButtonStyle.success, custom_id="cinema:notify")
    async def notify(self, interaction: discord.Interaction, _):
        role = discord.utils.get(interaction.guild.roles, name=config.ROLE_CINEMA)
        if not role:
            return await interaction.response.send_message("Роль не найдена — админ должен запустить /setup",
                                                           ephemeral=True, delete_after=GONE)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Отписался от кино")
            text = "🔕 Больше не буду звать тебя на кино"
        else:
            await interaction.user.add_roles(role, reason="Подписался на кино")
            text = "🔔 Готово! Напомню перед каждым сеансом 🍿"
        await interaction.response.send_message(text, ephemeral=True, delete_after=GONE)

    @discord.ui.button(label="Расписание", emoji="📅", custom_id="cinema:schedule")
    async def schedule(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(embed=await schedule_embed(interaction.guild), ephemeral=True, delete_after=MENU_GONE)

    @discord.ui.button(label="Подборка", emoji="🍿", custom_id="cinema:wishlist")
    async def wishlist(self, interaction: discord.Interaction, _):
        from cogs import films
        g = interaction.guild
        ch = discord.utils.get(g.text_channels, name=config.CH_CINEMA_WISHLIST)
        await interaction.response.send_message(
            f"Предложить фильм можно в {ch.mention if ch else 'подборке'} 👇",
            embeds=films.list_embeds(await films.films(g.id), [])[:5], ephemeral=True, delete_after=MENU_GONE)


async def schedule_embed(guild: discord.Guild) -> discord.Embed:
    items = await sessions(guild.id)
    lines = [f"🎬 **{s['title']}** — <t:{s['start_ts']}:F> (<t:{s['start_ts']}:R>)" for s in items[:15]]
    return discord.Embed(title="📅 Расписание кино", description="\n".join(lines) or "Пока сеансов нет",
                         colour=COLOUR)


# ---------- Админская панель ----------
class AddSessionModal(discord.ui.Modal, title="➕ Новый сеанс"):
    film = discord.ui.TextInput(label="Название фильма", max_length=100)
    date = discord.ui.TextInput(label="Дата (ДД.ММ) — пусто = сегодня", required=False, max_length=10,
                                placeholder="25.10")
    time = discord.ui.TextInput(label=config.tz("Время начала"), max_length=5, placeholder="20:30")
    link = discord.ui.TextInput(label="Ссылка: видеофайл, Яндекс Диск или YouTube", required=False, max_length=400)
    desc = discord.ui.TextInput(label="Описание (необязательно)", style=discord.TextStyle.paragraph,
                                required=False, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start = parse_start(self.date.value, self.time.value)
        except ValueError as e:
            return await interaction.response.send_message(f"⚠️ {e}", ephemeral=True, delete_after=GONE)
        await interaction.response.defer(ephemeral=True, thinking=True)
        g = interaction.guild
        _, voice, _ = channels(g)
        event_id = None
        if voice:
            try:
                event = await g.create_scheduled_event(
                    name=f"🎬 {self.film.value}"[:100], start_time=start, channel=voice,
                    entity_type=discord.EntityType.voice, privacy_level=discord.PrivacyLevel.guild_only,
                    description=((self.desc.value or "") + (f"\n\n🔗 {self.link.value}" if self.link.value else ""))[:1000]
                    or None, reason=f"Кино, добавил {interaction.user}")
                event_id = event.id
            except discord.HTTPException:
                pass
        created = int(discord.utils.utcnow().timestamp())
        await db.execute("INSERT INTO cinema_sessions (guild_id, title, start_ts, link, description, event_id, "
                         "created_ts) VALUES (?,?,?,?,?,?,?)",
                         (g.id, self.film.value, int(start.timestamp()), self.link.value.strip(),
                          self.desc.value.strip(), event_id, created))
        from cogs import films  # ИИ заранее найдёт описание и обложку для поста в афише
        await films.prepare_session_film(g, self.film.value)
        announce = announce_time({"start_ts": int(start.timestamp()), "created_ts": created},
                                 parse_slots(await setting(g.id, "cinema_slots")))
        await films.done(interaction, f"✅ Сеанс **{self.film.value}** — <t:{int(start.timestamp())}:F>"
                         f"\n📣 Анонс в афише: <t:{int(announce.timestamp())}:F>"
                         + ("\n📅 Событие создано во вкладке «Мероприятия»" if event_id else ""), 60)
        from cogs.admin_panel import log_action
        await log_action(g, f"🎬 {interaction.user.mention} добавил сеанс **{self.film.value}** "
                            f"на <t:{int(start.timestamp())}:F>")


class DeleteSessionView(discord.ui.View):
    def __init__(self, items: list[dict]):
        super().__init__(timeout=300)
        self.pick.options = [discord.SelectOption(
            label=s["title"][:100], value=str(s["id"]),
            description=datetime.datetime.fromtimestamp(s["start_ts"], config.TIMEZONE).strftime("%d.%m %H:%M"))
            for s in items[:25]]

    @discord.ui.select(placeholder="🗑️ Удалить сеанс…", options=[discord.SelectOption(label="-")])
    async def pick(self, interaction: discord.Interaction, select):
        sid = int(select.values[0])
        row = await db.fetchone("SELECT title, event_id FROM cinema_sessions WHERE id=?", (sid,))
        if row and row[1]:
            try:
                ev = await interaction.guild.fetch_scheduled_event(row[1])
                await ev.cancel()
            except discord.HTTPException:
                pass
        await db.execute("DELETE FROM cinema_sessions WHERE id=?", (sid,))
        await interaction.response.edit_message(content=f"🗑️ Сеанс **{row[0] if row else sid}** удалён", embed=None,
                                                view=None)


class TextModal(discord.ui.Modal):
    def __init__(self, key: str, current: str):
        super().__init__(title=f"✏️ {TEXT_KEYS[key]}"[:45])
        self.key = key
        self.text = discord.ui.TextInput(label="Текст (можно {film}, {time} и др.)", style=discord.TextStyle.paragraph,
                                         default=current, max_length=1800)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        await db.set_setting(interaction.guild.id, self.key, self.text.value)
        await interaction.response.send_message(f"✅ Текст «{TEXT_KEYS[self.key]}» сохранён", ephemeral=True, delete_after=GONE)


class TextPickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Какой текст изменить?",
                       options=[discord.SelectOption(label=v, value=k) for k, v in TEXT_KEYS.items()] +
                               [discord.SelectOption(label="↩️ Вернуть все тексты по умолчанию", value="reset")])
    async def pick(self, interaction: discord.Interaction, select):
        key = select.values[0]
        if key == "reset":
            for k in TEXT_KEYS:
                await db.set_setting(interaction.guild.id, k, DEFAULTS[k])
            return await interaction.response.send_message("↩️ Тексты сброшены", ephemeral=True, delete_after=GONE)
        await interaction.response.send_modal(TextModal(key, await setting(interaction.guild.id, key)))


class TimesModal(discord.ui.Modal, title="⏰ Время анонсов"):
    slots = discord.ui.TextInput(label="Анонсы: утро, обед, вечер (через запятую)", max_length=40)
    reminders = discord.ui.TextInput(label="Напоминания: за сколько минут (через запятую)", max_length=50)

    def __init__(self, slots: str, reminders: str):
        super().__init__()
        self.slots.default, self.reminders.default = slots, reminders

    async def on_submit(self, interaction: discord.Interaction):
        try:
            slots_text = ",".join(f"{h:02}:{m:02}" for h, m in parse_slots(self.slots.value))
        except ValueError:
            return await interaction.response.send_message("⚠️ Время пиши так: 10:00,13:00,18:00", ephemeral=True, delete_after=GONE)
        try:
            mins = sorted({int(x) for x in self.reminders.value.replace(" ", "").split(",") if x}, reverse=True)
        except ValueError:
            return await interaction.response.send_message("⚠️ Минуты пиши так: 60,10", ephemeral=True, delete_after=GONE)
        await db.set_setting(interaction.guild.id, "cinema_slots", slots_text)
        await db.set_setting(interaction.guild.id, "cinema_reminders", ",".join(map(str, mins)))
        await interaction.response.send_message(
            f"✅ Анонсы в **{slots_text.replace(',', ', ')}**, напоминания за "
            f"**{', '.join(fmt_left(m) for m in mins) or 'не присылать'}**", ephemeral=True, delete_after=GONE)


class CinemaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not await perms.deny(interaction, "cinema")

    @discord.ui.button(label="Добавить сеанс", emoji="➕", style=discord.ButtonStyle.success, custom_id="cin:add")
    async def add(self, interaction, _):
        await interaction.response.send_modal(AddSessionModal())

    @discord.ui.button(label="Сеансы", emoji="📋", custom_id="cin:list")
    async def list_btn(self, interaction, _):
        items = await sessions(interaction.guild.id)
        extra = {"view": DeleteSessionView(items)} if items else {}  # view=None библиотека не принимает
        await interaction.response.send_message(embed=await schedule_embed(interaction.guild), ephemeral=True,
                                                delete_after=180, **extra)

    @discord.ui.button(label="Тексты", emoji="✏️", custom_id="cin:texts")
    async def texts(self, interaction, _):
        await interaction.response.send_message(
            embed=discord.Embed(title="✏️ Тексты бота", description=f"Можно вставлять:\n{PLACEHOLDERS}", colour=COLOUR),
            view=TextPickView(), ephemeral=True, delete_after=MENU_GONE)

    @discord.ui.button(label="Время", emoji="⏰", custom_id="cin:times")
    async def times(self, interaction, _):
        g = interaction.guild.id
        await interaction.response.send_modal(TimesModal(await setting(g, "cinema_slots"),
                                                         await setting(g, "cinema_reminders")))

    @discord.ui.button(label="Предпросмотр", emoji="👀", custom_id="cin:preview")
    async def preview(self, interaction, _):
        items = await sessions(interaction.guild.id)
        s = items[0] if items else {"title": "Пример фильма", "start_ts": int(discord.utils.utcnow().timestamp()) + 7200,
                                    "description": "Описание фильма", "link": "https://youtube.com/..."}
        g = interaction.guild
        embeds = [discord.Embed(title=TEXT_KEYS[k], description=await render(g, k, s, 10), colour=COLOUR)
                  for k in TEXT_KEYS]
        await interaction.response.send_message("Так будут выглядеть сообщения" +
                                                ("" if items else " (на примере)") + ":", embeds=embeds, ephemeral=True, delete_after=MENU_GONE)

    @discord.ui.button(label="Голосование", emoji="🗳️", style=discord.ButtonStyle.primary, custom_id="cin:vote", row=1)
    async def vote(self, interaction, _):
        from cogs.films import open_vote
        await open_vote(interaction)

    @discord.ui.button(label="Просмотрено", emoji="✅", custom_id="cin:watched", row=1)
    async def watched(self, interaction, _):
        from cogs.films import open_manage
        await open_manage(interaction, "watched")

    @discord.ui.button(label="Удалить из подборки", emoji="🗑️", style=discord.ButtonStyle.danger,
                       custom_id="cin:filmdel", row=1)
    async def film_delete(self, interaction, _):
        from cogs.films import open_manage
        await open_manage(interaction, "delete")

    @discord.ui.button(label="Начать заново", emoji="🧹", style=discord.ButtonStyle.danger, custom_id="cin:fresh", row=2)
    async def fresh(self, interaction, _):
        await interaction.response.send_message(
            "🧹 **Начать заново?** Удалю все сообщения в 🎬・афиша и 🍿・подборка и весь список фильмов "
            "(и «Уже посмотрели»). Сеансы в расписании останутся. Вернуть будет нельзя.",
            view=FreshStartConfirm(), ephemeral=True, delete_after=120)


class FreshStartConfirm(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Да, удалить всё", emoji="🧹", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="🧹 Удаляю… это займёт до минуты.", view=None)
        await fresh_start(interaction.client, interaction.guild)
        await interaction.edit_original_response(content="✅ Готово: афиша и подборка чистые, панели на месте.")


async def fresh_start(bot: commands.Bot, guild: discord.Guild):
    """Начать кино заново: всё из афиши и подборки — удалить, список фильмов — очистить, панели — выложить снова."""
    from cogs import films
    afisha = discord.utils.get(guild.text_channels, name=config.CH_CINEMA_AFISHA)
    wishlist = discord.utils.get(guild.text_channels, name=config.CH_CINEMA_WISHLIST)
    setup_ch = discord.utils.get(guild.text_channels, name=config.CH_CINEMA_SETUP)
    for ch in (afisha, wishlist):
        if ch:
            await ch.purge(limit=None, reason="Кино: начать заново")
    await db.execute("DELETE FROM films WHERE guild_id=?", (guild.id,))
    if afisha and setup_ch:
        await post_cinema_panels(bot, afisha, setup_ch)
    if wishlist:
        await films.post_panel(bot, wishlist)
    log.info("Кино начато заново на сервере %s", guild.name)


def afisha_view(guild: discord.Guild) -> discord.ui.View:
    """Кнопки афиши + ссылка в подборку, где предлагают фильмы."""
    view = AfishaView()
    wishlist = discord.utils.get(guild.text_channels, name=config.CH_CINEMA_WISHLIST)
    if wishlist:
        view.add_item(discord.ui.Button(label="Предложить фильм", emoji="➕", url=wishlist.jump_url))
    return view


async def post_cinema_panels(bot: commands.Bot, afisha: discord.TextChannel, setup_ch: discord.TextChannel):
    for ch in (afisha, setup_ch):
        async for msg in ch.history(limit=30):
            if msg.author == bot.user and msg.components:
                await msg.delete()
    wishlist = discord.utils.get(afisha.guild.text_channels, name=config.CH_CINEMA_WISHLIST)
    where = wishlist.mention if wishlist else "🍿・подборка"
    await afisha.send(embed=discord.Embed(
        title=f"🎬 Кинотеатр {config.SERVER_NAME}",
        description="Смотрим фильмы вместе в 🎬・Кинозал!\n\nАнонсы и напоминания появляются здесь.\n"
                    "🔔 **Уведомлять меня** — пинговать тебя перед каждым сеансом\n📅 **Расписание** — ближайшие сеансы\n"
                    "🍿 **Подборка** — фильмы, которые предложили посмотреть\n\n"
                    f"**➕ Как предложить фильм:** открой {where} (кнопка «Предложить фильм» ниже), нажми "
                    "**➕ Предложить фильм** и напиши название. С ИИ бот покажет похожие варианты — выбираешь "
                    "точный, а год, описание, сезоны и обложку он допишет сам.",
        colour=COLOUR), view=afisha_view(afisha.guild))
    await setup_ch.send(embed=discord.Embed(
        title="⚙️ Настройка кинотеатра",
        description="➕ **Добавить сеанс** — фильм, дата, время, ссылка (создаст событие в «Мероприятиях»)\n"
                    "📋 **Сеансы** — список и удаление\n"
                    "✏️ **Тексты** — что бот пишет утром, в напоминаниях и на старте\n"
                    "⏰ **Время** — когда анонсы и за сколько минут напоминать\n"
                    "📣 Анонс выходит в ближайшее из **10:00 / 13:00 / 18:00** после добавления сеанса: "
                    "добавил до 10 — в 10, до 13 — в 13, до 18 — в 18, позже — сразу\n"
                    "👀 **Предпросмотр** — как будут выглядеть сообщения\n\n"
                    "**🍿 Подборка фильмов**\n"
                    "🗳️ **Голосование** — 1–5 фильмов из подборки (вручную, топ-5 или случайно) → опрос в афише\n"
                    "✅ **Просмотрено** — убрать фильм из подборки в «Уже посмотрели» "
                    "(при старте сеанса с таким же названием бот делает это сам)\n"
                    "🗑️ **Удалить из подборки** — мусор и шутки\n\n"
                    "🧹 **Начать заново** — очистить афишу, подборку и список фильмов\n\n"
                    "ℹ️ На старте сеанса: ссылка на видеофайл или Яндекс Диск — кнопка «🌐 Смотреть в браузере» "
                    "(все смотрят синхронно), YouTube — «Смотрим вместе» прямо в Discord.",
        colour=COLOUR), view=CinemaPanelView())


class Cinema(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(AfishaView())
        bot.add_view(CinemaPanelView())
        self.ticker.start()

    def cog_unload(self):
        self.ticker.cancel()

    async def remote_task(self):
        """Задание с другого ПК (через диспетчер, команда bot_task): runtime/bot_task.txt."""
        path = os.path.join("runtime", "bot_task.txt")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            task = f.read().strip()
        os.remove(path)
        if task == "cinema_fresh_start":
            for guild in self.bot.guilds:
                await fresh_start(self.bot, guild)

    @tasks.loop(seconds=30)
    async def ticker(self):
        await self.remote_task()
        now = datetime.datetime.now(config.TIMEZONE)
        for guild in self.bot.guilds:
            afisha, voice, role = channels(guild)
            if not afisha:
                continue
            slots = parse_slots(await setting(guild.id, "cinema_slots"))
            reminders = [int(x) for x in (await setting(guild.id, "cinema_reminders")).split(",") if x]
            for s in await sessions(guild.id):
                start = datetime.datetime.fromtimestamp(s["start_ts"], config.TIMEZONE)
                mention = discord.AllowedMentions(roles=True)

                if not s["morning_sent"] and now < start and now >= announce_time(s, slots):
                    embed = discord.Embed(description=await render(guild, "cinema_text_morning", s), colour=COLOUR)
                    files = await with_card(guild, s, embed, f"СЕГОДНЯ В {start:%H:%M}")
                    await afisha.send(embed=embed, files=files, view=afisha_view(guild))
                    await db.execute("UPDATE cinema_sessions SET morning_sent=1 WHERE id=?", (s["id"],))

                sent = set(filter(None, s["reminders_sent"].split(",")))
                for m in reminders:
                    due = start - datetime.timedelta(minutes=m)
                    if str(m) in sent or now < due or now >= start:
                        continue
                    if (now - due).total_seconds() <= 300:  # опоздали больше чем на 5 мин — пропускаем
                        await afisha.send(await render(guild, "cinema_text_reminder", s, m), allowed_mentions=mention)
                    sent.add(str(m))
                    await db.execute("UPDATE cinema_sessions SET reminders_sent=? WHERE id=?",
                                     (",".join(sent), s["id"]))

                if now >= start:
                    await self.start_session(guild, s, afisha, voice)

            # завершить события старше 4 часов
            for s in await db.fetchall("SELECT id, event_id FROM cinema_sessions WHERE guild_id=? AND started=1 "
                                       "AND start_ts < ?", (guild.id, int(now.timestamp()) - 4 * 3600)):
                if s[1]:
                    try:
                        ev = await guild.fetch_scheduled_event(s[1])
                        if ev.status == discord.EventStatus.active:
                            await ev.end()
                    except discord.HTTPException:
                        pass
                await db.execute("UPDATE cinema_sessions SET started=2 WHERE id=?", (s[0],))

    async def start_session(self, guild: discord.Guild, s: dict, afisha: discord.TextChannel, voice):
        await db.execute("UPDATE cinema_sessions SET started=1 WHERE id=?", (s["id"],))
        embed = discord.Embed(description=await render(guild, "cinema_text_start", s), colour=COLOUR)
        files = await with_card(guild, s, embed, "НАЧИНАЕМ!")  # до «посмотрели» — карточка ещё золотая
        try:
            from cogs import films  # фильм смотрим — убираем из подборки в «Уже посмотрели»
            await films.watched_now(guild, s["title"])
        except Exception:
            log.exception("Не удалось отметить фильм просмотренным")
        view = discord.ui.View()
        link = s["link"] or ""
        in_kinozal = False
        if voice and kinozal_ready() and link.startswith("http") and not YOUTUBE.search(link):
            # видеофайл или Яндекс Диск — показываем в своём кинозале прямо в Discord
            if await kinozal_set(voice, link, s["title"]):
                kinozal_buttons(view, voice, await kinozal_invite(self.bot, voice))
                in_kinozal = True
        if voice and not in_kinozal:
            try:
                invite = await voice.create_invite(max_age=6 * 3600, target_type=discord.InviteTarget.embedded_application,
                                                   target_application_id=config.WATCH_TOGETHER_APP_ID,
                                                   reason="Кино: Смотрим вместе")
                view.add_item(discord.ui.Button(label="Смотрим вместе", emoji="▶️", url=invite.url))
            except discord.HTTPException:
                pass
        if link.startswith("http") and not in_kinozal:
            view.add_item(discord.ui.Button(label="Ссылка на фильм", emoji="🔗", url=link))
        role = channels(guild)[2]
        await afisha.send(content=role.mention if role else None, embed=embed, files=files,
                          view=view if view.children else None,
                          allowed_mentions=discord.AllowedMentions(roles=True))
        if s["event_id"]:
            try:
                ev = await guild.fetch_scheduled_event(s["event_id"])
                if ev.status == discord.EventStatus.scheduled:
                    await ev.start()
            except discord.HTTPException:
                pass

    @app_commands.command(name="kinozal", description="Включить фильм в кинозале прямо сейчас (ссылка на видео или Яндекс Диск)")
    @app_commands.describe(link="Прямая ссылка на MP4/WebM или публичная ссылка Яндекс Диска",
                           title="Название (необязательно)")
    @app_commands.guild_only()
    async def kinozal(self, interaction: discord.Interaction, link: str, title: str | None = None):
        if not kinozal_ready():
            return await interaction.response.send_message(
                "Кинозал ещё не подключён: нужен адрес сайта кинозала в настройках бота.", ephemeral=True, delete_after=GONE)
        voice = interaction.user.voice.channel if interaction.user.voice else channels(interaction.guild)[1]
        if voice is None:
            return await interaction.response.send_message("Зайди в голосовой канал, где будете смотреть.", ephemeral=True, delete_after=GONE)
        if not link.startswith("http") or YOUTUBE.search(link):
            return await interaction.response.send_message(
                "Нужна ссылка на видеофайл или Яндекс Диск. YouTube открывай через «Смотрим вместе».", ephemeral=True, delete_after=GONE)
        await interaction.response.defer(thinking=True)
        name = title or link.split("?")[0].rstrip("/").split("/")[-1]
        if not await kinozal_set(voice, link, name):
            return await interaction.followup.send("⚠️ Кинозал не ответил. Попробуй ещё раз через минуту.")
        view = discord.ui.View()
        kinozal_buttons(view, voice, await kinozal_invite(self.bot, voice))
        await interaction.followup.send(f"🍿 **{name}** — в {voice.mention}. Пауза и перемотка — у всех сразу, "
                                        "и в Discord, и в браузере.", view=view)

    @ticker.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Cinema(bot))
