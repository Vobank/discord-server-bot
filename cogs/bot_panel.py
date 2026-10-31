"""🤖 Пульт бота в Discord: канал #🤖・бот в админке (видят только высшие админы — право «Администратор»).
Живая карточка раз в минуту: где работает бот, сколько работает, пинг, память, ошибки, все компьютеры и сервер.
Кнопки: перезапустить, журнал, ошибки, перенести на другой компьютер, закрепить/открепить, копия базы.
Команды уходят диспетчеру той машины, где работает бот (runtime/command.txt) — работает с телефона откуда угодно."""
import datetime
import io
import json
import logging
import os
import re
import time

import discord
from discord.ext import commands, tasks

import config
import db

log = logging.getLogger(__name__)
CHANNEL = "🤖・бот"
STATUS = os.path.join("runtime", "status.json")
COMMAND = os.path.join("runtime", "command.txt")
BOT_LOG = "bot.log"
SUP_LOG = os.path.join("runtime", "supervisor.log")
ERROR_RE = re.compile(r"\bERROR\b|CRITICAL|Traceback")
STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
ONLINE = 150
COLOUR = discord.Colour.from_rgb(*config.ACCENT)

try:
    import psutil
except ImportError:
    psutil = None


def read_status() -> dict:
    try:
        with open(STATUS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def tail(path: str, n: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [re.sub(r"\x1b\[[0-9;]*m", "", ln.rstrip("\n")) for ln in f.readlines()[-n:]]
    except OSError:
        return []


def errors(hours: int = 24) -> list[str]:
    """Ошибки бота за последние hours часов: первая строка каждой."""
    since = datetime.datetime.now() - datetime.timedelta(hours=hours)
    out = []
    for ln in tail(BOT_LOG, 5000):
        if ERROR_RE.search(ln) and (m := STAMP_RE.search(ln)):
            try:
                if datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= since:
                    out.append(ln)
            except ValueError:
                pass
    return out


def ago(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 1:
        return "только что"
    if m < 60:
        return f"{m} мин"
    if m < 1440:
        return f"{m // 60} ч {m % 60} мин"
    return f"{m // 1440} дн {m % 1440 // 60} ч"


def send(cmd: str):
    """Команда диспетчеру этой машины (бот работает там же, где он)."""
    with open(COMMAND, "w", encoding="utf-8") as f:
        f.write(cmd)


def host_line(h: dict, st: dict) -> str:
    now = time.time()
    running = h.get("name") == st.get("active_host")
    online = running or now - (h.get("ts") or 0) < ONLINE
    icon = "🟢" if running else ("⚪" if online else "⚫")
    kind = "сервер" if h.get("kind") == "server" else "ПК"
    state = "работает бот" if running else ("в резерве" if online else f"не в сети {ago(now - (h.get('ts') or 0))}")
    load = f" · нагрузка {round(h['load'])}%" if online and isinstance(h.get("load"), (int, float)) else ""
    pin = " · 📌 закреплён" if st.get("pinned") and st.get("pinned") == h.get("id") else ""
    return f"{icon} **{h.get('name')}** ({kind}, №{h.get('priority')}) — {state}{load}{pin}"


class BotPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started = time.time()
        bot.add_view(PanelView(self))
        self.refresh.start()

    def cog_unload(self):
        self.refresh.cancel()

    async def channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cid = await db.get_setting(guild.id, "botpanel_channel")
        ch = guild.get_channel(int(cid)) if cid else None
        ch = ch or discord.utils.get(guild.text_channels, name=CHANNEL)
        if ch is None:
            category = discord.utils.find(lambda c: config.CAT_ADMIN in c.name, guild.categories)
            # только высшие админы: право «Администратор» видит всё и так, остальным — закрыто
            over = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
            for name in (config.ROLE_STAFF, config.ROLE_HEAD_MOD, config.ROLE_MOD):
                if role := discord.utils.get(guild.roles, name=name):
                    over[role] = discord.PermissionOverwrite(view_channel=False)
            ch = await guild.create_text_channel(CHANNEL, category=category, overwrites=over,
                                                 topic="Пульт бота: состояние и управление", reason="Пульт бота")
        if str(ch.id) != cid:
            await db.set_setting(guild.id, "botpanel_channel", str(ch.id))
        return ch

    def embed(self, guild: discord.Guild) -> discord.Embed:
        st = read_status()
        here = (st.get("me") or {}).get("name") or "этот компьютер"
        kind = "сервер" if (st.get("me") or {}).get("kind") == "server" else "ПК"
        e = discord.Embed(title="🤖 Пульт бота", colour=COLOUR, timestamp=discord.utils.utcnow())
        pinned = " · 📌 закреплён" if st.get("pinned") and st.get("pinned") == (st.get("me") or {}).get("id") else ""
        e.description = f"🟢 Работает на **{here}** ({kind}){pinned}"
        e.add_field(name="⏱️ Без перерыва", value=ago(time.time() - self.started))
        e.add_field(name="📶 Пинг", value=f"{round(self.bot.latency * 1000)} мс")
        if psutil:
            mem = psutil.Process().memory_info().rss / 2**20
            e.add_field(name="🧠 Память бота", value=f"{mem:.0f} МБ")
        version = st.get("version")
        if version:
            v = datetime.datetime.fromtimestamp(version, config.TIMEZONE)
            e.add_field(name="📦 Версия", value=v.strftime("%d.%m %H:%M"))
        errs = errors()
        e.add_field(name="⚠️ Ошибки за сутки", value=str(len(errs)) if errs else "нет 👍")
        pending = discord.utils.get(guild.roles, name=config.ROLE_PENDING)
        humans = sum(1 for m in guild.members if not m.bot and not config.is_ghost(m))
        e.add_field(name="👥 Участники", value=f"{humans}" + (f" · 🔒 на анкете: {len(pending.members)}" if pending else ""))
        hosts = st.get("hosts") or []
        if hosts:
            e.add_field(name="💻 Компьютеры", value="\n".join(host_line(h, st) for h in hosts)[:1024], inline=False)
        if errs:
            e.add_field(name="Последняя ошибка", value=f"```{errs[-1][-300:]}```", inline=False)
        e.set_footer(text="Обновляется раз в минуту")
        return e

    async def post(self, guild: discord.Guild, fresh: bool = False):
        ch = await self.channel(guild)
        mid = await db.get_setting(guild.id, "botpanel_msg")
        embed, view = self.embed(guild), PanelView(self, guild)
        if mid and not fresh:
            try:
                msg = await ch.fetch_message(int(mid))
                return await msg.edit(embed=embed, view=view)
            except discord.HTTPException:
                pass
        msg = await ch.send(embed=embed, view=view)
        await db.set_setting(guild.id, "botpanel_msg", str(msg.id))

    @tasks.loop(minutes=1)
    async def refresh(self):
        for guild in self.bot.guilds:
            try:
                await self.post(guild)
            except discord.HTTPException:
                log.exception("Пульт бота не обновился")

    @refresh.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


class MoveSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild | None):
        st = read_status()
        now = time.time()
        options = [discord.SelectOption(label=str(h.get("name"))[:100], value=str(h.get("id")),
                                        emoji="☁️" if h.get("kind") == "server" else "💻",
                                        description=f"№{h.get('priority')} · в резерве")
                   for h in st.get("hosts") or []
                   if h.get("name") != st.get("active_host") and now - (h.get("ts") or 0) < ONLINE][:25]
        super().__init__(placeholder="💻 Перенести бота на…", custom_id="botpanel:move", row=1,
                         options=options or [discord.SelectOption(label="Других компьютеров в сети нет", value="-")],
                         disabled=not options)

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        if target == "-":
            return await interaction.response.send_message("Других компьютеров в сети нет", ephemeral=True,
                                                           delete_after=15)
        name = next((h.get("name") for h in read_status().get("hosts") or [] if str(h.get("id")) == target), target)
        await interaction.response.send_message(f"🚚 Переношу бота на **{name}** — около 30 секунд. Бот закрепится "
                                                "там; вернуть — кнопкой «📌» на новом месте.", ephemeral=True,
                                                delete_after=60)
        send(f"give:{target}")


class PanelView(discord.ui.View):
    def __init__(self, cog: BotPanel, guild: discord.Guild | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(MoveSelect(guild))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message("Пульт только для высших админов", ephemeral=True, delete_after=15)
        return False

    @discord.ui.button(label="Перезапустить", emoji="🔄", style=discord.ButtonStyle.danger, custom_id="botpanel:restart")
    async def restart(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("🔄 Перезапускаю бота — вернётся через 10–20 секунд.", ephemeral=True,
                                                delete_after=30)
        send("restart_bot")

    @discord.ui.button(label="Журнал", emoji="📜", custom_id="botpanel:log")
    async def journal(self, interaction: discord.Interaction, _):
        text = "\n".join(tail(BOT_LOG, 400)) + "\n\n===== диспетчер =====\n" + "\n".join(tail(SUP_LOG, 100))
        await interaction.response.send_message(
            "📜 Последние 400 строк журнала бота и 100 — диспетчера:",
            file=discord.File(io.BytesIO(text.encode("utf-8")), filename="journal.txt"), ephemeral=True)

    @discord.ui.button(label="Ошибки", emoji="⚠️", custom_id="botpanel:errors")
    async def errs(self, interaction: discord.Interaction, _):
        found = errors(72)
        if not found:
            return await interaction.response.send_message("👍 За последние 3 дня ошибок нет", ephemeral=True,
                                                           delete_after=30)
        text = "\n".join(ln[-180:] for ln in found[-12:])
        await interaction.response.send_message(f"⚠️ Ошибок за 3 дня: **{len(found)}**. Последние:\n```{text[-1800:]}```",
                                                ephemeral=True)

    @discord.ui.button(label="Закрепить / открепить", emoji="📌", custom_id="botpanel:pin")
    async def pin(self, interaction: discord.Interaction, _):
        st = read_status()
        me = (st.get("me") or {}).get("id")
        if st.get("pinned") == me:
            send("unpin")
            text = "📌 Закрепление снято — бот снова выбирает компьютер по очереди."
        else:
            send("take_here")
            text = f"📌 Бот закреплён за **{(st.get('me') or {}).get('name')}**."
        await interaction.response.send_message(text, ephemeral=True, delete_after=30)

    @discord.ui.button(label="Копия базы", emoji="💾", custom_id="botpanel:backup")
    async def backup(self, interaction: discord.Interaction, _):
        send("backup")
        await interaction.response.send_message("💾 Сохраняю копию базы — она уйдёт и на другие компьютеры.",
                                                ephemeral=True, delete_after=30)


async def setup(bot: commands.Bot):
    await bot.add_cog(BotPanel(bot))
