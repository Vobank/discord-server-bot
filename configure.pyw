"""Мастер настройки бота: подключение к Discord, название, модули, игры, оформление, два ПК.
Сохраняет свои настройки в settings.json (только то, что отличается от settings.example.json) и ключи в .env.
Запуск: двойной клик по ярлыку «Настройка бота» или .venv\\Scripts\\pythonw.exe configure.pyw"""
import base64
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from tkinter import colorchooser, filedialog, messagebox, ttk

APP = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP)
sys.path.insert(0, APP)
import config  # noqa: E402

ENV_PATH = os.path.join(APP, ".env")
ENV_EXAMPLE = os.path.join(APP, ".env.example")
HOST_PATH = os.path.join(APP, "host.json")
STATUS = os.path.join(APP, "runtime", "status.json")
PY = os.path.join(APP, ".venv", "Scripts", "python.exe")
PYW = os.path.join(APP, ".venv", "Scripts", "pythonw.exe")
if not os.path.exists(PY):
    PY = PYW = sys.executable
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BG, SIDE, CARD, FG, MUTED = "#15161c", "#101116", "#1f2129", "#f2f2f7", "#9a9caa"
GREEN, YELLOW, RED, ACCENT = "#3ddc84", "#f5c518", "#ff5a5f", "#8b7bff"
FONT, BOLD, H1 = ("Segoe UI", 10), ("Segoe UI", 10, "bold"), ("Segoe UI", 16, "bold")

MODULES = [
    ("welcome_card", "🖼️ Карточка новичка", "Красивая картинка-приветствие с аватаркой и номером участника"),
    ("music", "🎵 Музыка", "/play — YouTube, SoundCloud, ВК; панель с кнопками, плейлисты, жанры"),
    ("voice_rooms", "🔊 Личные комнаты", "Зашёл в «Создать канал» — получил свою голосовую с кнопками управления"),
    ("levels", "📊 Уровни и достижения", "Уровни за сообщения, роли-награды, достижения, таблицы рейтингов"),
    ("birthdays", "🎂 Дни рождения", "Поздравления в календаре, роль именинника, праздники"),
    ("cinema", "🎬 Кинотеатр", "Сеансы, анонсы с карточкой фильма, напоминания, подборка фильмов с голосованием"),
    ("applications", "📝 Заявки в состав", "Анкета в модераторы/администраторы, рассмотрение, обзвон"),
    ("family", "🧡 Семья (для RP)", "Заявки в семью, HR, испытательный срок — для GTA RP и похожих игр"),
    ("protection", "🛡️ Защита", "Антиспам, антифлуд, фишинговые ссылки, защита от рейдов"),
    ("community", "💡 Идеи и ⭐ зал славы", "Канал идей с голосованием, лучшие сообщения, недельная сводка"),
    ("photo_only", "📸 Только фото", "В каналах «скриншоты» бот удаляет сообщения без картинок"),
    ("server_stats", "👥 Счётчик участников", "Голосовой канал «Участников: N», обновляется сам"),
    ("adult_channels", "🔞 Каналы 18+", "Закрытые каналы для девочек и мальчиков 18+ (по анкете)"),
    ("news_forward", "📰 Пересылка новостей", "Копирует посты из канала другого сервера в ваш канал"),
]
TIMEZONES = ["Europe/Moscow", "Europe/Kaliningrad", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Omsk",
             "Asia/Novosibirsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", "Asia/Vladivostok",
             "Europe/Kyiv", "Europe/Minsk", "Asia/Almaty", "Asia/Tashkent", "Europe/Berlin", "Europe/London", "UTC"]


def dpi_aware():
    """Чёткий текст на экранах с масштабом 125–200% (иначе Windows растягивает окно и всё мыльное)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# ---------- файлы ----------
def read_env() -> dict:
    path = ENV_PATH if os.path.exists(ENV_PATH) else ENV_EXAMPLE
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            m = re.match(r"^\s*([A-Z_]+)\s*=\s*(.*)$", line)
            if m:
                out[m[1]] = m[2].strip()
    return out


def write_env(updates: dict):
    src = ENV_PATH if os.path.exists(ENV_PATH) else ENV_EXAMPLE
    lines = open(src, encoding="utf-8-sig").read().splitlines() if os.path.exists(src) else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z_]+)\s*=", line)
        if m and m[1] in updates:
            lines[i] = f"{m[1]}={updates[m[1]]}"
            done.add(m[1])
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


MISSING = object()


def diff(cur, base):
    """Только то, что отличается от settings.example.json — так settings.json остаётся коротким."""
    if isinstance(cur, dict) and isinstance(base, dict):
        out = {}
        for k, v in cur.items():
            if k.startswith("_"):
                continue
            d = diff(v, base[k]) if k in base else v
            if d is not MISSING:
                out[k] = d
        return out or MISSING
    return MISSING if cur == base else cur


def save_settings(data: dict):
    with open(config.EXAMPLE_PATH, encoding="utf-8-sig") as f:
        example = json.load(f)
    d = diff(data, example)
    with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({} if d is MISSING else d, f, ensure_ascii=False, indent=2)


def read_host() -> dict:
    try:
        with open(HOST_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        import socket
        return {"name": socket.gethostname(), "priority": 1, "id": socket.gethostname().lower()}


def supervisor_running() -> bool:
    try:
        with open(STATUS, encoding="utf-8") as f:
            return time.time() - json.load(f).get("ts", 0) < 40
    except (OSError, json.JSONDecodeError):
        return False


# ---------- Discord API (без запуска бота) ----------
def api(token: str, path: str):
    req = urllib.request.Request("https://discord.com/api/v10" + path, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (configure, 1.0)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def app_id_from_token(token: str) -> str | None:
    try:
        part = token.split(".")[0]
        return base64.b64decode(part + "=" * (-len(part) % 4)).decode()
    except Exception:
        return None


def invite_url(app_id: str) -> str:
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}&permissions=8"
            "&scope=bot%20applications.commands")


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def make_shortcuts(name: str):
    """Автозапуск (если его ещё нет) и ярлыки на рабочем столе: панель и мастер настройки."""
    vbs = os.path.join(APP, "tools", "run_hidden.vbs")
    script = f"""
