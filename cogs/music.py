"""Музыка: поиск по названию (YouTube → SoundCloud) или ссылка с любого сайта, который знает yt-dlp
(YouTube, SoundCloud, VK видео, Twitch, Bandcamp и ещё 1000+).
Управлять можно только сидя в одном голосовом канале с ботом. Панель с кнопками — в чате этого канала."""
import asyncio
import logging
import os
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

import perms
import vk_music
from cogs import achievements
from utils import fmt_duration

log = logging.getLogger(__name__)

FFMPEG = os.getenv("FFMPEG_PATH") or "ffmpeg"
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
}
# Где искать по названию — по очереди, пока не найдётся
SEARCH_SOURCES = [("YouTube", "ytsearch1:"), ("SoundCloud", "scsearch1:")]
STREAM_TTL = 30 * 60  # ссылки на поток протухают — старше 30 мин получаем заново
COLOUR = discord.Colour.orange()
LOOP_NAMES = {"off": "выкл", "track": "🔂 трек", "queue": "🔁 очередь"}


YDL_LIST_OPTS = {**YDL_OPTS, "extract_flat": "in_playlist"}  # плейлисты: только список, без загрузки
MAX_PLAYLIST = 100

GENRES = ["Фонк", "Рэп", "Русский рэп", "Рок", "Русский рок", "Поп", "Lo-fi", "EDM", "Хаус", "Техно",
          "Дрилл", "Метал", "Панк", "Джаз", "Классика", "Шансон", "Хип-хоп 90-х", "K-pop", "Аниме опенинги",
          "Музыка для игр", "Синтвейв", "Drum and Bass", "Реггетон", "Инди"]


@dataclass
class Track:
    title: str | None
    page_url: str | None          # ссылка на трек; None — ещё не найден (тогда ищем по query)
    duration: int | None
    source: str
    author: str | None = None
    thumbnail: str | None = None
    query: str | None = None      # «исполнитель - название» для треков из ВК
    stream_url: str | None = None
    requester: discord.Member | None = None
    fetched_at: float = field(default_factory=time.monotonic)

    @property
    def name(self) -> str:
        return self.title or self.query or "Без названия"

    @property
    def link(self) -> str:
        return f"[{self.name}]({self.page_url})" if self.page_url else self.name

    def needs_refresh(self) -> bool:
        return not self.stream_url or time.monotonic() - self.fetched_at > STREAM_TTL

    def refresh(self):
        """Получить ссылку на поток (блокирующая)."""
        targets = [self.page_url] if self.page_url else [p + self.query for _, p in SEARCH_SOURCES]
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            for target in targets:
                try:
                    info = ydl.extract_info(target, download=False)
                except yt_dlp.utils.DownloadError as e:
                    log.warning("Не удалось открыть %s: %s", target, e)
                    continue
                if info and info.get("entries"):
                    info = next((e for e in info["entries"] if e), None)
                if info:
                    self.stream_url = info["url"]
                    self.fetched_at = time.monotonic()
                    self.page_url = info.get("webpage_url") or self.page_url
                    self.title = self.title or info.get("title")
                    self.duration = self.duration or info.get("duration")
                    self.thumbnail = self.thumbnail or info.get("thumbnail")
                    self.author = self.author or info.get("uploader")
                    return
        raise RuntimeError("трек не найден")


