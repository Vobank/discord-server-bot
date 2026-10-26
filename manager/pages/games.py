"""Игры и отделы: игры анкеты новичка, их роли и категории каналов, приставка роли администратора отдела.

Раздел — пример W.ListEditor: таблица, форма с проверкой (validate=) и подтверждение удаления.
Небольшое расширение редактора (класс ListEditor ниже) использует и раздел «Роли».
"""
import re

from .. import widgets as W
from ..theme import C, font, px
from .base import Page

MAX_GAMES = 20  # кнопки игр в анкете стоят по 4 в ряд, а рядов у сообщения Discord не больше пяти
DEFAULT_EMOJI = "\U0001F3AE"  # значок новой игры (джойстик), его можно поменять в форме
DISCORD_ID = re.compile(r"\d{15,21}")
CUSTOM_EMOJI = re.compile(r"<a?:\w{2,32}:\d{15,21}>")
KEYCAP = re.compile("[0-9#*]️?⃣")
INVISIBLE = dict.fromkeys(map(ord, "️‍"))  # Tk не склеивает составные эмодзи, эти символы только мешают


def is_emoji(text: str) -> bool:
    """Похоже на один эмодзи: без букв, цифр и пробелов. Свой эмодзи сервера — <:имя:id>."""
    if CUSTOM_EMOJI.fullmatch(text) or KEYCAP.fullmatch(text):
        return True
    return 0 < len(text) <= 16 and not any(ch.isalnum() or ch.isspace() for ch in text)


def split_names(text: str) -> list[str]:
    """«a, b, c» → ['a', 'b', 'c']."""
    return [x.strip() for x in text.split(",") if x.strip()]


def merge_item(old: dict | None, new: dict) -> dict:
    """Элемент списка после формы: незнакомые ключи и их порядок сохраняются, None убирает ключ."""
    out = dict(old or {})
    for key, value in new.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def clip(text: str, width: int, fnt) -> str:
    """Обрезать текст с многоточием, чтобы он помещался в width пикселей."""
    if fnt.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fnt.measure(text[:mid].rstrip() + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


class ListEditor(W.ListEditor):
    """W.ListEditor с доработками:
    removal(item) → (заголовок, текст) — удаление с подтверждением;
    empty — подсказка в пустой таблице; limit=(число, текст) — сколько элементов можно добавить;
    editing — номер элемента, открытого в форме (None — добавление): validate ищет повторы через others();
    fixed — колонки, которые не растягиваются. Таблица растёт по числу строк (до height), длинный текст
    в ячейках обрезается многоточием."""

    EMPTY_ROWS = 3

    def __init__(self, parent, page, path, *, removal=None, empty: str = "", limit=None, fixed=(), **kw):
        self.editing = None
        self.removal, self.limit = removal, limit
        self.empty_text, self.empty_label = empty, None
        self.max_rows = kw.get("height", 6)
        self.rows, self._fit_job, self.fixed = [], None, set(fixed)
        super().__init__(parent, page, path, **kw)
        for key in fixed:
            self.tree.column(key, stretch=False)
        self.tree.bind("<Configure>", self._schedule_fit, add="+")
        self.tree.bind("<ButtonRelease-1>", self._schedule_fit, add="+")  # после перетаскивания границы колонки

    def others(self) -> list:
        """Все элементы, кроме открытого в форме."""
        return [x for i, x in enumerate(self.items()) if i != self.editing]

    def add(self):
        if self.limit and len(self.items()) >= self.limit[0]:
            self.page.app.message("Список заполнен", self.limit[1])
            return
        self.editing = None
        super().add()

    def edit(self):
        self.editing = self.table.selected()
        try:
            super().edit()
        finally:
            self.editing = None

    def delete(self):
        i = self.table.selected()
        if i is None:
            return
        if self.removal:
            title, text = self.removal(self.items()[i])
            if not self.page.app.confirm(title, text, ok="Удалить", danger=True):
                return
        super().delete()

    def refresh(self, select=None):
        super().refresh(select)
        items = self.items()
        self.rows = [self.to_row(x) for x in items]
        self.tree.configure(height=min(len(items), self.max_rows) if items else self.EMPTY_ROWS)
        self.fit()
        if not self.empty_text:
            return
        if self.empty_label is None:  # фон под строками таблицы — цвета страницы
            self.empty_label = W.label(self.tree, self.empty_text, "body", "text2", wrap=420, justify="center",
                                       anchor="center")
            self.empty_label.configure(bg=C("bg"))
        if items:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.6, anchor="center")

    def _schedule_fit(self, _=None):
        if self._fit_job is None:
            self._fit_job = self.after_idle(self.fit)

    def fit(self):
        self._fit_job = None
        fnt = font("body")
        widths = [None if c[0] in self.fixed else int(self.tree.column(c[0], "width")) - px(14)
                  for c in self.table.columns]
        for i, row in enumerate(self.rows):
            values = ["" if v is None else str(v).translate(INVISIBLE) for v in row]
            self.tree.item(str(i), values=[v if w is None else clip(v, w, fnt) for v, w in zip(values, widths)])


