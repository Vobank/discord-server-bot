"""Роли: администрация и участники, пол, роли за сообщения, достижения, именные роли, подсказки
для админ-панели и роли других ботов. Бот находит роли по названию, поэтому здесь в основном названия."""
import tkinter as tk

from .. import widgets as W
from ..theme import C, px
from .base import Page
from .games import ListEditor, is_emoji, merge_item

MAX_NAME = 100  # длина названия роли в Discord
MAX_COUNT = 10_000_000

STAFF = [
    ("s:roles.head_admin", "Главный админ", "Полный доступ к серверу через право «Администратор» в Discord.", "admin"),
    ("s:roles.head_mod", "Главный модератор", "Кик, бан и тайм-ауты, ники и голосовые каналы, вся админка.", "shield"),
    ("s:roles.staff", "Администрация", "Админ-панель бота, админ-чат и журнал действий.", "group"),
    ("s:roles.mod", "Модератор", "Тайм-ауты и удаление сообщений через мод-панель.", "people"),
]
MEMBERS = [
    ("s:roles.base", "Участник", "Выдаётся после анкеты и открывает каналы сервера.", "contact"),
    ("s:roles.pending", "Новичок без анкеты", "Пока анкеты нет, участник видит только правила и канал с анкетой.",
     "lock"),
]
STATS = [
    ("voice_min", "Минут в голосовых"),
    ("screens", "Картинок в каналах «скриншоты»"),
    ("night", "Сообщений ночью"),
    ("tracks", "Включённых треков"),
    ("best_streak", "Дней подряд в чате"),
    ("games", "Выбранных игр"),
    ("days", "Дней на сервере"),
    ("stars", "Сообщений в зале славы"),
]
STAT_NAMES = dict(STATS)
MESSAGES = ("сообщение", "сообщения", "сообщений")


def number(n) -> str:
    """1000 → «1 000» (между разрядами неразрывный пробел)."""
    return f"{n:,}".replace(",", " ") if isinstance(n, int) else str(n)


def plural(n: int, forms: tuple) -> str:
    """plural(5, MESSAGES) → «сообщений»."""
    n = abs(int(n)) % 100
    if 10 < n < 20:
        return forms[2]
    n %= 10
    return forms[0] if n == 1 else forms[1] if 2 <= n <= 4 else forms[2]


def hex_colour(value) -> str:
    """Цвет из настроек («#1abc9c» или число) → «#1ABC9C»."""
    if isinstance(value, int):
        return f"#{value:06X}"
    return str(value or "").upper()


def same(a: str, b: str) -> bool:
    return str(a).strip().casefold() == str(b).strip().casefold()


def swatch_image(colour: str, size: int):
    """Скруглённый квадратик цвета роли для строки таблицы; None, если цвет не разобрать."""
    try:
        from PIL import Image, ImageDraw, ImageTk
        big = size * 4
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, big - 1, big - 1), radius=big // 4, fill=colour,
                                              outline=C("border"), width=4)
        return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
    except Exception:
        return None


class RoleEditor(ListEditor):
    """ListEditor для данных, которые хранятся не простым списком: reader() → список элементов,
    writer(items) — записать в черновик (словарь, сразу два пути). colour(item) → образец цвета в начале строки."""

    def __init__(self, parent, page, path, *, reader=None, writer=None, colour=None, **kw):
        self.reader, self.writer, self.colour = reader, writer, colour
        self.swatches = {}
        super().__init__(parent, page, path, **kw)

    def items(self) -> list:
        return self.reader() if self.reader else super().items()

    def _store(self, items, select=None):
        if not self.writer:
            return super()._store(items, select)
        chosen = items[select] if select is not None and 0 <= select < len(items) else None
        self.writer(items)
        fresh = self.items()  # порядок мог поменяться (сортировка) — выделяем тот же элемент
        self.refresh(fresh.index(chosen) if chosen in fresh else None)
        if self.on_change:
            self.on_change(fresh)

    def refresh(self, select=None):
        super().refresh(select)
        if not self.colour:
            return
        self.tree.configure(show=("tree", "headings"))
        self.tree.column("#0", width=px(46), minwidth=px(46), stretch=False)
        for i, item in enumerate(self.items()):
            self.tree.item(str(i), image=self.swatch(self.colour(item)) or "")

    def swatch(self, colour):
        key = hex_colour(colour)
        if key not in self.swatches:
            self.swatches[key] = swatch_image(key, px(14))
        return self.swatches[key]


