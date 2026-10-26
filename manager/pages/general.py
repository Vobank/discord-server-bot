"""Основное: имя бота, ник на сервере, название сервера, часовой пояс и подпись времени."""
import datetime
import tkinter as tk
from zoneinfo import ZoneInfo

from .. import state
from .. import widgets as W
from ..theme import C, px
from .base import Page

# (часовой пояс, город для списка, подпись времени считается от Москвы: «МСК+2»)
ZONES = [
    ("Europe/Moscow", "Москва", True),
    ("Europe/Kaliningrad", "Калининград", True),
    ("Europe/Samara", "Самара", True),
    ("Asia/Yekaterinburg", "Екатеринбург", True),
    ("Asia/Omsk", "Омск", True),
    ("Asia/Novosibirsk", "Новосибирск", True),
    ("Asia/Krasnoyarsk", "Красноярск", True),
    ("Asia/Irkutsk", "Иркутск", True),
    ("Asia/Yakutsk", "Якутск", True),
    ("Asia/Vladivostok", "Владивосток", True),
    ("Europe/Kyiv", "Киев", False),
    ("Europe/Minsk", "Минск", False),
    ("Asia/Almaty", "Алматы", False),
    ("Asia/Tashkent", "Ташкент", False),
    ("Europe/Berlin", "Берлин", False),
    ("Europe/London", "Лондон", False),
    ("UTC", "Всемирное время", False),
]
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")
MINUS = "−"
FIELD_W = 24   # ширина полей: так строки не переносятся даже в самом узком окне
NICK_MAX = 32  # ограничение Discord на ник


def zone(name: str):
    try:
        return ZoneInfo(name) if name else None
    except Exception:  # неизвестный или неверный пояс
        return None


def utc_offset(tz) -> str:
    minutes = int(datetime.datetime.now(tz).utcoffset().total_seconds() // 60)
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'+' if minutes >= 0 else MINUS}{hours}" + (f":{rest:02d}" if rest else "")


def zone_options(current: str) -> list:
    """[(пояс, «Москва (UTC+3)»), …]; поясов, которых нет в базе этого ПК, в списке нет.
    Текущий пояс остаётся в списке, даже если его нет среди обычных."""
    options = []
    for name, city, _ in ZONES:
        tz = zone(name)
        if tz is None:
            continue
        options.append((name, "Всемирное время (UTC)" if name == "UTC" else f"{city} ({utc_offset(tz)})"))
    if current and current not in {v for v, _ in options}:
        tz = zone(current)
        options.insert(0, (current, f"{current} ({utc_offset(tz)})" if tz else f"{current} (не найден)"))
    return options


def suggested_label(name: str) -> str | None:
    """Обычная подпись времени для пояса: «МСК», «МСК+2», «Минск»… None — для поясов не из списка."""
    item = next((z for z in ZONES if z[0] == name), None)
    if item is None:
        return None
    _, city, from_moscow = item
    if not from_moscow:
        return "UTC" if name == "UTC" else city
    tz, moscow = zone(name), zone("Europe/Moscow")
    if tz is None or moscow is None:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    hours = round((now.astimezone(tz).utcoffset() - now.astimezone(moscow).utcoffset()).total_seconds() / 3600)
    return "МСК" if hours == 0 else f"МСК{'+' if hours > 0 else MINUS}{abs(hours)}"