$sh = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath('Startup')
$have = $false
Get-ChildItem $startup -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {{
  $l = $sh.CreateShortcut($_.FullName); if ($l.Arguments -like ('*' + {ps_quote(vbs)} + '*')) {{ $have = $true }} }}
if (-not $have) {{
  $l = $sh.CreateShortcut((Join-Path $startup ({ps_quote(name)} + ' (автозапуск).lnk')))
  $l.TargetPath = 'C:\\Windows\\System32\\wscript.exe'; $l.Arguments = '"' + {ps_quote(vbs)} + '"'
  $l.WorkingDirectory = {ps_quote(APP)}; $l.Save() }}
$desk = [Environment]::GetFolderPath('Desktop')
foreach ($p in @(@({ps_quote(name)}, 'control_panel.pyw', 'Панель управления'),
                 @({ps_quote(name + ' — настройка')}, 'configure.pyw', 'Мастер настройки'))) {{
  $l = $sh.CreateShortcut((Join-Path $desk ($p[0] + '.lnk')))
  $l.TargetPath = {ps_quote(PYW)}; $l.Arguments = '"' + (Join-Path {ps_quote(APP)} $p[1]) + '"'
  $l.WorkingDirectory = {ps_quote(APP)}; $l.Description = $p[2]; $l.Save() }}
"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   creationflags=NO_WINDOW, timeout=60)