class View(Page):
    description = "Названия ролей, которые бот создаёт и выдаёт. Если роль с таким названием уже есть, бот возьмёт её."

    def build(self):
        W.InfoBar(self.body, "info", "Бот находит роли по названию",
                  "Если переименуете роль в Discord, поменяйте название и здесь, иначе бот создаст новую.",
                  closable=False).pack(fill="x")

        W.section(self.body, "Администрация")
        g = W.Group(self.body)
        for path, title, desc, icon in STAFF:
            self.name_entry(g.row(title, desc, icon), path)

        W.section(self.body, "Участники")
        g = W.Group(self.body)
        for path, title, desc, icon in MEMBERS:
            self.name_entry(g.row(title, desc, icon), path)

        self.build_genders()
        self.build_levels()
        self.build_achievements()
        self.build_custom()
        self.build_hints()

        W.section(self.body, "Роли других ботов", "Для бота экономики и других ботов, которые сами выдают роли.")
        g = W.Group(self.body)
        row = g.row("Роли ботов", "Бот ставит их в самый низ списка ролей, и такие боты не могут выдавать роли сервера.",
                    "robot")
        self.bind_entry(row.right, "s:limited_bot_roles", 26, kind="list", placeholder="Через запятую").pack(
            side="left")
        row = g.row("Роли магазина", "Роли, которые эти боты продают: они стоят ещё ниже, чтобы боты могли их выдавать.",
                    "tag")
        self.bind_entry(row.right, "s:shop_roles", 26, kind="list", placeholder="Через запятую").pack(side="left")
        row = g.row("Невидимки",
                    "ID участников, которых на сервере как будто нет: бот прячет их роли и ник, не даёт их тегнуть, "
                    "не считает уровни и достижения. Убрали ID — роли и ник вернутся. Роль бота должна стоять выше "
                    "их ролей.", "hide")
        self.bind_entry(row.right, "s:ghosts", 26, kind="list", placeholder="ID через запятую").pack(side="left")

    def on_show(self):
        self.show_levels_note()

    def name_entry(self, row, path: str):
        entry = self.bind_entry(row.right, path, 26)
        entry.validate = lambda raw: 0 < len(raw.strip()) <= MAX_NAME  # без названия бот не создаст роль
        entry.pack(side="left")
        return entry

    # ---------- пол ----------
    def build_genders(self):
        W.section(self.body, "Пол", "Первый шаг анкеты: участник нажимает кнопку и получает роль.")
        box = W.Group(self.body).block()
        self.genders = ListEditor(
            box, self, "s:genders", noun="вариант пола", height=5, validate=self.validate_gender,
            columns=[("role", "Роль", 240), ("emoji", "Значок на кнопке", 170), ("label", "Подпись", 260)],
            fields=[
                {"key": "role", "label": "Роль", "required": True,
                 "hint": "Её получает участник, который нажал кнопку."},
                {"key": "emoji", "label": "Значок на кнопке", "required": True, "hint": "Один эмодзи."},
                {"key": "label", "label": "Подпись на кнопке", "required": True},
            ],
            to_row=lambda g: tuple((list(g) + ["", "", ""])[:3]),
            to_form=lambda g: dict(zip(("role", "emoji", "label"), (list(g) + ["", "", ""])[:3])),
            from_form=lambda data, old: [data["role"], data["emoji"], data["label"], *list(old or [])[3:]],
            removal=lambda g: ("Удалить вариант?", f"Кнопка «{g[2]}» пропадёт из анкеты. "
                                                   f"Роль «{g[0]}» на сервере останется."),
            empty="Вариантов пока нет. Добавьте хотя бы один, иначе новички не смогут пройти анкету.")
        self.genders.pack(fill="both", expand=True)

    def validate_gender(self, data: dict) -> str | None:
        if any(same(g[0], data["role"]) for g in self.genders.others() if g):
            return f"Вариант с ролью «{data['role']}» уже есть."
        if len(data["role"]) > MAX_NAME:
            return f"Название роли — не длиннее {MAX_NAME} символов."
        if not is_emoji(data["emoji"]):
            return "Значок — это один эмодзи, без букв и цифр."
        if len(data["label"]) > 80:
            return "Подпись не помещается на кнопку: максимум 80 символов."
        return None

    # ---------- роли за сообщения ----------
    def build_levels(self):
        W.section(self.body, "Роли за сообщения",
                  "Роль выдаётся, когда участник напишет нужное число сообщений, и остаётся у него.")
        self.levels_note = tk.Frame(self.body, bg=C("bg"))
        self.levels_note.pack(fill="x")
        self.levels_off = None
        box = W.Group(self.body).block()
        self.levels = RoleEditor(
            box, self, "s:levels.roles", noun="роль за сообщения", height=6, reorder=False,
            reader=self.level_roles, writer=self.store_level_roles, validate=self.validate_level,
            columns=[("messages", "Сообщений", 150), ("role", "Роль", 520)],
            fields=[
                {"key": "messages", "label": "Число сообщений", "kind": "int", "min": 1, "max": MAX_COUNT,
                 "width": 12},
                {"key": "role", "label": "Роль", "required": True},
            ],
            to_row=lambda x: (number(x["messages"]), x["role"]), to_form=dict,
            from_form=lambda data, old: {"messages": data["messages"], "role": data["role"]},
            new=lambda: {"messages": min(MAX_COUNT, max([x["messages"] for x in self.level_roles()] or [0]) + 1000)},
            removal=lambda x: ("Удалить роль за сообщения?",
                               f"Бот перестанет выдавать «{x['role']}» за {number(x['messages'])} "
                               f"{plural(x['messages'], MESSAGES)}. Сама роль на сервере останется."),
            empty="Ролей за сообщения пока нет.")
        self.levels.pack(fill="both", expand=True)
        self.show_levels_note()

    def level_roles(self) -> list[dict]:
        out = []
        for key, role in (self.get("s:levels.roles", {}) or {}).items():
            try:
                out.append({"messages": int(key), "role": str(role)})
            except (TypeError, ValueError):
                continue
        return sorted(out, key=lambda x: x["messages"])

    def store_level_roles(self, items):
        ordered = sorted(items, key=lambda x: x["messages"])
        self.set("s:levels.roles", {str(x["messages"]): x["role"] for x in ordered})

    def validate_level(self, data: dict) -> str | None:
        count = data["messages"]
        taken = next((x for x in self.levels.others() if x["messages"] == count), None)
        if taken:
            return f"За {number(count)} {plural(count, MESSAGES)} уже выдаётся роль «{taken['role']}»."
        if len(data["role"]) > MAX_NAME:
            return f"Название роли — не длиннее {MAX_NAME} символов."
        return None

    def show_levels_note(self):
        """Роли за сообщения и достижения работают, только когда включены уровни (раздел «Функции»)."""
        off = not self.get("s:modules.levels", True)
        if off == self.levels_off:
            return
        self.levels_off = off
        for child in self.levels_note.winfo_children():
            child.destroy()
        if off:
            W.InfoBar(self.levels_note, "warning", "Уровни выключены",
                      "Пока функция уровней выключена, бот не выдаёт роли за сообщения и достижения.",
                      actions=[("Открыть «Функции»", lambda: self.app.goto("features"))],
                      closable=False).pack(fill="x", pady=(0, px(8)))

    # ---------- достижения ----------
    def build_achievements(self):
        W.section(self.body, "Достижения",
                  "Бот сам выдаёт роль, когда участник выполнит условие, и пишет об этом в канале достижений.")
        box = W.Group(self.body).block()
        self.achievements = RoleEditor(
            box, self, "s:achievements", noun="достижение", height=10, validate=self.validate_achievement,
            colour=lambda a: a.get("colour"),
            columns=[("role", "Роль", 270), ("need", "Условие", 330), ("colour", "Цвет", 110)],
            fields=[
                {"key": "role", "label": "Роль", "required": True},
                {"key": "desc", "label": "Описание", "required": True,
                 "hint": "Его видят участники в сообщении о награде и в списке достижений."},
                {"key": "stat", "label": "Что считать", "kind": "choice", "choices": STATS},
                {"key": "need", "label": "Сколько нужно", "kind": "int", "min": 1, "max": MAX_COUNT},
                {"key": "colour", "label": "Цвет роли", "kind": "color"},
            ],
            to_row=self.achievement_row,
            to_form=lambda a: {"role": a.get("role", ""), "desc": a.get("desc", ""), "stat": a.get("stat"),
                               "need": a.get("need"), "colour": hex_colour(a.get("colour")) or None},
            from_form=lambda data, old: merge_item(old, data),
            new=lambda: {"stat": STATS[0][0], "need": 10},
            removal=lambda a: ("Удалить достижение?", f"Бот перестанет выдавать «{a.get('role', '')}». "
                                                      "Сама роль на сервере останется."),
            empty="Достижений пока нет.")
        self.achievements.pack(fill="both", expand=True)

    @staticmethod
    def achievement_row(a: dict) -> tuple:
        stat = STAT_NAMES.get(a.get("stat"), str(a.get("stat", "")))
        return a.get("role", ""), f"{number(a.get('need', 0))} · {stat[:1].lower()}{stat[1:]}", hex_colour(a.get("colour"))

    def validate_achievement(self, data: dict) -> str | None:
        if any(same(a.get("role", ""), data["role"]) for a in self.achievements.others()):
            return f"Достижение с ролью «{data['role']}» уже есть."
        if len(data["role"]) > MAX_NAME:
            return f"Название роли — не длиннее {MAX_NAME} символов."
        return None

    # ---------- именные роли ----------
    def build_custom(self):
        W.section(self.body, "Именные роли", "Роли со своим цветом. Порядок строк — порядок этих ролей на сервере.")
        box = W.Group(self.body).block()
        self.custom = RoleEditor(
            box, self, "s:custom_roles", noun="именная роль", height=8, validate=self.validate_custom,
            reader=self.custom_roles, writer=self.store_custom_roles, colour=lambda r: r["colour"],
            columns=[("name", "Роль", 300), ("colour", "Цвет", 110), ("owner", "Владелец", 260)],
            fields=[
                {"key": "name", "label": "Название роли", "required": True},
                {"key": "colour", "label": "Цвет", "kind": "color"},
                {"key": "owner", "label": "Владелец", "placeholder": "Не указан",
                 "hint": "Часть ника на сервере: бот выдаст роль участнику, в нике которого есть этот текст."},
            ],
            to_row=lambda r: (r["name"], hex_colour(r["colour"]), r["owner"]),
            to_form=lambda r: {"name": r["name"], "colour": hex_colour(r["colour"]) or None, "owner": r["owner"]},
            from_form=self.custom_from_form,
            removal=lambda r: ("Удалить именную роль?", f"Бот перестанет следить за ролью «{r['name']}». "
                                                        "Сама роль на сервере останется."),
            empty="Именных ролей пока нет.")
        self.custom.pack(fill="both", expand=True)

    def custom_roles(self) -> list[dict]:
        owners = self.get("s:custom_role_owners", {}) or {}
        out = []
        for entry in self.get("s:custom_roles", []) or []:
            name, colour = (list(entry) + ["", ""])[:2]
            out.append({"name": name, "colour": colour, "owner": owners.get(name, "")})
        return out

    def store_custom_roles(self, items):
        """Роли — в custom_roles, владельцы — в custom_role_owners. Владельцы других ролей не трогаем."""
        listed = {r["name"] for r in self.custom_roles()}
        owners = {k: v for k, v in (self.get("s:custom_role_owners", {}) or {}).items() if k not in listed}
        owners.update((r["name"], r["owner"]) for r in items if r["owner"])
        self.set("s:custom_roles", [[r["name"], r["colour"]] for r in items])
        self.set("s:custom_role_owners", owners)

    def custom_from_form(self, data: dict, old: dict | None) -> dict:
        if old and old["name"] != data["name"]:
            self.rename_hint(old["name"], data["name"])
        return {"name": data["name"], "colour": data["colour"], "owner": data["owner"]}

    def validate_custom(self, data: dict) -> str | None:
        if any(same(r["name"], data["name"]) for r in self.custom.others()):
            return f"Роль «{data['name']}» уже есть в списке."
        if len(data["name"]) > MAX_NAME:
            return f"Название роли — не длиннее {MAX_NAME} символов."
        return None

    # ---------- подсказки в админ-панели ----------
    def build_hints(self):
        W.section(self.body, "Подсказки в админ-панели",
                  "Администрация видит их, когда выдаёт роли через админ-панель: кому и за что давать роль.")
        box = W.Group(self.body).block()
        self.hints = RoleEditor(
            box, self, "s:role_descriptions", noun="подсказка", height=8, reorder=False,
            reader=self.role_hints, writer=lambda items: self.set("s:role_descriptions",
                                                                  {h["role"]: h["text"] for h in items}),
            validate=self.validate_hint,
            columns=[("role", "Роль", 260), ("text", "Подсказка", 520)],
            fields=[
                {"key": "role", "label": "Роль", "required": True, "hint": "Название роли — как на сервере."},
                {"key": "text", "label": "Подсказка", "kind": "multiline", "required": True, "height": 3},
            ],
            to_row=lambda h: (h["role"], " ".join(h["text"].split())), to_form=dict,
            from_form=lambda data, old: {"role": data["role"], "text": data["text"].strip()},
            removal=lambda h: ("Удалить подсказку?", f"Подсказка для роли «{h['role']}» пропадёт из админ-панели."),
            empty="Своих подсказок пока нет. Для ролей, которые бот выдаёт сам, он пишет подсказки без вас.")
        self.hints.pack(fill="both", expand=True)

    def role_hints(self) -> list[dict]:
        return [{"role": k, "text": str(v)} for k, v in (self.get("s:role_descriptions", {}) or {}).items()]

    def rename_hint(self, old: str, new: str):
        """Именную роль переименовали — её подсказка переезжает вместе с ней."""
        texts = self.get("s:role_descriptions", {}) or {}
        if old in texts and new not in texts:
            self.set("s:role_descriptions", {new if k == old else k: v for k, v in texts.items()})
            self.hints.refresh()

    def validate_hint(self, data: dict) -> str | None:
        if any(same(h["role"], data["role"]) for h in self.hints.others()):
            return f"Подсказка для роли «{data['role']}» уже есть."
        return None
