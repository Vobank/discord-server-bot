"""🍿 Подборка фильмов: у каждого фильма своя карточка в #🍿・подборка (картинка: обложка, название, жанры,
год · страна · длительность + описание). Предложить можно одним названием — потом автор, Киноманы или
админы дозаполняют и исправляют карточку кнопкой «✏️ Заполнить / исправить». Повторов нет: кнопка
«👍 Тоже хочу» добавляет голос (×N). Админ в #🎬・кино-настройки устраивает голосование и отмечает
просмотренное; начался сеанс с таким названием — фильм сам уходит в «Уже посмотрели».
ИИ (ai.py) сам дозаполняет новые карточки: год, страну, длительность, описание и обложку.
Ответы бота на кнопки видит только нажавший, и они исчезают сами.
Сериалы, мультсериалы и аниме: бот помнит, сколько серий посмотрели и сколько осталось (кнопки на карточке)."""
import asyncio
import datetime
import io
import logging
import random
import re
import time

import aiohttp
import discord
from discord.ext import commands

import ai
import config
import db
import perms
from cogs import film_card

log = logging.getLogger(__name__)

COLOUR = discord.Colour(0xF5C518)
DURATIONS = [("1 час", 1), ("6 часов", 6), ("12 часов", 12), ("1 день", 24), ("2 дня", 48), ("3 дня", 72)]
# Что предлагают: выбирается на шаге 1 и в «Заполнить / исправить» (один вариант)
TYPES = {
    "movie": ("🎬", "Фильм"), "series": ("📺", "Сериал"), "cartoon": ("🧸", "Мультфильм"),
    "cartoon_series": ("🎠", "Мультсериал"), "anime": ("🌸", "Аниме"), "anime_movie": ("🎴", "Аниме-фильм"),
}
# старые жанры — только чтобы правильно показывать уже предложенные фильмы
LEGACY = {
    "fantasy": ("🧙", "Фэнтези"), "action": ("💥", "Боевик"), "comedy": ("😂", "Комедия"), "horror": ("😱", "Ужасы"),
    "scifi": ("🚀", "Фантастика"), "thriller": ("🔪", "Триллер"), "detective": ("🔎", "Детектив"),
    "romance": ("💕", "Мелодрама"), "drama": ("🎭", "Драма"), "adventure": ("🗺️", "Приключения"),
    "other": ("📼", "Другое"),
}
GENRES = {**TYPES, **LEGACY}
POPULAR_TOP = 5
GONE = 15        # через сколько секунд исчезают ответы бота
MENU_GONE = 300  # меню и списки — дольше, чтобы успеть выбрать
FIELDS = "id, title, count, suggested_by, watched_before, watched_at, genre, genres, year, country, duration, " \
         "description, poster, card_msg, author_id, status, episodes_total, episodes_watched"
SERIALS = {"series", "cartoon_series", "anime"}  # у них считаем серии


def genre_label(key: str) -> str:
    emoji, name = GENRES.get(key or "other", GENRES["other"])
    return f"{emoji} {name}"


def genre_keys(f: dict) -> list[str]:
    keys = [k for k in (f.get("genres") or "").split(",") if k in GENRES]
    return keys or [f.get("genre") or "other"]


def normalize(title: str) -> str:
    t = title.lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def as_dict(row) -> dict:
    return dict(zip([k.strip() for k in FIELDS.split(",")], row))


async def films(guild_id: int, status: str = "wish") -> list[dict]:
    items = [as_dict(r) for r in await db.fetchall(f"SELECT {FIELDS} FROM films WHERE guild_id=? AND status=?",
                                                   (guild_id, status))]
    if status == "watched":
        return sorted(items, key=lambda f: -(f["watched_at"] or 0))
    return sorted(items, key=lambda f: normalize(f["title"]))


async def film_by(**where) -> dict | None:
    (key, value), = where.items()
    row = await db.fetchone(f"SELECT {FIELDS} FROM films WHERE {key}=?", (value,))
    return as_dict(row) if row else None


# ---------- карточка ----------
def is_serial(f: dict) -> bool:
    return genre_keys(f)[0] in SERIALS or bool(f.get("episodes_total"))


def progress(f: dict) -> str:
    """«12 из 114 · осталось 102» или «посмотрели 12» (если не знаем, сколько всего)."""
    seen, total = f.get("episodes_watched") or 0, f.get("episodes_total")
    if total:
        return f"{seen} из {total} · осталось {max(0, total - seen)}"
    return f"посмотрели {seen}" + (" · сколько всего — неизвестно" if seen else "")


def meta_line(f: dict) -> str:
    return " · ".join(x for x in (f.get("year"), f.get("country"), f.get("duration")) if x)