class View(Page):
    description = "Имя бота, название сервера и часовой пояс."

    def build(self):
        example = state.load_example().get("bot", {})
        self.default_name = example.get("name") or "Бот сервера"
        self.default_server = example.get("server_name") or "Мой сервер"

        W.section(self.body, "Бот")
        g = W.Group(self.body)
        row = g.row("Имя бота", "Так бот называется в этой программе, на ярлыках и в установщиках.", "robot")
        self.entry(row.right, "s:bot.name", fallback=self.default_name, maxlen=60).pack(side="left")
        row = g.row("Ник на сервере", "Пусто — имя из Developer Portal; новый ник бот ставит при построении "
                                      "сервера.", "contact")
        self.entry(row.right, "s:bot.nickname_on_server", placeholder="Как в Developer Portal",
                   maxlen=NICK_MAX).pack(side="left")

        W.section(self.body, "Сервер")
        g = W.Group(self.body)
        row = g.row("Название сервера", "Бот подставляет его в приветствие, правила и картинки.", "globe")
        self.server = self.entry(row.right, "s:bot.server_name", fallback=self.default_server, maxlen=100,
                                 on_change=lambda v: self.suggest_server_name())
        self.server.pack(side="left")
        self.suggest_box = tk.Frame(self.body, bg=W.bg_of(self.body))
        self.suggest_box.pack(fill="x")
        self.suggestion = None

        W.section(self.body, "Время", "По нему бот поздравляет с днём рождения, назначает сеансы кино "
                                      "и подводит итоги недели.")
        g = W.Group(self.body)
        self.zone_row = g.row("Часовой пояс", icon="clock")  # пояснение — живое время, см. update_clock
        self.zone_value = self.get("s:bot.timezone") or ""
        self.zone = self.bind_combo(self.zone_row.right, "s:bot.timezone", zone_options(self.zone_value),
                                    FIELD_W - 1, on_change=self.zone_changed)
        self.zone.pack(side="left")
        self.label_row = g.row("Подпись времени", icon="tag")  # пояснение — пример с текущим временем
        self.label = self.entry(self.label_row.right, "s:bot.tz_label", 12, placeholder="Без подписи", maxlen=20,
                                on_change=lambda v: self.update_clock(force=True))
        self.label.pack(side="left")
        self.clock_key = None
        self.update_clock(force=True)

    # --- поле, которое пишет в черновик (как bind_entry, плюс запасное значение, длина и отклик) ---
    def entry(self, parent, path: str, width: int = FIELD_W, placeholder: str = "", fallback: str | None = None,
              maxlen: int | None = None, on_change=None) -> W.Entry:
        """fallback — что записать, если поле очистили (подсказка в пустом поле показывает его же)."""
        value = self.get(path)

        def clean(raw: str) -> str:
            raw = raw.strip()
            return fallback if fallback is not None and not raw else raw

        def changed(raw: str):
            new = clean(raw)
            self.set(path, new)
            if on_change:
                on_change(new)

        return W.Entry(parent, "" if value is None else str(value), width, placeholder or (fallback or ""),
                       command=changed, validate=lambda raw: maxlen is None or len(raw.strip()) <= maxlen)

    # --- раздел открыли / раз в 2 секунды ---
    def on_show(self):
        self.update_clock(force=True)
        self.suggest_server_name()

    def on_status(self, status):
        self.update_clock()

    # --- время ---
    def zone_changed(self, value):
        old, self.zone_value = self.zone_value, value or ""
        label = (self.get("s:bot.tz_label") or "").strip()
        before, after = suggested_label(old), suggested_label(self.zone_value)
        if label and before and label == before and after and after != label:
            # подпись была обычной для прежнего пояса — меняем на обычную для нового
            self.set("s:bot.tz_label", after)
            self.label.set(after)
        self.update_clock(force=True)

    def update_clock(self, force: bool = False):
        tz = zone(self.get("s:bot.timezone") or "")
        label = (self.get("s:bot.tz_label") or "").strip()
        now = datetime.datetime.now(tz) if tz else None
        key = (self.get("s:bot.timezone"), label, now.strftime("%Y%m%d%H%M") if now else "")
        if key == self.clock_key and not force:
            return
        self.clock_key = key
        if now is None:
            self.zone_row.set_description("Такого пояса нет в базе часовых поясов. Выберите другой, иначе бот "
                                          "не запустится.")
            self.zone_row.desc.configure(fg=C("error"))
            self.label_row.set_description("Пример появится, когда будет выбран часовой пояс.")
            return
        hhmm = now.strftime("%H:%M")
        self.zone_row.set_description(f"Сейчас в этом поясе {hhmm}, {WEEKDAYS[now.weekday()]}, "
                                      f"{now.day} {MONTHS[now.month - 1]}.")
        self.zone_row.desc.configure(fg=C("text2"))
        if label:
            self.label_row.set_description(f"Так время выглядит в сообщениях бота: «{hhmm} ({label})».")
        else:
            self.label_row.set_description(f"Пусто — время без подписи: «{hhmm}».")

    # --- название сервера из Discord (если ключ уже проверили в разделе «Подключение») ---
    def suggest_server_name(self):
        info = getattr(self.app, "discord_info", None) or {}
        guilds = info.get("guilds") or []
        gid = str(self.get("e:GUILD_ID") or "")
        guild = next((x for x in guilds if str(x.get("id")) == gid), None)
        if guild is None and len(guilds) == 1:
            guild = guilds[0]
        current = (self.get("s:bot.server_name") or "").strip()
        wanted = bool(guild) and current in ("", self.default_server) and guild.get("name") not in ("", None,
                                                                                                    current)
        if not wanted:
            if self.suggestion is not None and self.suggestion.winfo_exists():
                self.suggestion.destroy()
            self.suggestion = None
            return
        if self.suggestion is not None and self.suggestion.winfo_exists():
            return
        name = guild["name"]
        self.suggestion = W.InfoBar(self.suggest_box, "info", f"В Discord сервер называется «{name}»",
                                    f"Подставить это название вместо «{current or self.default_server}»?",
                                    actions=[("Подставить", lambda: self.apply_server_name(name))])
        self.suggestion.pack(fill="x", pady=(px(8), 0))

    def apply_server_name(self, name: str):
        self.set("s:bot.server_name", name)
        self.server.set(name)
        self.suggestion = None
