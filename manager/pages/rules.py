"""Правила сервера (rules.json): заголовок, вступление, разделы, наказания и подпись.

Предпросмотр собирает сообщение так же, как бот (cogs/rules.py: подстановки, нумерация пунктов, скрытые разделы
18+, не больше 10 карточек), и заранее предупреждает о том, что Discord не примет.
"""
import json
import re
import tkinter as tk
from tkinter import ttk

from .. import state, theme
from .. import widgets as W
from ..theme import C, font, px
from .base import Page

KEYS = ("title", "intro", "sections", "punishments", "footer")
GOLD, DARK_RED = 0xF1C40F, 0x992D22  # цвета первой и последней карточки бота: Colour.gold() и Colour.dark_red()
PUNISH_TITLE = "⚖️ Наказания"  # заголовок последней карточки, как в cogs/rules.py
MENTION = "<#" + "0" * 19 + ">"  # так упоминание канала занимает место в тексте сообщения
LIMIT_EMBEDS, LIMIT_TOTAL, LIMIT_TITLE, LIMIT_TEXT, LIMIT_FOOTER = 10, 6000, 256, 4096, 2048
EMBED_WIDTH = 520  # ширина карточки в Discord
PREVIEW_HEIGHT = 460

LINK, BOLD, ITALIC = "\x01", "\x02", "\x03"
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_CTRL = re.compile("([\x01\x02\x03])")
_WORDS = re.compile(r"\s+|\S+")