def card_embed(f: dict) -> discord.Embed:
    watched = f["status"] == "watched"
    e = discord.Embed(title=f"🎬 {f['title']}", colour=discord.Colour.green() if watched else COLOUR,
                      description=(f["description"] or "*Описания пока нет — нажми «✏️ Заполнить / исправить».*")[:4000])
    e.add_field(name="🎞️ Тип", value=", ".join(genre_label(k) for k in genre_keys(f)))
    if f.get("year"):
        e.add_field(name="📅 Год", value=f["year"])
    if f.get("country"):
        e.add_field(name="🌍 Страна", value=f["country"])
    if f.get("duration"):
        e.add_field(name="⏱️ Время", value=f["duration"])
    if is_serial(f):
        e.add_field(name="📺 Серии", value=progress(f), inline=False)
    e.set_image(url="attachment://film.png")
    who = f"<@{f['author_id']}>" if f.get("author_id") else "—"
    status = "✅ Уже посмотрели" if watched else f"👍 Хотят посмотреть: {f['count']}"
    e.add_field(name="Статус", value=f"{status} · предложил {who}" + (" · 🔁 смотрели раньше" if f["watched_before"] else ""),
                inline=False)
    return e


async def card_file(f: dict) -> discord.File:
    watched = f["status"] == "watched"
    badge = "ПОСМОТРЕЛИ" if watched else (f"ХОТЯТ ПОСМОТРЕТЬ ×{f['count']}" if f["count"] > 1 else "В ПОДБОРКЕ")
    if not watched and is_serial(f) and f.get("episodes_watched"):
        total = f.get("episodes_total")
        badge = f"СЕРИЯ {f['episodes_watched']} ИЗ {total}" if total else f"ПОСМОТРЕЛИ {f['episodes_watched']} СЕРИЙ"
    data = await asyncio.to_thread(film_card.render, f["title"], [GENRES[k][1] for k in genre_keys(f)],
                                   meta_line(f), badge, f["poster"], watched)
    return discord.File(io.BytesIO(data), filename="film.png")


async def session_card(guild: discord.Guild, title: str, badge: str) -> tuple[discord.File, dict | None]:
    """Карточка для афиши кинотеатра: фильм из подборки — с обложкой и жанрами, иначе — только название."""
    row = await db.fetchone(f"SELECT {FIELDS} FROM films WHERE guild_id=? AND norm=?", (guild.id, normalize(title)))
    f = as_dict(row) if row else None
    genres = [GENRES[k][1] for k in genre_keys(f)] if f else []
    data = await asyncio.to_thread(film_card.render, f["title"] if f else title, genres,
                                   meta_line(f) if f else "", badge, f["poster"] if f else None)
    return discord.File(io.BytesIO(data), filename="film.png"), f


async def update_card(guild: discord.Guild, film_id: int, new: bool = False):
    """Создать или обновить карточку фильма в #🍿・подборка."""
    f = await film_by(id=film_id)
    channel = discord.utils.get(guild.text_channels, name=config.CH_CINEMA_WISHLIST)
    if not f or not channel or f["status"] == "planned":  # planned — фильм сеанса, без карточки в подборке
        return
    view = None if f["status"] == "watched" else FilmCardView(serial=is_serial(f))
    if f["card_msg"] and not new:
        try:
            msg = await channel.fetch_message(f["card_msg"])
            return await msg.edit(embed=card_embed(f), attachments=[await card_file(f)], view=view)
        except discord.HTTPException:
            pass
    msg = await channel.send(embed=card_embed(f), file=await card_file(f), view=view)
    await db.execute("UPDATE films SET card_msg=? WHERE id=?", (msg.id, film_id))
    await post_panel(None, channel)  # панель с кнопками — снова внизу


def can_edit(member: discord.Member, f: dict) -> bool:
    if member.guild_permissions.administrator or member.id == f.get("author_id"):
        return True
    names = {r.name for r in member.roles}
    return bool(names & (config.STAFF_ROLES | {config.ROLE_CINEMA}))


async def done(interaction: discord.Interaction, text: str, after: int = GONE):
    """Ответ после defer — видит только нажавший, исчезает сам."""
    msg = await interaction.followup.send(text, ephemeral=True, wait=True)

    async def later():
        await asyncio.sleep(after)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass
    asyncio.create_task(later())


# ---------- ИИ: дозаполнить карточку ----------
FIELD_NAMES = {"year": "год", "country": "страну", "duration": "длительность", "description": "описание",
               "episodes_total": "число серий", "poster": "обложку"}