def sample_avatar() -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (256, 256))
    d = ImageDraw.Draw(img)
    for y in range(256):
        d.line([(0, y), (256, y)], fill=(90 + y // 4, 70, 200 - y // 3))
    d.ellipse((78, 50, 178, 150), fill=(235, 230, 255))
    d.ellipse((38, 160, 218, 330), fill=(235, 230, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ---------- интерфейс ----------
class Scroll(tk.Frame):
    """Прокручиваемая страница."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg=BG)
        self.body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units")
                      if str(e.widget).startswith(str(self)) else None)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.S = copy.deepcopy(config.load())
        self.env = read_env()
        self.host = read_host()
        self.app_id = None
        self.title("Мастер настройки бота")
        self.configure(bg=BG)
        k = self.winfo_fpixels("1i") / 96  # масштаб экрана
        self.geometry(f"{int(1060 * k)}x{int(740 * k)}")
        self.minsize(int(960 * k), int(640 * k))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG, arrowcolor=FG)
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=FG, rowheight=28, font=FONT)
        style.configure("Treeview.Heading", background=SIDE, foreground=FG, font=BOLD)
        style.map("Treeview", background=[("selected", ACCENT)])
        style.configure("Vertical.TScrollbar", background=CARD, troughcolor=BG, arrowcolor=FG)

        side = tk.Frame(self, bg=SIDE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="⚙️ Настройка", font=H1, fg=FG, bg=SIDE).pack(pady=(20, 4), padx=16, anchor="w")
        self.bot_title = tk.Label(side, text=self.S["bot"]["name"], font=FONT, fg=MUTED, bg=SIDE)
        self.bot_title.pack(padx=16, anchor="w", pady=(0, 16))

        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="top", fill="both", expand=True)
        bottom = tk.Frame(self, bg=SIDE)
        bottom.pack(side="bottom", fill="x")

        self.vars: dict[str, tk.Variable] = {}
        self.pages = {}
        self.nav = {}
        for key, label, build in [
            ("conn", "🔑  Подключение", self.page_conn), ("main", "📝  Основное", self.page_main),
            ("modules", "🧩  Модули", self.page_modules), ("games", "🎮  Игры и отделы", self.page_games),
            ("design", "🎨  Оформление", self.page_design), ("pcs", "🖥️  Два ПК", self.page_pcs),
        ]:
            frame = tk.Frame(self.content, bg=BG)
            build(frame)
            self.pages[key] = frame
            b = tk.Button(side, text=label, anchor="w", font=BOLD, fg=FG, bg=SIDE, activebackground=CARD,
                          activeforeground=FG, relief="flat", cursor="hand2", padx=16, pady=10,
                          command=lambda k=key: self.show(k))
            b.pack(fill="x")
            self.nav[key] = b

        for text, fn, colour in [("💾 Сохранить", self.save, ACCENT), ("🔍 Что создаст бот", self.check_server, MUTED),
                                 ("🏗️ Построить сервер", self.build_server, YELLOW),
                                 ("📜 Перевыложить правила", self.repost_rules, MUTED),
                                 ("▶ Запустить бота", self.start_bot, GREEN)]:
            tk.Button(bottom, text=text, command=fn, font=BOLD, fg=BG, bg=colour, relief="flat", cursor="hand2",
                      padx=10, pady=8).pack(side="left", padx=5, pady=10)
        self.toast = tk.Label(self.content, font=FONT, fg=MUTED, bg=BG, anchor="w")
        self.toast.pack(side="bottom", fill="x", padx=24, pady=(0, 4))
        self.show("conn" if not self.env.get("DISCORD_TOKEN") or "your" in self.env.get("DISCORD_TOKEN", "")
                  else "main")

    # ---------- общие элементы ----------
    def show(self, key):
        for k, f in self.pages.items():
            f.pack_forget()
            self.nav[k].configure(bg=SIDE)
        self.pages[key].pack(fill="both", expand=True)
        self.nav[key].configure(bg=CARD)

    def say(self, text, colour=MUTED):
        self.toast.configure(text=text, fg=colour)
        self.after(8000, lambda: self.toast.configure(text="") if self.toast.cget("text") == text else None)

    def header(self, parent, title, text=""):
        tk.Label(parent, text=title, font=H1, fg=FG, bg=BG).pack(anchor="w", padx=24, pady=(20, 2))
        if text:
            tk.Label(parent, text=text, font=FONT, fg=MUTED, bg=BG, justify="left", wraplength=700).pack(
                anchor="w", padx=24, pady=(0, 10))

    def field(self, parent, key, label, value, hint="", width=40, show=None, values=None):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=24, pady=4)
        tk.Label(row, text=label, font=BOLD, fg=FG, bg=BG, width=24, anchor="w").pack(side="left")
        var = tk.StringVar(value="" if value is None else str(value))
        if values:
            w = ttk.Combobox(row, textvariable=var, values=values, width=width - 2, font=FONT)
        else:
            w = tk.Entry(row, textvariable=var, width=width, font=FONT, bg=CARD, fg=FG, insertbackground=FG,
                         relief="flat", show=show or "")
        w.pack(side="left", ipady=4)
        if hint:
            tk.Label(row, text=hint, font=("Segoe UI", 9), fg=MUTED, bg=BG).pack(side="left", padx=10)
        self.vars[key] = var
        return var, w

    def button(self, parent, text, fn, colour=ACCENT, side="left"):
        b = tk.Button(parent, text=text, command=fn, font=BOLD, fg=BG, bg=colour, relief="flat", cursor="hand2",
                      padx=12, pady=6)
        b.pack(side=side, padx=4, pady=4)
        return b

    def section(self, parent, text):
        tk.Label(parent, text=text, font=("Segoe UI", 12, "bold"), fg=ACCENT, bg=BG).pack(anchor="w", padx=24,
                                                                                         pady=(16, 4))

    # ---------- 🔑 Подключение ----------
    def page_conn(self, page):
        sc = Scroll(page)
        sc.pack(fill="both", expand=True)
        p = sc.body
        self.header(p, "🔑 Подключение к Discord", (
            "1. Открой портал разработчиков → «New Application» → придумай имя.\n"
            "2. Слева «Bot» → «Reset Token» → скопируй токен и вставь ниже.\n"
            "3. Там же, ниже, включи «SERVER MEMBERS INTENT» и «MESSAGE CONTENT INTENT» → Save.\n"
            "4. Нажми «Проверить», потом «Пригласить бота» и выбери свой сервер.\n"
            "5. Выбери сервер в списке и нажми «💾 Сохранить» внизу."))
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=20)
        self.button(row, "🌐 Открыть портал разработчиков",
                    lambda: webbrowser.open("https://discord.com/developers/applications"), MUTED)
        token = self.env.get("DISCORD_TOKEN", "")
        self.field(p, "env.DISCORD_TOKEN", "Токен бота", "" if "your" in token else token, show="•", width=60)
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=20)
        self.button(row, "✅ Проверить", self.check_token, GREEN)
        self.button(row, "➕ Пригласить бота на сервер", self.invite, YELLOW)
        self.conn_status = tk.Label(p, text="", font=FONT, fg=MUTED, bg=BG, justify="left", wraplength=700)
        self.conn_status.pack(anchor="w", padx=24, pady=6)
        _, self.guild_box = self.field(p, "env.GUILD_ID", "Сервер", self.env.get("GUILD_ID", ""), width=50,
                                       values=[], hint="после «Проверить»")
        self.guild_ids: dict[str, str] = {}
        self.section(p, "Необязательно")
        self.field(p, "env.VK_TOKEN", "Токен ВК", self.env.get("VK_TOKEN", ""), show="•",
                   hint="только для ссылок на плейлисты ВК")
        self.field(p, "env.NEWS_FORWARDS", "Пересылка новостей", self.env.get("NEWS_FORWARDS", ""), width=46,
                   hint="ID_канала:наш_канал, …")

    def token(self) -> str:
        return self.vars["env.DISCORD_TOKEN"].get().strip()

    def check_token(self):
        token = self.token()
        if not token:
            return self.conn_status.configure(text="Вставь токен", fg=RED)
        self.conn_status.configure(text="Проверяю…", fg=MUTED)

        def work():
            try:
                me = api(token, "/users/@me")
                app = api(token, "/oauth2/applications/@me")
                guilds = api(token, "/users/@me/guilds")
            except urllib.error.HTTPError as e:
                text = "❌ Токен не подходит — скопируй заново (Bot → Reset Token)" if e.code == 401 else f"❌ Ошибка {e}"
                return self.after(0, lambda: self.conn_status.configure(text=text, fg=RED))
            except Exception as e:
                err = str(e)
                return self.after(0, lambda: self.conn_status.configure(text=f"❌ Нет связи: {err}", fg=RED))
            self.app_id = app["id"]
            flags = app.get("flags", 0)
            warn = []
            if not flags & (1 << 14 | 1 << 15):
                warn.append("SERVER MEMBERS INTENT")
            if not flags & (1 << 18 | 1 << 19):
                warn.append("MESSAGE CONTENT INTENT")
            text = f"✅ Бот «{me['username']}» найден. Серверов: {len(guilds)}."
            if warn:
                text += "\n⚠️ Включи на портале (Bot → Privileged Gateway Intents): " + ", ".join(warn)
            if not guilds:
                text += "\n➕ Бот ещё не на сервере — нажми «Пригласить бота на сервер», потом «Проверить» ещё раз."
            self.guild_ids = {f"{g['name']}  ({g['id']})": g["id"] for g in guilds}

            def done():
                self.conn_status.configure(text=text, fg=YELLOW if warn or not guilds else GREEN)
                self.guild_box.configure(values=list(self.guild_ids))
                cur = self.vars["env.GUILD_ID"].get()
                if len(guilds) == 1 and not cur:
                    self.vars["env.GUILD_ID"].set(next(iter(self.guild_ids)))
                if self.vars["main.bot.server_name"].get().strip() in ("", "Мой сервер"):  # подставим настоящее
                    name = next((g["name"] for g in guilds if g["id"] == self.guild_id()), None)
                    if name:
                        self.vars["main.bot.server_name"].set(name)
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def guild_id(self) -> str:
        v = self.vars["env.GUILD_ID"].get().strip()
        return self.guild_ids.get(v) or (re.search(r"(\d{15,21})", v) or [None, ""])[1]

    def invite(self):
        app_id = self.app_id or app_id_from_token(self.token())
        if not app_id or not app_id.isdigit():
            return self.say("Сначала вставь токен и нажми «Проверить»", RED)
        webbrowser.open(invite_url(app_id))
        self.say("Выбери сервер и нажми «Авторизовать», потом «Проверить» ещё раз")

    # ---------- 📝 Основное ----------
    def page_main(self, page):
        sc = Scroll(page)
        sc.pack(fill="both", expand=True)
        p, S = sc.body, self.S
        self.header(p, "📝 Основное", "Названия, которые бот пишет в сообщениях, на картинках и в правилах.")
        self.field(p, "main.bot.name", "Имя бота", S["bot"]["name"], hint="в панели управления и ярлыках")
        self.field(p, "main.bot.server_name", "Название сервера", S["bot"]["server_name"],
                   hint="«Добро пожаловать на …», правила, карточки")
        self.field(p, "main.bot.nickname_on_server", "Ник бота на сервере", S["bot"].get("nickname_on_server", ""),
                   hint="пусто — как в портале")
        self.field(p, "main.bot.timezone", "Часовой пояс", S["bot"]["timezone"], values=TIMEZONES)
        self.field(p, "main.bot.tz_label", "Подпись времени", S["bot"].get("tz_label", ""), width=10,
                   hint="например МСК — «20:30 (МСК)»")
        self.section(p, "Роли (бот создаст, если их нет; если есть — возьмёт существующие)")
        r = S["roles"]
        for key, label in [("base", "Участник (после анкеты)"), ("pending", "Новичок без анкеты"),
                           ("head_admin", "Главный админ"), ("head_mod", "Главный модератор"),
                           ("staff", "Администрация"), ("mod", "Модератор"), ("birthday", "Именинник"),
                           ("cinema", "Киноман"), ("mini_admin_prefix", "Приставка админа отдела")]:
            self.field(p, f"main.roles.{key}", label, r[key])
        self.section(p, "Семья (если включён модуль «Семья»)")
        f = S["family"]
        self.field(p, "main.family.name", "Название семьи", f["name"])
        self.field(p, "main.family.game", "Игра", f.get("game", ""), hint="например GTA 5 RP")
        self.field(p, "main.family.member_role", "Роль участника семьи", f["member_role"])
        self.field(p, "int.family.probation_days", "Испытательный срок, дней", f["probation_days"], width=6)
        self.section(p, "Разное")
        self.field(p, "int.community.star_count", "⭐ для зала славы", S["community"]["star_count"], width=6)
        self.field(p, "int.levels.step", "Сообщений на уровень", S["levels"]["step"], width=6)
        self.field(p, "int.birthday_hour", "Поздравлять в (час)", S["birthday_hour"], width=6)
        self.field(p, "int.applications.cooldown_days", "Повторная заявка через, дн.",
                   S["applications"]["cooldown_days"], width=6)
        self.field(p, "list.photo_only.keywords", "Каналы «только фото»", ", ".join(S["photo_only"]["keywords"]),
                   hint="слова в названии канала через запятую")
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=20, pady=12)
        self.button(row, "📄 Открыть все настройки (названия каналов и т.д.)", self.open_settings_file, MUTED)
        self.button(row, "📜 Открыть правила", self.open_rules_file, MUTED)

    def open_settings_file(self):
        self.save(quiet=True)
        os.startfile(config.SETTINGS_PATH)
        messagebox.showinfo("Все настройки", "Открыт settings.json — тут только твои изменения.\n"
                                             "Все возможные настройки с описанием — в settings.example.json: "
                                             "скопируй нужный кусок в settings.json и поменяй.\n\n"
                                             "После правки перезапусти мастер.")

    def open_rules_file(self):
        path = os.path.join(APP, "rules.json")
        if not os.path.exists(path):
            shutil.copy(os.path.join(APP, "rules.example.json"), path)
        os.startfile(path)
        self.say("Поправь правила и сохрани файл, потом «📜 Перевыложить правила»")

    # ---------- 🧩 Модули ----------
    def page_modules(self, page):
        sc = Scroll(page)
        sc.pack(fill="both", expand=True)
        p = sc.body
        self.header(p, "🧩 Модули", "Включи, что нужно. Анкета новичка, админ-панель, mini-панели отделов, "
                                    "мод-панель и правила работают всегда.")
        for key, title, desc in MODULES:
            card = tk.Frame(p, bg=CARD, padx=14, pady=8)
            card.pack(fill="x", padx=24, pady=4)
            var = tk.BooleanVar(value=bool(self.S["modules"].get(key)))
            self.vars[f"module.{key}"] = var
            tk.Checkbutton(card, text=title, variable=var, font=BOLD, fg=FG, bg=CARD, selectcolor=BG,
                           activebackground=CARD, activeforeground=FG, anchor="w").pack(anchor="w")
            tk.Label(card, text=desc, font=("Segoe UI", 9), fg=MUTED, bg=CARD, anchor="w").pack(anchor="w", padx=24)

    # ---------- 🎮 Игры ----------
    def page_games(self, page):
        self.header(page, "🎮 Игры и отделы", (
            "Каждая игра — роль и своя категория каналов (новости, чат, скриншоты, «Создать канал») и свой "
            "mini Admin. Новичок выбирает игры в анкете. Если у игры уже есть своя категория — бот её не трогает, "
            "только добавит права mini Admin."))
        self.games = copy.deepcopy(self.S["games"])
        box = tk.Frame(page, bg=BG)
        box.pack(fill="both", expand=True, padx=24)
        self.tree = ttk.Treeview(box, columns=("emoji", "name", "role", "extra"), show="headings", height=9)
        for col, text, w in [("emoji", "Эмодзи", 70), ("name", "Игра", 200), ("role", "Роль", 170),
                             ("extra", "Доп. роли отдела", 260)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.game_selected)
        form = tk.Frame(page, bg=BG)
        form.pack(fill="x", pady=6)
        self.g_emoji, _ = self.field(form, "game.emoji", "Эмодзи", "", width=8, hint="цветное сердечко — 💚 💙 🧡")
        self.g_name, _ = self.field(form, "game.name", "Название игры", "")
        self.g_role, _ = self.field(form, "game.role", "Роль", "", hint="пусто — как название")
        self.g_extra, _ = self.field(form, "game.extra", "Доп. роли отдела", "", hint="через запятую")
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x", padx=20, pady=(0, 10))
        self.button(row, "➕ Добавить", self.game_add, GREEN)
        self.button(row, "✏️ Изменить выбранную", self.game_edit)
        self.button(row, "🗑 Удалить", self.game_del, RED)
        self.button(row, "⬆", lambda: self.game_move(-1), MUTED)
        self.button(row, "⬇", lambda: self.game_move(1), MUTED)
        self.games_refresh()

    def games_refresh(self, select: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self.games):
            self.tree.insert("", "end", iid=str(i), values=(g["emoji"], g["name"], g["role"],
                                                           ", ".join(g.get("extra_roles", []))))
        if select is not None and 0 <= select < len(self.games):
            self.tree.selection_set(str(select))

    def game_selected(self, _=None):
        sel = self.tree.selection()
        if sel:
            g = self.games[int(sel[0])]
            self.g_emoji.set(g["emoji"])
            self.g_name.set(g["name"])
            self.g_role.set(g["role"])
            self.g_extra.set(", ".join(g.get("extra_roles", [])))

    def game_form(self) -> dict | None:
        name = self.g_name.get().strip()
        if not name:
            self.say("Впиши название игры", RED)
            return None
        extra = [x.strip() for x in self.g_extra.get().split(",") if x.strip()]
        return {"name": name, "role": self.g_role.get().strip() or name, "emoji": self.g_emoji.get().strip() or "🎮",
                **({"extra_roles": extra} if extra else {})}

    def game_add(self):
        if g := self.game_form():
            if any(x["name"] == g["name"] for x in self.games):
                return self.say("Такая игра уже есть", RED)
            self.games.append(g)
            self.games_refresh(len(self.games) - 1)

    def game_edit(self):
        sel = self.tree.selection()
        if sel and (g := self.game_form()):
            i = int(sel[0])
            keep = {k: v for k, v in self.games[i].items() if k in ("category_id", "category")}
            self.games[i] = {**g, **keep}
            self.games_refresh(i)

    def game_del(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Удалить", "Убрать игру из бота? Каналы и роль на сервере останутся."):
            del self.games[int(sel[0])]
            self.games_refresh()

    def game_move(self, step):
        sel = self.tree.selection()
        if sel:
            i = int(sel[0])
            j = i + step
            if 0 <= j < len(self.games):
                self.games[i], self.games[j] = self.games[j], self.games[i]
                self.games_refresh(j)

    # ---------- 🎨 Оформление ----------
    def page_design(self, page):
        sc = Scroll(page)
        sc.pack(fill="both", expand=True)
        p, t = sc.body, self.S["theme"]
        self.header(p, "🎨 Оформление карточки новичка",
                    "Баннер — фон картинки-приветствия (лучше 1100×400). Цвета — рамка, свечение и плашки. "
                    "Те же цвета у карточек фильмов.")
        self.preview = tk.Label(p, bg=BG)
        self.preview.pack(padx=24, pady=6, anchor="w")
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=20)
        self.button(row, "🖼️ Выбрать баннер…", self.pick_banner)
        self.button(row, "✖ Без баннера (фирменный фон)", self.clear_banner, MUTED)
        self.button(row, "🔄 Обновить предпросмотр", self.render_preview, GREEN)
        self.banner = t.get("welcome_banner") or "assets/welcome_bg.png"
        self.colours = {"accent": t["accent"], "accent2": t["accent2"]}
        self.swatches = {}
        for key, label in [("accent", "Основной цвет"), ("accent2", "Второй цвет")]:
            r = tk.Frame(p, bg=BG)
            r.pack(fill="x", padx=24, pady=4)
            tk.Label(r, text=label, font=BOLD, fg=FG, bg=BG, width=24, anchor="w").pack(side="left")
            sw = tk.Button(r, width=6, bg=self.colours[key], relief="flat", cursor="hand2",
                           command=lambda k=key: self.pick_colour(k))
            sw.pack(side="left", ipady=4)
            self.swatches[key] = sw
        self.field(p, "main.theme.welcome_title", "Надпись сверху", t["welcome_title"])
        self.field(p, "main.theme.welcome_subtitle", "Надпись снизу", t["welcome_subtitle"],
                   hint="{server} — название сервера", width=50)
        self.after(300, self.render_preview)

    def banner_path(self) -> str:
        return os.path.join(APP, self.banner)

    def pick_banner(self):
        path = filedialog.askopenfilename(title="Картинка для баннера",
                                          filetypes=[("Картинки", "*.png *.jpg *.jpeg *.webp *.gif *.bmp")])
        if not path:
            return
        from PIL import Image
        os.makedirs(os.path.join(APP, "assets"), exist_ok=True)
        self.banner = "assets/welcome_bg.png"
        Image.open(path).convert("RGB").save(self.banner_path(), "PNG")
        self.render_preview()
        self.say("Баннер сохранён в assets/welcome_bg.png")

    def clear_banner(self):
        if os.path.exists(self.banner_path()) and messagebox.askyesno("Баннер", "Убрать свой баннер?"):
            os.remove(self.banner_path())
            self.render_preview()

    def pick_colour(self, key):
        _, hx = colorchooser.askcolor(self.colours[key], title="Цвет")
        if hx:
            self.colours[key] = hx.upper()
            self.swatches[key].configure(bg=hx)
            self.render_preview()

    def render_preview(self):
        try:
            from PIL import Image, ImageTk
            from cogs import welcome_card as wc
            wc.ACCENT = tuple(int(self.colours["accent"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            wc.ACCENT2 = tuple(int(self.colours["accent2"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            wc.BG_FILE = self.banner_path()
            config.THEME["welcome_title"] = self.vars["main.theme.welcome_title"].get()
            config.THEME["welcome_subtitle"] = self.vars["main.theme.welcome_subtitle"].get()
            data = wc.render(sample_avatar(), "Новичок", 1, self.vars["main.bot.server_name"].get() or "Сервер")
            img = Image.open(io.BytesIO(data)).resize((660, 240))
            self.preview_img = ImageTk.PhotoImage(img)
            self.preview.configure(image=self.preview_img)
        except Exception as e:
            self.preview.configure(text=f"Предпросмотр недоступен: {e}", fg=RED, image="")

    # ---------- 🖥️ Два ПК ----------
    def page_pcs(self, page):
        sc = Scroll(page)
        sc.pack(fill="both", expand=True)
        p = sc.body
        self.header(p, "🖥️ Два ПК — бот не выключается", (
            "Бот можно поставить на два компьютера. Работает всегда ровно один: если главный ПК выключился — "
            "через минуту бот сам запустится на втором. База (уровни, дни рождения…) и обновления кода "
            "переезжают между ПК сами через закрытый канал 🔧・bot-sync на сервере.\n\n"
            "1. Нажми «Включить синхронизацию» (бот должен быть уже на сервере).\n"
            "2. Нажми «Собрать установщик» — на рабочем столе появится архив. Отправь его другу "
            "ЛИЧНО (там ключ бота!). Он распаковывает и запускает УСТАНОВИТЬ.bat — всё."))
        self.sync_label = tk.Label(p, font=BOLD, bg=BG, justify="left")
        self.sync_label.pack(anchor="w", padx=24, pady=4)
        self.refresh_sync()
        self.section(p, "Этот ПК")
        self.field(p, "host.name", "Имя этого ПК", self.host.get("name", ""))
        self.field(p, "host.priority", "Роль этого ПК", "1 — главный" if self.host.get("priority", 1) == 1
                   else "2 — запасной", values=["1 — главный", "2 — запасной"], width=20,
                   hint="главный забирает бота себе, когда включается")
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=20)
        self.button(row, "🔗 Включить синхронизацию", self.enable_sync, GREEN)
        self.section(p, "Установщик для второго ПК")
        self.field(p, "friend.name", "Имя второго ПК", "ПК друга")
        self.field(p, "friend.priority", "Его роль", "2 — запасной", values=["1 — главный", "2 — запасной"],
                   width=20)
        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=20)
        self.button(row, "📦 Собрать установщик на рабочий стол", self.make_package, YELLOW)

    def refresh_sync(self):
        env = read_env()
        if env.get("SYNC_CHANNEL_ID"):
            self.sync_label.configure(text="✅ Синхронизация включена — можно ставить второй ПК", fg=GREEN)
        else:
            self.sync_label.configure(text="⚪ Сейчас бот работает на одном ПК", fg=MUTED)

    def enable_sync(self):
        if read_env().get("SYNC_CHANNEL_ID"):
            return messagebox.showinfo("Два ПК", "Синхронизация уже включена — можно сразу собирать установщик.")
        if not self.save(quiet=True):
            return
        self.run_tool("Синхронизация двух ПК", [os.path.join("tools", "setup_sync.py")],
                      done=lambda ok: (self.refresh_sync(), ok and self.offer_restart()))

    def offer_restart(self):
        if supervisor_running() and messagebox.askyesno("Перезапуск", "Перезапустить бота, чтобы включить режим двух ПК?"):
            with open(os.path.join(APP, "runtime", "command.txt"), "w", encoding="utf-8") as f:
                f.write("stop")
            self.after(20000, lambda: subprocess.Popen(["wscript.exe", os.path.join(APP, "tools", "run_hidden.vbs")]))
            self.say("Бот перезапустится через ~20 секунд")

    def make_package(self):
        if not read_env().get("SYNC_CHANNEL_ID"):
            return messagebox.showwarning("Сначала синхронизация", "Сначала нажми «Включить синхронизацию».")
        if not self.save(quiet=True):
            return
        prio = "1" if self.vars["friend.priority"].get().startswith("1") else "2"
        self.run_tool("Установщик для второго ПК", [os.path.join("tools", "make_package.py"),
                                                    "--name", self.vars["friend.name"].get() or "Второй ПК",
                                                    "--priority", prio])

    # ---------- сохранение ----------
    def collect(self) -> tuple[dict, dict] | None:
        S = copy.deepcopy(self.S)
        env = {}
        for key, var in self.vars.items():
            kind, _, path = key.partition(".")
            value = var.get()
            if kind == "env":
                env[path] = str(value).strip()
            elif kind in ("main", "int", "list"):
                *parents, last = path.split(".")
                node = S
                for part in parents:
                    node = node[part]
                if kind == "int":
                    try:
                        value = int(str(value).strip())
                    except ValueError:
                        messagebox.showerror("Ошибка", f"«{value}» — тут нужно число")
                        return None
                elif kind == "list":
                    value = [x.strip() for x in str(value).split(",") if x.strip()]
                elif last not in ("mini_admin_prefix", "welcome_subtitle"):  # там пробелы по краям важны
                    value = str(value).strip()
                node[last] = value
            elif kind == "module":
                S["modules"][path] = bool(value)
        env["GUILD_ID"] = self.guild_id()
        S["games"] = self.games
        S["theme"]["accent"], S["theme"]["accent2"] = self.colours["accent"], self.colours["accent2"]
        S["theme"]["welcome_banner"] = self.banner
        if not S["bot"]["name"]:
            S["bot"]["name"] = "Бот сервера"
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(S["bot"]["timezone"])
        except Exception:
            messagebox.showerror("Ошибка", f"Не знаю часовой пояс «{S['bot']['timezone']}»")
            return None
        return S, env

    def save(self, quiet=False) -> bool:
        got = self.collect()
        if not got:
            return False
        S, env = got
        save_settings(S)
        write_env({k: v for k, v in env.items() if v or k in ("VK_TOKEN", "NEWS_FORWARDS")})
        host = {"name": self.vars["host.name"].get().strip() or self.host.get("name"),
                "priority": 1 if self.vars["host.priority"].get().startswith("1") else 2,
                "id": self.host.get("id") or re.sub(r"\W+", "-", self.vars["host.name"].get().lower()) or "pc"}
        with open(HOST_PATH, "w", encoding="utf-8") as f:
            json.dump(host, f, ensure_ascii=False, indent=1)
        self.S, self.host = S, host
        self.bot_title.configure(text=S["bot"]["name"])
        if not quiet:
            self.say("✅ Сохранено. Чтобы бот подхватил — «🏗️ Построить сервер» и перезапуск бота.", GREEN)
        return True

    def ready(self) -> bool:
        if not self.save(quiet=True):
            return False
        env = read_env()
        if not env.get("DISCORD_TOKEN") or not env.get("GUILD_ID"):
            messagebox.showwarning("Не хватает", "Сначала вкладка «Подключение»: токен и сервер.")
            self.show("conn")
            return False
        return True

    # ---------- действия ----------
    def run_tool(self, title, args, done=None):
        win = tk.Toplevel(self, bg=BG)
        win.title(title)
        win.geometry("760x440")
        txt = tk.Text(win, bg=CARD, fg=FG, font=("Consolas", 10), relief="flat", wrap="word")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("end", "⏳ Работаю, это займёт до минуты…\n\n")

        def work():
            try:
                r = subprocess.run([PY, "-X", "utf8", *args], cwd=APP, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW)
                out, ok = (r.stdout + ("\n" + r.stderr if r.returncode else "")).strip(), r.returncode == 0
            except Exception as e:
                out, ok = f"Ошибка: {e}", False

            def show():
                txt.insert("end", (out or "Готово.") + ("\n\n✅ Готово" if ok else "\n\n❌ Не получилось"))
                txt.see("end")
                if done:
                    done(ok)
            self.after(0, show)
        threading.Thread(target=work, daemon=True).start()

    def check_server(self):
        if self.ready():
            self.run_tool("Что создаст бот", [os.path.join("tools", "build_server.py"), "--check"])

    def build_server(self):
        if self.ready() and messagebox.askyesno(
                "Построить сервер", "Бот создаст недостающие роли, категории и каналы и выложит панели.\n"
                                    "Ничего не удаляет и не меняет существующие каналы.\n\nПродолжить?"):
            self.run_tool("Построение сервера", [os.path.join("tools", "build_server.py")])

    def repost_rules(self):
        if self.ready():
            self.run_tool("Правила", [os.path.join("tools", "build_server.py"), "--rules-only"])

    def start_bot(self):
        if not self.ready():
            return
        try:
            make_shortcuts(self.S["bot"]["name"])
        except Exception as e:
            messagebox.showwarning("Ярлыки", f"Не получилось создать ярлыки: {e}")
        if read_env().get("SYNC_CHANNEL_ID"):  # два ПК: настройки и баннер уезжают на второй ПК обновлением
            def publish():
                try:
                    import asyncio
                    import sync
                    asyncio.run(sync.publish("Настройки из мастера"))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: self.say(f"⚠️ Не отправил настройки на второй ПК: {err}", RED))
            threading.Thread(target=publish, daemon=True).start()
        if supervisor_running():
            with open(os.path.join(APP, "runtime", "command.txt"), "w", encoding="utf-8") as f:
                f.write("restart_bot")
            self.say("🔄 Бот перезапускается с новыми настройками", GREEN)
        else:
            subprocess.Popen(["wscript.exe", os.path.join(APP, "tools", "run_hidden.vbs")])
            self.say("▶ Бот запускается — через ~20 секунд он будет онлайн", GREEN)
        subprocess.Popen([PYW, os.path.join(APP, "control_panel.pyw")], cwd=APP)


if __name__ == "__main__":
    dpi_aware()
    App().mainloop()