def _thumb(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = info.get("thumbnails") or []
    return thumbs[-1]["url"] if thumbs else None


def _to_track(info: dict, source: str) -> Track:
    return Track(
        title=info.get("track") or info.get("title"),
        page_url=info.get("webpage_url") or info.get("url"),
        stream_url=info.get("url") if info.get("formats") else None,  # у плоских записей потока ещё нет
        duration=info.get("duration"),
        source=source,
        author=info.get("artist") or info.get("uploader") or info.get("channel"),
        thumbnail=_thumb(info),
    )


def resolve(query: str) -> tuple[str | None, list[Track]]:
    """Название/ссылка/плейлист -> (название плейлиста или None, треки). Блокирующая."""
    if re.match(r"https?://", query):
        if vk_music.is_vk(query):
            name, items = vk_music.get_tracks(query, MAX_PLAYLIST)
            return name, [Track(title=f"{i['artist']} — {i['title']}", page_url=None, duration=i["duration"],
                                source="ВК → YouTube", thumbnail=i["cover"], author=i["artist"],
                                query=f"{i['artist']} - {i['title']}") for i in items]
        with yt_dlp.YoutubeDL(YDL_LIST_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
        source = info.get("extractor_key", "Ссылка")
        if info.get("entries") is not None:
            tracks = [_to_track(e, source) for e in info["entries"] if e][:MAX_PLAYLIST]
            return info.get("title") or "Плейлист", tracks
        return None, [_to_track(info, source)]

    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        for name, prefix in SEARCH_SOURCES:
            try:
                info = ydl.extract_info(prefix + query, download=False)
            except yt_dlp.utils.DownloadError as e:
                log.warning("Поиск в %s не удался: %s", name, e)
                continue
            entries = [e for e in (info or {}).get("entries") or [] if e]
            if entries:
                return None, [_to_track(entries[0], name)]
    return None, []


def search_genre(genre: str, count: int) -> list[Track]:
    """Подборка треков жанра: ищем на YouTube, отсекаем часовые миксы, перемешиваем."""
    found: dict[str, dict] = {}
    with yt_dlp.YoutubeDL(YDL_LIST_OPTS) as ydl:
        for q in (f"ytsearch80:{genre} трек", f"ytsearch50:{genre} song"):
            info = ydl.extract_info(q, download=False)
            for e in info.get("entries") or []:
                if e and 90 <= (e.get("duration") or 0) <= 600:
                    found.setdefault(e["id"], e)
            if len(found) >= count * 2:
                break
    entries = list(found.values())
    random.shuffle(entries)
    return [_to_track(e, f"Жанр: {genre}") for e in entries[:count]]


class GuildMusic:
    def __init__(self):
        self.queue: deque[Track] = deque()
        self.history: deque[Track] = deque(maxlen=20)
        self.current: Track | None = None
        self.channel: discord.abc.Messageable | None = None  # чат голосового канала
        self.panel: discord.Message | None = None
        self.volume = 0.5
        self.loop = "off"            # off / track / queue
        self.manual: str | None = None  # skip / back / stop — почему остановили трек


def added_embed(track: Track, position: int) -> discord.Embed:
    embed = discord.Embed(title="💿 Добавлено в очередь", description=track.link, colour=COLOUR)
    embed.add_field(name="Автор", value=track.author or "—")
    embed.add_field(name="Длительность", value=f"`{fmt_duration(track.duration)}`")
    if position:
        embed.add_field(name="Место в очереди", value=f"#{position}")
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    return embed


def panel_embed(st: GuildMusic, paused: bool = False) -> discord.Embed:
    t = st.current
    embed = discord.Embed(title="⏸️ На паузе" if paused else "💿 Сейчас играет ♪",
                          description=t.link, colour=COLOUR)
    embed.add_field(name="Добавил", value=t.requester.mention if t.requester else "—")
    embed.add_field(name="Автор", value=t.author or "—")
    embed.add_field(name="Длительность", value=f"`{fmt_duration(t.duration)}`")
    if t.thumbnail:
        embed.set_thumbnail(url=t.thumbnail)
    embed.set_footer(text=f"🔊 {round(st.volume * 100)}%  ·  Повтор: {LOOP_NAMES[st.loop]}  ·  "
                          f"В очереди: {len(st.queue)}  ·  {t.source}")
    return embed


def queue_embed(st: GuildMusic) -> discord.Embed:
    lines = []
    if st.current:
        lines.append(f"▶️ **{st.current.name}** ({fmt_duration(st.current.duration)})")
    lines += [f"`{i}.` {t.name} ({fmt_duration(t.duration)})" for i, t in enumerate(list(st.queue)[:15], 1)]
    if len(st.queue) > 15:
        lines.append(f"…и ещё {len(st.queue) - 15}")
    return discord.Embed(title="📄 Очередь", description="\n".join(lines) or "Пусто", colour=COLOUR)


def same_channel(interaction: discord.Interaction) -> bool:
    vc = interaction.guild.voice_client
    voice = interaction.user.voice
    return bool(vc and voice and voice.channel == vc.channel)


NOT_WITH_BOT = "🎧 Управлять музыкой можно, только сидя в одном голосовом канале с ботом."


class PlayerView(discord.ui.View):
    """Кнопки под «Сейчас играет»."""

    def __init__(self, cog: "Music", st: GuildMusic):
        super().__init__(timeout=None)
        self.cog, self.st = cog, st
        on, off = discord.ButtonStyle.success, discord.ButtonStyle.secondary
        self.loop_track.style = on if st.loop == "track" else off
        self.loop_queue.style = on if st.loop == "queue" else off

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await perms.deny(interaction, "music"):
            return False
        if same_channel(interaction):
            return True
        await interaction.response.send_message(NOT_WITH_BOT, ephemeral=True)
        return False

    async def redraw(self, interaction: discord.Interaction):
        if self.st.current is None:
            return await interaction.response.defer()
        vc = interaction.guild.voice_client
        await interaction.response.edit_message(embed=panel_embed(self.st, paused=bool(vc and vc.is_paused())),
                                                view=PlayerView(self.cog, self.st))

    # --- 1 ряд ---
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.primary, row=0)
    async def previous(self, interaction: discord.Interaction, _):
        if not self.st.history:
            return await interaction.response.send_message("Предыдущих треков нет", ephemeral=True)
        await interaction.response.defer()
        await self.cog.go_back(interaction.guild)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, _):
        vc = interaction.guild.voice_client
        if vc.is_paused():
            vc.resume()
        elif vc.is_playing():
            vc.pause()
        await self.redraw(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        self.cog.skip_current(interaction.guild)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await self.cog.stop_all(interaction.guild, f"⏹️ Остановил {interaction.user.mention}")

    @discord.ui.button(emoji="📄", style=discord.ButtonStyle.secondary, row=0)
    async def show_queue(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(embed=queue_embed(self.st), ephemeral=True)

    # --- 2 ряд ---
    @discord.ui.button(emoji="🔂", row=1)
    async def loop_track(self, interaction: discord.Interaction, _):
        self.st.loop = "off" if self.st.loop == "track" else "track"
        await self.redraw(interaction)

    @discord.ui.button(emoji="🔁", row=1)
    async def loop_queue(self, interaction: discord.Interaction, _):
        self.st.loop = "off" if self.st.loop == "queue" else "queue"
        await self.redraw(interaction)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(self, interaction: discord.Interaction, _):
        items = list(self.st.queue)
        random.shuffle(items)
        self.st.queue = deque(items)
        await self.redraw(interaction)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1)
    async def volume_down(self, interaction: discord.Interaction, _):
        self.cog.set_volume(interaction.guild, self.st.volume - 0.1)
        await self.redraw(interaction)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1)
    async def volume_up(self, interaction: discord.Interaction, _):
        self.cog.set_volume(interaction.guild, self.st.volume + 0.1)
        await self.redraw(interaction)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusic] = {}

    def state(self, guild_id: int) -> GuildMusic:
        return self.states.setdefault(guild_id, GuildMusic())

    # ---------- логика плеера ----------
    async def play_next(self, guild: discord.Guild):
        st = self.state(guild.id)
        vc = guild.voice_client
        if vc is None or not vc.is_connected():
            st.current = None
            return await self.close_panel(st, "⏹️ Музыка остановлена")
        if not st.queue:
            st.current = None
            return await self.close_panel(st, "✅ Очередь закончилась. Добавь ещё: `/play`")

        track = st.queue.popleft()
        try:
            if track.needs_refresh():
                await asyncio.to_thread(track.refresh)
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(track.stream_url, executable=FFMPEG, **FFMPEG_OPTS), volume=st.volume)
        except Exception as e:
            log.exception("Не удалось запустить трек")
            if st.channel:
                await st.channel.send(f"⚠️ Пропускаю **{track.name}**: `{e}`")
            return await self.play_next(guild)

        st.current = track

        def after(error):
            if error:
                log.error("Ошибка воспроизведения: %s", error)
            asyncio.run_coroutine_threadsafe(self.on_track_end(guild), self.bot.loop)

        vc.play(source, after=after)
        await self.send_panel(st)

    async def on_track_end(self, guild: discord.Guild):
        st = self.state(guild.id)
        finished, reason = st.current, st.manual
        st.manual = None
        if finished and reason not in ("stop", "back"):
            if st.loop == "track" and reason != "skip":
                st.queue.appendleft(finished)
            else:
                st.history.append(finished)
                if st.loop == "queue":
                    st.queue.append(finished)
        if reason != "stop":
            await self.play_next(guild)

    def skip_current(self, guild: discord.Guild):
        st, vc = self.state(guild.id), guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            st.manual = "skip"
            vc.stop()  # after() включит следующий

    async def go_back(self, guild: discord.Guild):
        st, vc = self.state(guild.id), guild.voice_client
        prev = st.history.pop()
        if st.current:
            st.queue.appendleft(st.current)
        st.queue.appendleft(prev)
        if vc and (vc.is_playing() or vc.is_paused()):
            st.manual = "back"
            vc.stop()
        else:
            await self.play_next(guild)

    async def stop_all(self, guild: discord.Guild, text: str = "⏹️ Музыка остановлена"):
        st = self.state(guild.id)
        st.queue.clear()
        st.loop = "off"
        st.manual = "stop"
        st.current = None
        if vc := guild.voice_client:
            vc.stop()
            await vc.disconnect()
        await self.close_panel(st, text)

    def set_volume(self, guild: discord.Guild, value: float):
        st = self.state(guild.id)
        st.volume = round(min(1.5, max(0.1, value)), 2)
        vc = guild.voice_client
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = st.volume

    async def send_panel(self, st: GuildMusic):
        if st.panel:
            try:
                await st.panel.delete()
            except discord.HTTPException:
                pass
            st.panel = None
        if st.channel and st.current:
            st.panel = await st.channel.send(embed=panel_embed(st), view=PlayerView(self, st))

    async def close_panel(self, st: GuildMusic, text: str):
        if st.panel:
            try:
                await st.panel.edit(embed=discord.Embed(description=text, colour=COLOUR), view=None)
            except discord.HTTPException:
                pass
            st.panel = None

    # ---------- команды ----------
    async def check_same(self, interaction: discord.Interaction) -> bool:
        if await perms.deny(interaction, "music"):
            return False
        if same_channel(interaction):
            return True
        await interaction.response.send_message(NOT_WITH_BOT, ephemeral=True)
        return False

    async def precheck(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        """Есть доступ, человек в голосовом и бот не занят в другом канале? Возвращает канал человека."""
        if await perms.deny(interaction, "music"):
            return None
        voice = interaction.user.voice
        if not voice or not voice.channel:
            await interaction.response.send_message("Сначала зайди в голосовой канал 🎧", ephemeral=True)
            return None
        st = self.state(interaction.guild.id)
        vc = interaction.guild.voice_client
        if vc and vc.channel != voice.channel and (vc.is_playing() or vc.is_paused() or st.queue):
            await interaction.response.send_message(
                f"🎶 Я уже играю в {vc.channel.mention}. Зайди туда, чтобы добавить трек.", ephemeral=True)
            return None
        return voice.channel

    async def enqueue(self, interaction: discord.Interaction, channel: discord.VoiceChannel,
                      tracks: list[Track], title: str | None, colour_title: str = "📃 Добавлен плейлист"):
        st = self.state(interaction.guild.id)
        vc = interaction.guild.voice_client
        if vc is None:
            vc = await channel.connect(self_deaf=True)
        elif vc.channel != channel:
            await vc.move_to(channel)

        st.channel = channel  # панель — в чате голосового канала
        for t in tracks:
            t.requester = interaction.user
        st.queue.extend(tracks)
        playing = vc.is_playing() or vc.is_paused()

        if len(tracks) == 1 and title is None:
            embed = added_embed(tracks[0], len(st.queue) if playing else 0)
        else:
            preview = "\n".join(f"`{i}.` {t.name}" for i, t in enumerate(tracks[:10], 1))
            if len(tracks) > 10:
                preview += f"\n…и ещё {len(tracks) - 10}"
            embed = discord.Embed(title=f"{colour_title}: {title}", description=preview, colour=COLOUR)
            embed.set_footer(text=f"Треков: {len(tracks)}")
            if tracks[0].thumbnail:
                embed.set_thumbnail(url=tracks[0].thumbnail)
        await interaction.followup.send(embed=embed)
        await achievements.bump(interaction.user, "tracks")
        if not playing:
            await self.play_next(interaction.guild)

    @app_commands.command(name="play", description="Включить песню или плейлист (название, ссылка YouTube/SoundCloud/ВК)")
    @app_commands.describe(query="Название песни или ссылка на трек/плейлист (YouTube, SoundCloud, ВК…)")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        if not (channel := await self.precheck(interaction)):
            return
        await interaction.response.defer(thinking=True)
        try:
            title, tracks = await asyncio.to_thread(resolve, query)
        except vk_music.VKError as e:
            return await interaction.followup.send(f"⚠️ ВК: {e}")
        except Exception as e:
            return await interaction.followup.send(f"⚠️ Не смог открыть: `{e}`")
        if not tracks:
            return await interaction.followup.send(f"😕 Ничего не нашёл по запросу **{query}**")
        await self.enqueue(interaction, channel, tracks, title)

    @app_commands.command(name="genre", description="Включить подборку по жанру: фонк, рок, рэп…")
    @app_commands.describe(genre="Жанр — выбери из списка или впиши свой", count="Сколько треков (5-50)")
    @app_commands.guild_only()
    async def genre(self, interaction: discord.Interaction, genre: str,
                    count: app_commands.Range[int, 5, 50] = 15):
        if not (channel := await self.precheck(interaction)):
            return
        await interaction.response.defer(thinking=True)
        try:
            tracks = await asyncio.to_thread(search_genre, genre, count)
        except Exception as e:
            return await interaction.followup.send(f"⚠️ Не получилось: `{e}`")
        if not tracks:
            return await interaction.followup.send(f"😕 Не нашёл треков в жанре **{genre}**")
        await self.enqueue(interaction, channel, tracks, genre, colour_title="🎧 Подборка")

    @genre.autocomplete("genre")
    async def genre_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [app_commands.Choice(name=g, value=g) for g in GENRES if current in g.lower()][:25]

    @app_commands.command(name="skip", description="Пропустить трек")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        if await self.check_same(interaction):
            self.skip_current(interaction.guild)
            await interaction.response.send_message("⏭️ Пропущено")

    @app_commands.command(name="stop", description="Остановить музыку и выйти из канала")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        if await self.check_same(interaction):
            await self.stop_all(interaction.guild, f"⏹️ Остановил {interaction.user.mention}")
            await interaction.response.send_message("⏹️ Остановлено")

    @app_commands.command(name="pause", description="Пауза / продолжить")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction):
        if await self.check_same(interaction):
            vc = interaction.guild.voice_client
            if vc.is_paused():
                vc.resume()
                await interaction.response.send_message("▶️ Продолжаем")
            else:
                vc.pause()
                await interaction.response.send_message("⏸️ Пауза")

    @app_commands.command(name="queue", description="Показать очередь")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=queue_embed(self.state(interaction.guild.id)), ephemeral=True)

    @app_commands.command(name="volume", description="Громкость 10-150%")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 10, 150]):
        if await self.check_same(interaction):
            self.set_volume(interaction.guild, percent / 100)
            await interaction.response.send_message(f"🔊 Громкость {percent}%")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Если в канале с ботом никого не осталось — ждём минуту и выходим
        vc = member.guild.voice_client
        if not vc or not vc.channel or before.channel != vc.channel:
            return
        if any(not m.bot for m in vc.channel.members):
            return
        await asyncio.sleep(60)
        if vc.is_connected() and not any(not m.bot for m in vc.channel.members):
            await self.stop_all(member.guild, "👋 Все ушли — я тоже")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