async def autofill(guild: discord.Guild, fid: int, overwrite: bool = False) -> str:
    """Год, страна, длительность, описание (пустые, а с overwrite — все) и обложка, если её нет."""
    f = await film_by(id=fid)
    if not f:
        return "Фильм не найден"
    key = genre_keys(f)[0]
    kind = TYPES[key][1].lower() if key in TYPES else "фильм"
    info, problem = {}, ""
    try:
        info = await ai.film_info(f["title"], kind)
        if not info.get("found"):
            problem, info = f"не нашёл «{f['title']}» — проверь название", {}
    except ai.AIError as e:
        problem = str(e)
    updates = {}
    for k, limit in (("year", 20), ("country", 80), ("duration", 30), ("description", 1500)):
        value = (info.get(k) or "").strip()[:limit]
        if value and (overwrite or not f[k]):
            updates[k] = value
    if info.get("episodes") and (overwrite or not f["episodes_total"]):
        updates["episodes_total"] = info["episodes"]
    if not f["poster"]:
        data = await ai.poster(f["title"], info)
        if data:
            updates["poster"] = await asyncio.to_thread(film_card.shrink_poster, data)
    if updates:
        await db.execute(f"UPDATE films SET {', '.join(k + '=?' for k in updates)} WHERE id=?", (*updates.values(), fid))
        await update_card(guild, fid)
    filled = ", ".join(FIELD_NAMES[k] for k in updates)
    if filled:
        return f"🤖 Заполнил: {filled}" + (f"\n⚠️ Остальное не вышло: {problem}" if problem else "")
    return f"🤖 Не получилось: {problem}" if problem else "🤖 Всё уже заполнено"


def autofill_later(guild: discord.Guild, fid: int):
    """Дозаполнить в фоне: человек не ждёт, карточка обновится сама."""
    async def run():
        try:
            await autofill(guild, fid)
        except Exception:
            log.exception("ИИ не дозаполнил фильм %s", fid)
    if ai.ready():
        asyncio.create_task(run())


async def prepare_session_film(guild: discord.Guild, title: str):
    """Новый сеанс: найти данные и обложку для афиши. Фильма нет в подборке — запоминаем его без карточки."""
    norm = normalize(title)
    if len(norm) < 2:
        return
    row = await db.fetchone("SELECT id FROM films WHERE guild_id=? AND norm=?", (guild.id, norm))
    if row is None:
        await db.execute("INSERT INTO films (guild_id, title, norm, suggested_by, created_at, status) "
                         "VALUES (?,?,?,'',?,'planned')", (guild.id, title.strip()[:100], norm, int(time.time())))
        row = await db.fetchone("SELECT id FROM films WHERE guild_id=? AND norm=?", (guild.id, norm))
    autofill_later(guild, row[0])


# ---------- предложить фильм ----------
async def suggest(guild: discord.Guild, user: discord.abc.User, title: str, genres: list[str] | None = None,
                  details: dict | None = None) -> tuple[str, int | None]:
    """Возвращает (ответ человеку, id фильма для карточки или None)."""
    title = re.sub(r"\s+", " ", title).strip()[:100]
    norm = normalize(title)
    if len(norm) < 2:
        return "⚠️ Напиши нормальное название фильма 🙂", None
    genres = [g for g in (genres or []) if g in GENRES] or ["movie"]
    details = {k: (v or "").strip()[:1500] or None for k, v in (details or {}).items()}
    row = await db.fetchone("SELECT id, title, count, suggested_by, status FROM films WHERE guild_id=? AND norm=?",
                            (guild.id, norm))
    uid = str(user.id)
    if row is None:
        await db.execute("INSERT INTO films (guild_id, title, norm, suggested_by, created_at, genre, genres, author_id, "
                         "year, country, duration, description) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (guild.id, title, norm, uid, int(time.time()), genres[0], ",".join(genres), user.id,
                          details.get("year"), details.get("country"), details.get("duration"), details.get("description")))
        (fid,) = await db.fetchone("SELECT id FROM films WHERE guild_id=? AND norm=?", (guild.id, norm))
        return f"✅ **{title}** добавлен в подборку!", fid
    fid, old_title, count, by, status = row
    voters = set(filter(None, by.split(",")))
    if status == "planned":  # был только в афише — теперь в подборке по-настоящему
        await db.execute("UPDATE films SET status='wish', count=1, suggested_by=?, author_id=? WHERE id=?",
                         (uid, user.id, fid))
        return f"✅ **{old_title}** добавлен в подборку!", fid
    if status == "watched":  # уже смотрели — возвращаем для новых людей
        await db.execute("UPDATE films SET status='wish', watched_before=1, count=1, suggested_by=? WHERE id=?", (uid, fid))
        return f"🔁 **{old_title}** мы уже смотрели — вернул в подборку для тех, кто не видел.", fid
    if uid in voters:
        return f"Ты уже хочешь посмотреть **{old_title}** 🙂 (сейчас: ×{count})", None
    voters.add(uid)
    await db.execute("UPDATE films SET count=?, suggested_by=? WHERE id=?", (count + 1, ",".join(voters), fid))
    return f"👍 **{old_title}** уже есть в подборке — засчитал твой голос, теперь **×{count + 1}**.", fid