FIELDS = [
    {"key": "name", "label": "Название игры", "required": True},
    {"key": "emoji", "label": "Значок", "required": True,
     "hint": "Один эмодзи для кнопки в анкете и названий каналов отдела."},
    {"key": "role", "label": "Роль игроков", "placeholder": "Как название"},
    {"key": "extra_roles", "label": "Дополнительные роли отдела", "placeholder": "Через запятую",
     "hint": "Их выдаёт администратор отдела, например роль тестировщика."},
    {"key": "category_id", "label": "ID существующей категории", "placeholder": "Не указан",
     "hint": "Такую категорию бот не перестраивает, а только даёт права администратору отдела."},
    {"key": "category", "label": "Название новой категории", "placeholder": "Значок и название игры",
     "hint": "Если ID не указан, бот создаст категорию с новостями, чатом, скриншотами и голосовыми."},
]


class View(Page):
    description = "Игры для анкеты новичка. У каждой игры своя роль, категория каналов и администратор отдела."

    def build(self):
        W.section(self.body, "Игры", "Порядок строк — это порядок кнопок в анкете.")
        box = W.Group(self.body).block()
        self.games = ListEditor(
            box, self, "s:games", noun="игра", height=8, validate=self.validate, fixed=("emoji",),
            columns=[("emoji", "", 40), ("name", "Игра", 200), ("role", "Роль", 160),
                     ("category", "Категория", 230), ("extra", "Доп. роли", 200)],
            fields=FIELDS, to_row=self.to_row, to_form=self.to_form, from_form=self.from_form,
            new=lambda: {"emoji": DEFAULT_EMOJI},
            removal=lambda g: ("Удалить игру?", f"«{g.get('name', '')}» пропадёт из анкеты. "
                                                "Роль и каналы игры на сервере останутся."),
            empty="Игр пока нет. Добавьте хотя бы одну, иначе новички не смогут заполнить анкету.",
            limit=(MAX_GAMES, f"В анкете помещается не больше {MAX_GAMES} игр. "
                              "Чтобы добавить новую, удалите одну из старых."),
            on_change=lambda items: self.show_admin_role())
        self.games.pack(fill="both", expand=True)

        W.section(self.body, "Администраторы отделов",
                  "Администратор отдела управляет ролями, каналами и порядком только в своей игре.")
        g = W.Group(self.body)
        self.prefix_row = g.row("Приставка роли", icon="tag")
        self.prefix = self.bind_entry(self.prefix_row.right, "s:roles.mini_admin_prefix", 24, strip=False)
        self.prefix.validate = lambda raw: bool(raw.strip())  # без приставки роль совпадёт с ролью игроков
        self.prefix.var.trace_add("write", lambda *_: self.show_admin_role())
        self.prefix.pack(side="left")
        g.row("Назначение администраторов", "В Discord: админ-панель, кнопка «mini Admin отделов».", "info")
        self.show_admin_role()

    def show_admin_role(self):
        """Под приставкой — как будет называться роль администратора первой игры."""
        prefix = self.prefix.get()
        if not prefix.strip():
            self.prefix_row.set_description("Укажите приставку, иначе роль администратора совпадёт с названием игры.")
            return
        game = next((g.get("name") for g in self.games.items() if g.get("name")), "Minecraft")
        self.prefix_row.set_description(f"Роль администратора отдела — приставка и название игры, "
                                        f"например «{prefix}{game}».")

    # ---------- таблица и форма ----------
    @staticmethod
    def to_row(g: dict) -> tuple:
        name = g.get("name", "")
        if g.get("category_id"):
            category = f"ID {g['category_id']}"
        else:
            category = g.get("category") or "Создаст бот"
        return g.get("emoji", ""), name, g.get("role") or name, category, ", ".join(g.get("extra_roles") or [])

    @staticmethod
    def to_form(g: dict) -> dict:
        return {"name": g.get("name", ""), "emoji": g.get("emoji", ""), "role": g.get("role", ""),
                "extra_roles": ", ".join(g.get("extra_roles") or []),
                "category_id": str(g["category_id"]) if g.get("category_id") else "",
                "category": g.get("category", "")}

    @staticmethod
    def from_form(data: dict, old: dict | None) -> dict:
        name = data["name"]
        return merge_item(old, {
            "name": name, "role": data["role"] or name, "emoji": data["emoji"],
            "extra_roles": split_names(data["extra_roles"]) or None,
            "category_id": int(data["category_id"]) if data["category_id"] else None,
            "category": data["category"] or None,
        })

    def validate(self, data: dict) -> str | None:
        name, category_id = data["name"], data["category_id"]
        if any(g.get("name", "").casefold() == name.casefold() for g in self.games.others()):
            return f"Игра «{name}» уже есть в списке."
        if len(name) > 80:
            return "Название игры не помещается на кнопку: максимум 80 символов."
        if not is_emoji(data["emoji"]):
            return "Значок — это один эмодзи, без букв и цифр."
        if category_id and not DISCORD_ID.fullmatch(category_id):
            return "ID категории состоит только из цифр. В Discord: правый клик по категории → «Копировать ID»."
        if category_id and data["category"]:
            return "Укажите что-то одно: ID существующей категории или название новой."
        return None