# ---------- данные ----------
def _number(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def _colour(value) -> str | None:
    """Цвет раздела так же, как его читает бот (config.colour); None — бот не поймёт значение."""
    try:
        n = int(str(value).lstrip("#"), 16) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None
    return f"#{n:06X}" if 0 <= n <= 0xFFFFFF else None


def _channel(value) -> str:
    return str(value.get("name") or "") if isinstance(value, dict) else str(value or "")


def _example() -> dict:
    try:
        with open(state.RULES_EXAMPLE, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")} if isinstance(data, dict) else {}


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def build_message(rules: dict, show: dict, count: dict, adult: bool) -> dict:
    """То же, что cogs/rules.build_embeds, но из черновика. show — подстановки для показа, count — для подсчёта
    символов (упоминание канала в сообщении длиннее его названия). Возвращает карточки, скрытые и не поместившиеся
    разделы, число символов и список проблем [(уровень, текст)]."""
    show, count = _Safe(show), _Safe(count)
    problems: list[tuple[str, str]] = []

    def fill(text, where: str) -> tuple[str, str]:
        text = "" if text is None else str(text)
        try:
            return text.format_map(show), text.format_map(count)
        except (ValueError, KeyError, IndexError, AttributeError, TypeError):
            note = (where + ": неправильно стоят фигурные скобки. Подстановки пишутся так: {server}, "
                    "а одиночную скобку нужно удвоить: {{ или }}.")
            if ("error", note) not in problems:
                problems.append(("error", note))
            return text, text

    embeds = []
    title, title_c = fill(rules.get("title"), "«Заголовок»")
    intro, intro_c = fill(rules.get("intro"), "«Вступление»")
    embeds.append({"label": "вступление", "title": title, "text": intro, "footer": "", "colour": f"#{GOLD:06X}",
                   "size": len(title_c) + len(intro_c), "title_len": len(title_c), "text_len": len(intro_c),
                   "limit_text": True})
    hidden = []
    for s in rules.get("sections") or []:
        if not isinstance(s, dict):
            continue
        raw = str(s.get("title") or "")
        label = "«" + (raw.strip() or "Без названия") + "»"
        if s.get("adult") and not adult:
            hidden.append(label)
            continue
        missing = [name for key, name in (("title", "название"), ("colour", "цвет"), ("items", "пункты"))
                   if key not in s]
        if missing:
            problems.append(("error", f"У раздела {label} не заполнено: {', '.join(missing)}."))
        head, head_c = fill(raw, "Раздел " + label)
        words = head_c.split()
        num = words[1].rstrip(".") if len(words) > 1 else str(len(embeds))  # номер пунктов — как в боте
        shown, counted = [], []
        for i, item in enumerate(s.get("items") or [], 1):
            a, b = fill(item, "Раздел " + label)
            shown.append(f"**{num}.{i}** {a}")
            counted.append(f"**{num}.{i}** {b}")
        text_c = "\n".join(counted)
        if len(text_c) > LIMIT_TEXT:
            problems.append(("warning", f"Раздел {label} длиннее {_number(LIMIT_TEXT)} символов, бот обрежет "
                                        "его окончание."))
        colour = _colour(s.get("colour"))
        if colour is None and "colour" in s:
            problems.append(("error", f"У раздела {label} неверный цвет. Выберите его заново."))
        embeds.append({"label": "раздел " + label, "title": head, "text": "\n".join(shown), "footer": "",
                       "colour": colour, "size": len(head_c) + min(len(text_c), LIMIT_TEXT),
                       "title_len": len(head_c), "text_len": 0, "limit_text": False})
    punish, punish_c = fill(rules.get("punishments"), "«Наказания»")
    footer, footer_c = fill(rules.get("footer"), "«Подпись»")
    embeds.append({"label": "наказания", "title": PUNISH_TITLE, "text": punish, "footer": footer,
                   "colour": f"#{DARK_RED:06X}", "size": len(PUNISH_TITLE) + len(punish_c) + len(footer_c),
                   "title_len": len(PUNISH_TITLE), "text_len": len(punish_c), "limit_text": True,
                   "footer_len": len(footer_c)})

    sent, dropped = embeds[:LIMIT_EMBEDS], embeds[LIMIT_EMBEDS:]
    total = sum(e["size"] for e in sent)
    for e in sent:
        name = e["label"][:1].upper() + e["label"][1:]
        if e["title_len"] > LIMIT_TITLE:
            problems.append(("error", f"{name}: заголовок длиннее {LIMIT_TITLE} символов."))
        if e["limit_text"] and e["text_len"] > LIMIT_TEXT:
            problems.append(("error", f"{name}: текст длиннее {_number(LIMIT_TEXT)} символов."))
        if e.get("footer_len", 0) > LIMIT_FOOTER:
            problems.append(("error", f"Подпись длиннее {_number(LIMIT_FOOTER)} символов."))
    if total > LIMIT_TOTAL:
        problems.append(("error", f"В правилах {_number(total)} символов, а Discord принимает до "
                                  f"{_number(LIMIT_TOTAL)} в одном сообщении. Сократите текст."))
    if dropped:
        problems.append(("warning", f"Discord показывает до {LIMIT_EMBEDS} карточек в одном сообщении, поэтому не "
                                    "попадут: " + ", ".join(e["label"] for e in dropped) + "."))
    problems.sort(key=lambda p: p[0] != "error")
    return {"embeds": sent, "dropped": dropped, "hidden": hidden, "total": total, "problems": problems}


# ---------- предпросмотр ----------
def _runs(line: str):
    """Строка → куски (текст, жирный, курсив, ссылка) по разметке Discord."""
    line = _BOLD.sub(lambda m: BOLD + m.group(1) + BOLD, line)
    line = _ITALIC.sub(lambda m: ITALIC + m.group(1) + ITALIC, line)
    bold = italic = link = False
    for part in _CTRL.split(line):
        if part == LINK:
            link = not link
        elif part == BOLD:
            bold = not bold
        elif part == ITALIC:
            italic = not italic
        elif part:
            yield part, bold, italic, link


def _shape(canvas, x1, y1, x2, y2, r, fill, round_left=True):
    """Прямоугольник со скруглёнными углами (у правой части карточки левые углы прямые)."""
    if round_left:
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    else:
        pts = [x1, y1, x1, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1, y2, x1, y2]
    return canvas.create_polygon(pts, smooth=True, fill=fill, outline="")


class _Writer:
    """Вёрстка текста на холсте: перенос по словам, **жирный**, *курсив*, упоминания каналов цветом ссылки."""

    def __init__(self, canvas: tk.Canvas):
        self.c = canvas
        self.fonts = {}
        for size, (regular, bold) in {"title": ("strong", "strong"), "body": ("body", "strong"),
                                      "footer": ("caption", "caption_strong")}.items():
            italic, bold_italic = font(regular).copy(), font(bold).copy()
            italic.configure(slant="italic")
            bold_italic.configure(slant="italic")
            self.fonts[size] = {(False, False): font(regular), (True, False): font(bold),
                                (False, True): italic, (True, True): bold_italic}
        self.line = {size: f[(False, False)].metrics("linespace") + px(4) for size, f in self.fonts.items()}

    def paragraph(self, text: str, x: int, y: int, width: int, size: str = "body", color: str = "text") -> int:
        """Нарисовать абзац с переносами и вернуть y под ним."""
        line_h, right, cx = self.line[size], x + width, x
        chunk: list[str] = []
        start, style = x, None

        def flush():
            if chunk:
                self.c.create_text(start, y, text="".join(chunk), font=style[0], fill=style[1], anchor="nw")
                chunk.clear()

        for part, bold, italic, link in _runs(text):
            f = self.fonts[size][(bold, italic)]
            key = (f, C("link") if link else C(color))
            for token in _WORDS.findall(part):
                if token.isspace():
                    if cx > x:  # пробелы в начале строки не рисуем
                        if key != style:
                            flush()
                            start, style = cx, key
                        chunk.append(" ")
                        cx += f.measure(" ")
                    continue
                w = f.measure(token)
                if cx + w > right and cx > x:
                    flush()
                    y += line_h
                    cx = x
                while w > width and len(token) > 1:  # слово длиннее строки — переносим по буквам
                    cut = len(token) - 1
                    while cut > 1 and f.measure(token[:cut]) > width:
                        cut -= 1
                    flush()
                    start, style = cx, key
                    chunk.append(token[:cut])
                    flush()
                    token = token[cut:]
                    w = f.measure(token)
                    y += line_h
                if key != style or not chunk:
                    flush()
                    start, style = cx, key
                chunk.append(token)
                cx += w
        flush()
        return y + line_h


class View(Page):
    description = "Правила сервера, которые бот публикует в канале правил."

    # ---------- раздел ----------
    def build(self):
        self._job = self._draw_job = None
        self._shown_problems = None
        self._drawn_width = 0
        self.model = None
        self.example = _example()

        W.InfoBar(self.body, "info", "Подстановки",
                  "{server} — название сервера, {games} — список игр, {welcome} — канал анкеты, {girls} и {boys} — "
                  "каналы 18+. Бот заменит их при публикации.", closable=False).pack(fill="x")

        W.section(self.body, "Публикация")
        g = W.Group(self.body)
        rules_channel = _channel(self.get("s:channels.rules")) or "правила"
        row = g.row("Опубликовать в Discord", f"Бот заменит своё прошлое сообщение в канале #{rules_channel} "
                                              "сохранённым текстом правил.", "upload")
        W.button(row.right, "Опубликовать", self.publish, "accent").pack(side="left")
        self.reset_row = g.row("Стандартные правила", "", "history")
        self.b_reset = W.button(self.reset_row.right, "Вернуть стандартные", self.reset)
        self.b_reset.pack(side="left")
        self.problems_box = tk.Frame(self.body, bg=W.bg_of(self.body))
        self.problems_box.pack(fill="x")

        W.section(self.body, "Начало", "Первая карточка сообщения с правилами.")
        g = W.Group(self.body)
        row = g.row("Заголовок", "Крупная строка над вступлением.")
        self.e_title = self.bind_entry(row.right, "r:title", 40)
        self.e_title.pack(side="left")
        self.t_intro = self._text_block(g, "Вступление", "Поддерживается разметка Discord: **жирный**, *курсив*.",
                                        "r:intro")

        W.section(self.body, "Разделы", "Каждый раздел — отдельная карточка с цветной полосой, пункты нумеруются "
                                        "сами.")
        g = W.Group(self.body)
        fields = [
            {"key": "title", "label": "Название", "required": True,
             "hint": "Номер после значка задаёт нумерацию пунктов: 1.1, 1.2 и далее."},
            {"key": "colour", "label": "Цвет полосы", "kind": "color"},
            {"key": "items", "label": "Пункты", "kind": "multiline", "height": 9,
             "hint": "Каждый пункт — с новой строки."},
            {"key": "adult", "label": "Только при включённых каналах 18+", "kind": "bool",
             "hint": "Раздел появится в правилах, только если каналы 18+ включены в разделе «Функции»."},
        ]
        self.sections = W.ListEditor(
            g.block(), self, "r:sections",
            [("title", "Раздел", 380), ("items", "Пунктов", 90), ("colour", "Цвет", 100), ("adult", "Только 18+", 110)],
            fields, self._to_row, self._to_form, self._from_form,
            new=lambda: {"title": "", "colour": None, "items": "", "adult": False},
            noun="раздел", height=7, validate=self._validate)
        self.sections.pack(fill="x")

        W.section(self.body, "Наказания и подпись", "Последняя карточка сообщения.")
        g = W.Group(self.body)
        self.t_punish = self._text_block(g, "Наказания", "Текст под заголовком «Наказания»: какие бывают наказания "
                                                         "и куда сообщать о нарушениях.", "r:punishments")
        row = g.row("Подпись", "Мелкий текст в самом низу правил.")
        self.e_footer = self.bind_entry(row.right, "r:footer", 40)
        self.e_footer.pack(side="left")

        W.section(self.body, "Предпросмотр", "Так правила будут выглядеть в Discord, включая несохранённые "
                                             "изменения.")
        g = W.Group(self.body)
        self.size_row = g.row("Размер сообщения", f"Discord принимает до {LIMIT_EMBEDS} карточек и "
                                                  f"{_number(LIMIT_TOTAL)} символов в одном сообщении.", "info")
        self.size_label = W.label(self.size_row.right, "", "body", "text2")
        self.size_label.pack(side="left")
        box = g.block(padding=(18, 16))
        self.canvas = tk.Canvas(box, bg=W.bg_of(box), highlightthickness=0, bd=0, height=px(240),
                                yscrollincrement=px(16))
        self.vbar = ttk.Scrollbar(box, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.writer = _Writer(self.canvas)
        self._refresh()

    def _text_block(self, group, title: str, description: str, path: str) -> tk.Text:
        blk = group.block()
        W.label(blk, title, "body").pack(anchor="w")
        d = W.label(blk, description, "caption", "text2")
        d.pack(anchor="w", fill="x", pady=(px(2), px(10)))
        W.autowrap(d)
        box = self.bind_text(blk, path, height=4)
        box.pack(fill="x")
        return box

    def on_show(self):
        self._schedule(0)  # подстановки зависят от других разделов (название сервера, игры, каналы)

    def set(self, path: str, value):
        super().set(path, value)
        self._schedule()

    def destroy(self):
        for job in (getattr(self, "_job", None), getattr(self, "_draw_job", None)):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()

    # ---------- таблица разделов ----------
    @staticmethod
    def _to_row(s: dict):
        return (s.get("title", ""), len(s.get("items") or []), s.get("colour", ""), "Да" if s.get("adult") else "")

    @staticmethod
    def _to_form(s: dict) -> dict:
        return {"title": s.get("title", ""), "colour": _colour(s.get("colour")), "adult": bool(s.get("adult")),
                "items": "\n".join(str(x) for x in s.get("items") or [])}

    @staticmethod
    def _from_form(data: dict, old: dict | None) -> dict:
        item = dict(old or {})  # неизвестные ключи раздела сохраняются
        item["title"] = data["title"].strip()
        item["colour"] = data["colour"]
        if data["adult"]:
            item["adult"] = True
        else:
            item.pop("adult", None)
        item["items"] = [x.strip() for x in data["items"].splitlines() if x.strip()]
        return item

    @staticmethod
    def _validate(data: dict) -> str | None:
        if not any(x.strip() for x in data["items"].splitlines()):
            return "Добавьте хотя бы один пункт."
        if len(data["title"].strip()) > LIMIT_TITLE:
            return f"Название длиннее {LIMIT_TITLE} символов: Discord его не примет."
        return None

    # ---------- действия ----------
    def publish(self):
        model = self._build()
        errors = [text for level, text in model["problems"] if level == "error"]
        if errors:
            self.app.notify("error", "Правила не опубликуются", errors[0])
            return
        token, guild = self.get("e:DISCORD_TOKEN") or "", str(self.get("e:GUILD_ID") or "").strip()
        if not state.token_looks_valid(token) or not guild:
            self.app.notify("warning", "Бот не подключён", "Укажите ключ бота и сервер в разделе «Подключение».",
                            actions=[("Открыть «Подключение»", lambda: self.app.goto("connection"))])
            return
        if not self.app.ensure_saved("Правила публикуются из сохранённого файла."):
            return
        self.app.run_task("Публикация правил", state.tool_args("build_server.py", "--rules-only"),
                          "Бот заменит своё сообщение в канале правил. Обычно это занимает до минуты.",
                          success="Правила опубликованы", failure="Не удалось опубликовать правила")

    def reset(self):
        if not self.example:
            self.app.notify("error", "Шаблон правил не найден", "В папке бота нет файла rules.example.json.")
            return
        if not self.app.confirm("Вернуть стандартные правила?",
                                "Заголовок, вступление, разделы, наказания и подпись заменятся текстом из шаблона. "
                                "До сохранения это можно отменить.", ok="Вернуть", danger=True):
            return
        for key in KEYS:
            if key in self.example:
                self.set("r:" + key, self.example[key])
        self.e_title.set(self.get("r:title") or "")
        self.e_footer.set(self.get("r:footer") or "")
        for box, path in ((self.t_intro, "r:intro"), (self.t_punish, "r:punishments")):
            box.delete("1.0", "end")
            box.insert("1.0", self.get(path) or "")
            box.edit_modified(False)
        self.sections.refresh()
        self._schedule(0)

    # ---------- обновление ----------
    def _schedule(self, delay: int = 250):
        if getattr(self, "_job", None):
            self.after_cancel(self._job)
        self._job = self.after(delay, self._refresh)

    def _build(self) -> dict:
        server = self.get("s:bot.server_name") or ""
        games = ", ".join(str(g.get("name", "")) for g in self.get("s:games") or [] if isinstance(g, dict))
        names = {"welcome": _channel(self.get("s:channels.welcome")),
                 "girls": _channel(self.get("s:adult.girls_channel")),
                 "boys": _channel(self.get("s:adult.boys_channel"))}
        show = {"server": server, "games": games, **{k: LINK + "#" + v + LINK for k, v in names.items()}}
        count = {"server": server, "games": games, **{k: MENTION for k in names}}
        rules = {k: self.get("r:" + k) for k in KEYS}
        return build_message(rules, show, count, bool(self.get("s:modules.adult_channels")))

    def _refresh(self):
        self._job = None
        if not self.winfo_exists():
            return
        self.model = model = self._build()
        self._show_problems(model["problems"])
        cards = len(model["embeds"])
        over = model["total"] > LIMIT_TOTAL or bool(model["dropped"])
        self.size_label.configure(
            text=f"{cards} {_plural(cards, 'карточка', 'карточки', 'карточек')}, {_number(model['total'])} из "
                 f"{_number(LIMIT_TOTAL)} символов", fg=C("error" if over else "text2"))
        same = bool(self.example) and all(self.get("r:" + k) == self.example.get(k) for k in KEYS)
        self.b_reset.state(["disabled"] if same else ["!disabled"])
        self.reset_row.set_description("Сейчас используется стандартный текст правил." if same else
                                       "Текст из шаблона заменит ваши правила. До сохранения это можно отменить.")
        self._draw()

    def _show_problems(self, problems):
        key = tuple(problems)
        if key == self._shown_problems:
            return
        self._shown_problems = key
        for child in self.problems_box.winfo_children():
            child.destroy()
        if not problems:
            return
        errors = any(level == "error" for level, _ in problems)
        title = "Discord не примет правила в таком виде" if errors else "Часть правил не попадёт в Discord"
        message = "\n".join(text for _, text in problems[:4])
        W.InfoBar(self.problems_box, "error" if errors else "warning", title, message, closable=False).pack(
            fill="x", pady=(px(10), 0))

    # ---------- холст ----------
    def _on_canvas_resize(self, e):
        if abs(e.width - self._drawn_width) > 2 and self.model is not None:
            if self._draw_job:
                self.after_cancel(self._draw_job)
            self._draw_job = self.after(60, self._draw)

    def _on_yscroll(self, first, last):
        self.vbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.vbar.pack_forget()
        elif not self.vbar.winfo_ismapped():
            self.vbar.pack(side="right", fill="y", padx=(px(8), 0), before=self.canvas)

    def _wheel(self, e):
        first, last = self.canvas.yview()
        step = -1 if e.delta > 0 else 1
        if (step < 0 and first <= 0) or (step > 0 and last >= 1):
            return None  # предпросмотр в конце — прокручивается страница
        self.canvas.yview_scroll(step * 3, "units")
        return "break"

    def _bot_name(self) -> str:
        info = getattr(self.app, "discord_info", None) or {}
        return self.get("s:bot.nickname_on_server") or info.get("bot") or self.get("s:bot.name") or "Бот"

    def _draw(self):
        self._draw_job = None
        c, model = self.canvas, self.model
        if model is None or not c.winfo_exists():
            return
        c.delete("all")
        width = c.winfo_width()
        if width <= 1:
            width = px(820)
        self._drawn_width = width
        avatar = theme.app_icon_image(40)
        if avatar:
            c.create_image(0, 0, image=avatar, anchor="nw")
        x = px(56)
        name = self._bot_name()
        c.create_text(x, px(1), text=name, font=font("strong"), fill=C("text"), anchor="nw")
        tag_x = x + font("strong").measure(name) + px(8)
        tag_w = font("caption_strong").measure("БОТ") + px(10)
        _shape(c, tag_x, px(3), tag_x + tag_w, px(19), px(3), C("accent"))
        c.create_text(tag_x + tag_w / 2, px(11), text="БОТ", font=font("caption_strong"), fill=C("on_accent"))
        y = px(28)
        card_w = max(px(240), min(width - x - px(4), px(EMBED_WIDTH)))
        for embed in model["embeds"]:
            y = self._draw_embed(x, y, card_w, embed) + px(6)
        notes = [f"Скрыт раздел {label}: каналы 18+ выключены." for label in model["hidden"]]
        notes += [f"Не поместится: {e['label']}." for e in model["dropped"]]
        if notes:
            y += px(4)
            for note in notes:
                y = self.writer.paragraph(note, x, y, card_w, "footer", "text3")
        height = y + px(4)
        c.configure(scrollregion=(0, 0, width, height), height=min(height, px(PREVIEW_HEIGHT)))

    def _draw_embed(self, x: int, y: int, width: int, embed: dict) -> int:
        c, top = self.canvas, y
        text_x, text_w = x + px(16), width - px(32)
        y += px(10)
        if embed["title"].strip():
            y = self.writer.paragraph(embed["title"], text_x, y, text_w, "title") + px(4)
        for line in embed["text"].split("\n"):
            if line.strip():
                y = self.writer.paragraph(line, text_x, y, text_w, "body")
            else:
                y += self.writer.line["body"]
        if embed["footer"].strip():
            y += px(8)
            y = self.writer.paragraph(embed["footer"], text_x, y, text_w, "footer", "text2")
        y += px(10)
        stripe = _shape(c, x, top, x + px(10), y, px(4), embed["colour"] or C("border"))
        card = _shape(c, x + px(4), top, x + width, y, px(4), C("card2"), round_left=False)
        c.tag_lower(card)
        c.tag_lower(stripe)
        return y