class SuggestModal(discord.ui.Modal):
    film = discord.ui.TextInput(label="Название", placeholder="Например: Странный Томас", max_length=100)
    year = discord.ui.TextInput(label="Год (если знаешь)", placeholder="2013", required=False, max_length=10)
    country = discord.ui.TextInput(label="Страна (если знаешь)", placeholder="США, Великобритания",
                                   required=False, max_length=80)
    duration = discord.ui.TextInput(label="Длительность (если знаешь)", placeholder="1 ч 33 мин",
                                    required=False, max_length=30)
    description = discord.ui.TextInput(label="Описание (можно потом)", style=discord.TextStyle.paragraph,
                                       required=False, max_length=1500,
                                       placeholder="О чём фильм — можно скопировать с Кинопоиска")

    def __init__(self, genres: list[str]):
        super().__init__(title="🍿 Предложить фильм")
        self.genres = genres

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        text, fid = await suggest(interaction.guild, interaction.user, self.film.value, self.genres,
                                  {"year": self.year.value, "country": self.country.value,
                                   "duration": self.duration.value, "description": self.description.value})
        if fid:
            await update_card(interaction.guild, fid)
            if text.startswith("✅") and ai.ready():
                autofill_later(interaction.guild, fid)
                text += "\n🤖 Год, описание и обложку ИИ допишет сам примерно через минуту."
            else:
                text += "\nОбложку и остальное можно добавить кнопкой «✏️ Заполнить / исправить» на карточке."
        await done(interaction, text, 30)


class GenrePickView(discord.ui.View):
    """Шаг 1: что это — фильм, сериал, мультфильм, мультсериал, аниме или аниме-фильм → шаг 2: название."""

    def __init__(self, then):
        super().__init__(timeout=600)
        self.then = then
        self.pick.options = [discord.SelectOption(label=name, emoji=emoji, value=key)
                             for key, (emoji, name) in TYPES.items()]

    @discord.ui.select(placeholder="🎞️ Что предлагаешь?", min_values=1, max_values=1,
                       options=[discord.SelectOption(label="-")])
    async def pick(self, interaction: discord.Interaction, select):
        await self.then(interaction, select.values)


# ---------- заполнить / исправить карточку ----------
class DetailsModal(discord.ui.Modal):
    def __init__(self, f: dict):
        super().__init__(title="✏️ Фильм: основное")
        self.fid = f["id"]
        self.film = discord.ui.TextInput(label="Название", default=f["title"], max_length=100)
        self.year = discord.ui.TextInput(label="Год", default=f["year"] or "", required=False, max_length=10)
        self.country = discord.ui.TextInput(label="Страна", default=f["country"] or "", required=False, max_length=80)
        self.duration = discord.ui.TextInput(label="Длительность", default=f["duration"] or "", required=False,
                                             max_length=30, placeholder="1 ч 33 мин")
        self.description = discord.ui.TextInput(label="Описание", style=discord.TextStyle.paragraph,
                                                default=f["description"] or "", required=False, max_length=1500)
        for item in (self.film, self.year, self.country, self.duration, self.description):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        title = re.sub(r"\s+", " ", self.film.value).strip()[:100]
        norm = normalize(title)
        clash = await db.fetchone("SELECT id FROM films WHERE guild_id=? AND norm=? AND id<>?",
                                  (interaction.guild.id, norm, self.fid))
        if clash:
            return await interaction.response.send_message("⚠️ Фильм с таким названием уже есть в подборке",
                                                           ephemeral=True, delete_after=GONE)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await db.execute("UPDATE films SET title=?, norm=?, year=?, country=?, duration=?, description=? WHERE id=?",
                         (title, norm, self.year.value.strip() or None, self.country.value.strip() or None,
                          self.duration.value.strip() or None, self.description.value.strip() or None, self.fid))
        await update_card(interaction.guild, self.fid)
        await done(interaction, "✅ Карточка обновлена")


class PosterModal(discord.ui.Modal, title="🖼️ Обложка фильма"):
    def __init__(self, fid: int):
        super().__init__()
        self.fid = fid
        self.file = discord.ui.FileUpload(required=False, max_values=1)
        self.add_item(discord.ui.Label(text="Загрузи картинку с компьютера", component=self.file))
        self.url = discord.ui.TextInput(required=False, max_length=500, placeholder="https://…jpg")
        self.add_item(discord.ui.Label(text="…или вставь ссылку на картинку", component=self.url))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        data = None
        try:
            if self.file.values:
                data = await self.file.values[0].read()
            elif self.url.value.strip().startswith("http"):
                async with aiohttp.ClientSession() as s, s.get(self.url.value.strip(), timeout=20) as r:
                    data = await r.read() if r.status == 200 else None
            data = await asyncio.to_thread(film_card.shrink_poster, data) if data else None
        except Exception:
            data = None
        if not data:
            return await done(interaction, "⚠️ Не получилось открыть картинку — попробуй другую")
        await db.execute("UPDATE films SET poster=? WHERE id=?", (data, self.fid))
        await update_card(interaction.guild, self.fid)
        await done(interaction, "✅ Обложка поставлена")


class EditMenu(discord.ui.View):
    def __init__(self, fid: int):
        super().__init__(timeout=600)
        self.fid = fid
        self.genres.options = [discord.SelectOption(label=name, emoji=emoji, value=key)
                               for key, (emoji, name) in TYPES.items()]

    @discord.ui.button(label="Название, год, страна, время, описание", emoji="📝", style=discord.ButtonStyle.primary)
    async def details(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(DetailsModal(await film_by(id=self.fid)))

    @discord.ui.button(label="Обложка", emoji="🖼️", style=discord.ButtonStyle.success)
    async def poster(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(PosterModal(self.fid))

    @discord.ui.button(label="Заполнить с ИИ", emoji="🤖", row=1)
    async def ai_fill(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await done(interaction, await autofill(interaction.guild, self.fid, overwrite=True), 30)

    @discord.ui.button(label="Нарисовать обложку", emoji="🎨", row=1)
    async def ai_poster(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        f = await film_by(id=self.fid)
        try:
            data = await ai.image(f"atmospheric cinematic movie poster for \"{f['title']}\""
                                  + (f": {f['description'][:300]}" if f["description"] else "")
                                  + ", cinematic lighting, vertical movie poster, no text, no letters")
        except ai.AIError as e:
            return await done(interaction, f"⚠️ {e}")
        if not ai.is_image(data):
            return await done(interaction, "⚠️ ИИ прислал не картинку — попробуй ещё раз")
        await db.execute("UPDATE films SET poster=? WHERE id=?",
                         (await asyncio.to_thread(film_card.shrink_poster, data), self.fid))
        await update_card(interaction.guild, self.fid)
        await done(interaction, "🎨 Нарисовал новую обложку")

    @discord.ui.select(placeholder="🎞️ Поменять: фильм, сериал, аниме…", min_values=1, max_values=1,
                       options=[discord.SelectOption(label="-")], row=2)
    async def genres(self, interaction: discord.Interaction, select):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await db.execute("UPDATE films SET genres=?, genre=? WHERE id=?", (",".join(select.values), select.values[0], self.fid))
        await update_card(interaction.guild, self.fid)
        await done(interaction, "✅ Тип обновлён")


class EpisodesModal(discord.ui.Modal, title="📺 Сколько серий посмотрели"):
    def __init__(self, f: dict):
        super().__init__()
        self.fid = f["id"]
        self.seen = discord.ui.TextInput(label="Сколько серий уже посмотрели", max_length=5,
                                         default=str(f.get("episodes_watched") or 0))
        self.total = discord.ui.TextInput(label="Сколько всего серий (если знаешь)", required=False, max_length=5,
                                          default=str(f["episodes_total"]) if f.get("episodes_total") else "")
        self.add_item(self.seen)
        self.add_item(self.total)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            seen = max(0, int(self.seen.value.strip()))
            total = int(self.total.value.strip()) if self.total.value.strip() else None
        except ValueError:
            return await interaction.response.send_message("⚠️ Нужны числа, например 12 и 114", ephemeral=True,
                                                           delete_after=GONE)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await done(interaction, await set_episodes(interaction.guild, self.fid, seen, total))


async def set_episodes(guild: discord.Guild, fid: int, seen: int, total: int | None) -> str:
    """Запомнить, сколько серий посмотрели. Досмотрели все — сериал уходит в «Уже посмотрели»."""
    if total:
        seen = min(seen, total)
    await db.execute("UPDATE films SET episodes_watched=?, episodes_total=? WHERE id=?", (seen, total, fid))
    finished = bool(total) and seen >= total
    if finished:
        await db.execute("UPDATE films SET status='watched', watched_at=? WHERE id=?", (int(time.time()), fid))
    await update_card(guild, fid)
    f = await film_by(id=fid)
    return f"✅ **{f['title']}** досмотрели целиком!" if finished else f"📺 **{f['title']}**: {progress(f)}"


class FilmCardView(discord.ui.View):
    """Кнопки под каждой карточкой (постоянные — фильм ищется по сообщению). У сериалов — ещё учёт серий."""

    def __init__(self, serial: bool = True):
        super().__init__(timeout=None)
        if not serial:
            self.remove_item(self.episode_plus)
            self.remove_item(self.episodes)

    @staticmethod
    async def editable(interaction: discord.Interaction) -> dict | None:
        f = await film_by(card_msg=interaction.message.id)
        if not f:
            await interaction.response.send_message("Фильм не найден", ephemeral=True, delete_after=GONE)
            return None
        if not can_edit(interaction.user, f):
            await interaction.response.send_message(
                f"📺 Отмечать серии могут автор, Администрация и роль {config.ROLE_CINEMA} "
                "(её можно взять кнопкой «🔔 Уведомлять меня» в 🎬・афиша).", ephemeral=True, delete_after=30)
            return None
        return f

    @discord.ui.button(label="+1 серия", emoji="▶️", style=discord.ButtonStyle.primary, custom_id="film:ep_plus", row=1)
    async def episode_plus(self, interaction: discord.Interaction, _):
        if not (f := await self.editable(interaction)):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await done(interaction, await set_episodes(interaction.guild, f["id"], (f["episodes_watched"] or 0) + 1,
                                                   f["episodes_total"]))

    @discord.ui.button(label="Серии", emoji="📺", custom_id="film:episodes", row=1)
    async def episodes(self, interaction: discord.Interaction, _):
        if f := await self.editable(interaction):
            await interaction.response.send_modal(EpisodesModal(f))

    @discord.ui.button(label="Тоже хочу", emoji="👍", style=discord.ButtonStyle.success, custom_id="film:want")
    async def want(self, interaction: discord.Interaction, _):
        f = await film_by(card_msg=interaction.message.id)
        if not f:
            return await interaction.response.send_message("Фильм не найден", ephemeral=True, delete_after=GONE)
        await interaction.response.defer(ephemeral=True, thinking=True)
        text, fid = await suggest(interaction.guild, interaction.user, f["title"])
        if fid:
            await update_card(interaction.guild, fid)
        await done(interaction, text)

    @discord.ui.button(label="Заполнить / исправить", emoji="✏️", custom_id="film:edit")
    async def edit(self, interaction: discord.Interaction, _):
        f = await film_by(card_msg=interaction.message.id)
        if not f:
            return await interaction.response.send_message("Фильм не найден", ephemeral=True, delete_after=GONE)
        if not can_edit(interaction.user, f):
            return await interaction.response.send_message(
                f"✏️ Исправлять карточку могут автор, Администрация и роль {config.ROLE_CINEMA} "
                "(её можно взять кнопкой «🔔 Уведомлять меня» в 🎬・афиша).", ephemeral=True, delete_after=30)
        await interaction.response.send_message(f"✏️ **{f['title']}** — что поправить?", view=EditMenu(f["id"]),
                                                ephemeral=True, delete_after=MENU_GONE)


# ---------- список (по кнопке и в афише) ----------
def film_line(f: dict) -> str:
    extra = " · ".join(x for x in (f.get("year"),) if x)
    return (f"• **{f['title']}**" + (f" ({extra})" if extra else "") + (f" · ×{f['count']}" if f["count"] > 1 else "")
            + (" · 🔁" if f["watched_before"] else ""))


def list_embeds(wish: list[dict], watched: list[dict]) -> list[discord.Embed]:
    lines = []
    popular = [f for f in sorted(wish, key=lambda f: (-f["count"], normalize(f["title"]))) if f["count"] > 1]
    if popular:
        lines.append("**🔥 Популярное**")
        lines += [f"{i}. **{f['title']}** · ×{f['count']} · {genre_label(genre_keys(f)[0])}"
                  for i, f in enumerate(popular[:POPULAR_TOP], 1)]
        lines.append("")
    for key in GENRES:
        group = [f for f in wish if genre_keys(f)[0] == key]
        if group:
            lines.append(f"**{genre_label(key)}** — {len(group)}")
            lines += [film_line(f) for f in group]
            lines.append("")
    chunks, chunk = [], ""
    for line in lines or ["Пока пусто — предложи первый фильм 👇"]:
        if len(chunk) + len(line) > 3900:
            chunks.append(chunk)
            chunk = ""
        chunk += line + "\n"
    chunks.append(chunk)
    result = [discord.Embed(title=f"🍿 Подборка фильмов — {len(wish)}" if i == 0 else None, description=text,
                            colour=COLOUR) for i, text in enumerate(chunks[:8])]
    result[0].set_footer(text="По типам и алфавиту · ×N — сколько человек хотят посмотреть")
    if watched:
        seen = "\n".join(f"✅ {f['title']}" + (f" · <t:{f['watched_at']}:d>" if f["watched_at"] else "")
                         for f in watched[:40])
        result.append(discord.Embed(title=f"🎬 Уже посмотрели — {len(watched)}", description=seen[:4000],
                                    colour=discord.Colour.dark_grey()))
    return result


class WishlistView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Предложить фильм", emoji="➕", style=discord.ButtonStyle.success, custom_id="films:add")
    async def add(self, interaction: discord.Interaction, _):
        async def then(i: discord.Interaction, genres: list[str]):
            await i.response.send_modal(SuggestModal(genres))
            try:  # шаг 1 больше не нужен
                await interaction.delete_original_response()
            except discord.HTTPException:
                pass
        await interaction.response.send_message("**Шаг 1.** Что предлагаешь: фильм, сериал, мультфильм, "
                                                "мультсериал, аниме или аниме-фильм? 👇",
                                                view=GenrePickView(then), ephemeral=True, delete_after=MENU_GONE)

    @discord.ui.button(label="Весь список", emoji="📋", custom_id="films:list")
    async def full_list(self, interaction: discord.Interaction, _):
        g = interaction.guild
        await interaction.response.send_message(embeds=list_embeds(await films(g.id), await films(g.id, "watched"))[:10],
                                                ephemeral=True, delete_after=MENU_GONE)


async def post_panel(bot, channel: discord.TextChannel):
    """Панель с кнопками — всегда последним сообщением."""
    async for msg in channel.history(limit=15):
        if msg.author == channel.guild.me and msg.components and \
                any(getattr(c, "custom_id", None) == "films:add" for row in msg.components for c in row.children):
            await msg.delete()
    await channel.send(embed=discord.Embed(
        title="🍿 Что посмотрим?",
        description=(
            "Жми **➕ Предложить фильм**: выбери, что это (фильм, сериал, аниме…), и напиши название — остальное по желанию.\n"
            "У каждого фильма появится **карточка** с обложкой. Хочешь тот же фильм — жми на ней **👍 Тоже хочу**.\n"
            "Обложку, описание, год и прочее можно добавить кнопкой **✏️ Заполнить / исправить** "
            f"(автор, Администрация и {config.ROLE_CINEMA}).\n"
            "Из подборки админы устраивают **голосование** в 🎬・афиша. Посмотренные помечаются ✅."),
        colour=COLOUR), view=WishlistView())


async def refresh_list(bot, guild: discord.Guild):
    """Совместимость: карточки обновляются сами, тут просто держим панель внизу."""
    channel = discord.utils.get(guild.text_channels, name=config.CH_CINEMA_WISHLIST)
    if channel:
        await post_panel(bot, channel)


async def post_wishlist_panel(bot, channel: discord.TextChannel):
    """При /setup: убрать старый общий список, выложить карточки фильмам без них, панель — вниз."""
    g = channel.guild
    old = await db.get_setting(g.id, "films_list_msg")
    if old:
        try:
            await (await channel.fetch_message(int(old))).delete()
        except discord.HTTPException:
            pass
        await db.set_setting(g.id, "films_list_msg", "")
    for f in (await films(g.id))[:30]:
        if not f["card_msg"]:
            await update_card(g, f["id"], new=True)
    await post_panel(bot, channel)


async def mark_watched(guild_id: int, title: str) -> bool:
    """Начался сеанс с таким названием — фильм уходит в «Уже посмотрели», карточка становится зелёной."""
    norm = normalize(title)
    row = await db.fetchone("SELECT id FROM films WHERE guild_id=? AND norm=?", (guild_id, norm))
    if row is None:
        await db.execute("INSERT INTO films (guild_id, title, norm, suggested_by, created_at) VALUES (?,?,?,'',?)",
                         (guild_id, title, norm, int(time.time())))
    await db.execute("UPDATE films SET status='watched', watched_at=? WHERE guild_id=? AND norm=?",
                     (int(time.time()), guild_id, norm))
    return row is not None


async def watched_now(guild: discord.Guild, title: str):
    """Для кинотеатра: сеанс начался — отметить и перекрасить карточку. Сериал за один сеанс не досматривают —
    его не отмечаем, серии считают кнопками на карточке."""
    row = await db.fetchone(f"SELECT {FIELDS} FROM films WHERE guild_id=? AND norm=?", (guild.id, normalize(title)))
    if row and is_serial(as_dict(row)):
        return
    await mark_watched(guild.id, title)
    row = await db.fetchone("SELECT id FROM films WHERE guild_id=? AND norm=?", (guild.id, normalize(title)))
    if row:
        await update_card(guild, row[0])


# ---------- админ: голосование и «просмотрено» ----------
class VoteSetupView(discord.ui.View):
    def __init__(self, items: list[dict], genre: str = "all", hours: int = 24):
        super().__init__(timeout=900)
        self.all_items, self.genre, self.hours = items, genre, hours
        shown = [f for f in items if genre == "all" or genre in genre_keys(f)]
        self.items = {str(f["id"]): f for f in shown}
        self.picked: list[str] = []
        top = sorted(shown, key=lambda f: (-f["count"], normalize(f["title"])))[:25]
        self.pick.options = [discord.SelectOption(label=f["title"][:100], value=str(f["id"]),
                                                  description=f"{genre_label(genre_keys(f)[0])} · хотят ×{f['count']}")
                             for f in top] or [discord.SelectOption(label="Такого пока нет в подборке", value="0")]
        self.pick.max_values = max(1, min(5, len(top)))
        present = {k for f in items for k in genre_keys(f)}
        self.genre_pick.options = [discord.SelectOption(label="Всё подряд", emoji="🎬", value="all",
                                                        default=genre == "all")] + [
            discord.SelectOption(label=name, emoji=emoji, value=key, default=genre == key)
            for key, (emoji, name) in GENRES.items() if key in present]
        self.duration.options = [discord.SelectOption(label=n, value=str(h), default=(h == hours)) for n, h in DURATIONS]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not await perms.deny(interaction, "cinema")

    @discord.ui.select(placeholder="🎞️ Что голосуем: фильмы, сериалы, аниме…", options=[discord.SelectOption(label="-")], row=0)
    async def genre_pick(self, interaction: discord.Interaction, select):
        await interaction.response.edit_message(view=VoteSetupView(self.all_items, select.values[0], self.hours))

    @discord.ui.select(placeholder="🎬 Выбери 1–5 фильмов для голосования", min_values=1,
                       options=[discord.SelectOption(label="-")], row=1)
    async def pick(self, interaction: discord.Interaction, select):
        self.picked = [v for v in select.values if v in self.items]
        await interaction.response.defer()

    @discord.ui.select(placeholder="⏱️ Сколько длится голосование", options=[discord.SelectOption(label="-")], row=2)
    async def duration(self, interaction: discord.Interaction, select):
        self.hours = int(select.values[0])
        await interaction.response.defer()

    async def launch(self, interaction: discord.Interaction, chosen: list[dict]):
        if not chosen:
            return await interaction.response.send_message("Выбери фильмы 👆", ephemeral=True, delete_after=GONE)
        g = interaction.guild
        afisha = discord.utils.get(g.text_channels, name=config.CH_CINEMA_AFISHA)
        role = discord.utils.get(g.roles, name=config.ROLE_CINEMA)
        question = "🍿 Что смотрим в следующий раз?" if self.genre == "all" else \
            f"🍿 Что смотрим? {genre_label(self.genre)}"
        poll = discord.Poll(question=question, duration=datetime.timedelta(hours=self.hours))
        for f in chosen:
            poll.add_answer(text=f["title"][:55], emoji="🎬")
        await afisha.send(content=(role.mention + " " if role else "") + "Голосуем за следующий фильм! 🎬",
                          poll=poll, allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.edit_message(
            content=f"🗳️ Голосование запущено в {afisha.mention} на {self.hours} ч: "
                    + ", ".join(f"**{f['title']}**" for f in chosen), embed=None, view=None)

    @discord.ui.button(label="Запустить", emoji="🗳️", style=discord.ButtonStyle.success, row=3)
    async def go(self, interaction, _):
        await self.launch(interaction, [self.items[i] for i in self.picked])

    @discord.ui.button(label="Топ-5 по голосам", emoji="🔝", row=3)
    async def top5(self, interaction, _):
        await self.launch(interaction, sorted(self.items.values(), key=lambda f: (-f["count"], normalize(f["title"])))[:5])

    @discord.ui.button(label="Случайные 5", emoji="🎲", row=3)
    async def rand5(self, interaction, _):
        await self.launch(interaction, random.sample(list(self.items.values()), min(5, len(self.items))))


class ManageView(discord.ui.View):
    """Отметить просмотренным / удалить мусор."""

    def __init__(self, items: list[dict], mode: str):
        super().__init__(timeout=900)
        self.mode = mode
        self.pick.options = [discord.SelectOption(label=f["title"][:100], value=str(f["id"])) for f in items[:25]]
        self.pick.max_values = len(self.pick.options)
        self.pick.placeholder = "✅ Что уже посмотрели?" if mode == "watched" else "🗑️ Что удалить из подборки?"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not await perms.deny(interaction, "cinema")

    @discord.ui.select(options=[discord.SelectOption(label="-")])
    async def pick(self, interaction: discord.Interaction, select):
        await interaction.response.defer(ephemeral=True, thinking=True)
        g = interaction.guild
        channel = discord.utils.get(g.text_channels, name=config.CH_CINEMA_WISHLIST)
        for fid in (int(v) for v in select.values):
            if self.mode == "watched":
                await db.execute("UPDATE films SET status='watched', watched_at=? WHERE id=?", (int(time.time()), fid))
                await update_card(g, fid)
            else:
                f = await film_by(id=fid)
                if f and f["card_msg"] and channel:
                    try:
                        await (await channel.fetch_message(f["card_msg"])).delete()
                    except discord.HTTPException:
                        pass
                await db.execute("DELETE FROM films WHERE id=?", (fid,))
        text = ("✅ Отмечено просмотренными" if self.mode == "watched" else "🗑️ Удалено из подборки") + \
            f": {len(select.values)}"
        await interaction.edit_original_response(content=text, view=None)


async def open_vote(interaction: discord.Interaction):
    items = await films(interaction.guild.id)
    if not items:
        return await interaction.response.send_message("В подборке пока нет фильмов", ephemeral=True, delete_after=GONE)
    await interaction.response.send_message(
        embed=discord.Embed(title="🗳️ Голосование за фильм", colour=COLOUR,
                            description="Можно выбрать **тип** (например, только аниме). "
                                        "Выбери до 5 фильмов вручную и нажми **Запустить** — или сразу "
                                        "**🔝 Топ-5** (больше всего 👍) / **🎲 Случайные 5**.\n"
                                        "Опрос появится в 🎬・афиша с пингом 🍿 Киноманов."),
        view=VoteSetupView(items), ephemeral=True, delete_after=MENU_GONE)


async def open_manage(interaction: discord.Interaction, mode: str):
    items = await films(interaction.guild.id)
    if not items:
        return await interaction.response.send_message("В подборке пока нет фильмов", ephemeral=True, delete_after=GONE)
    await interaction.response.send_message(view=ManageView(items, mode), ephemeral=True, delete_after=MENU_GONE)


class Films(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(WishlistView())
        bot.add_view(FilmCardView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Films(bot))
