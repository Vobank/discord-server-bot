"""Каналы: названия категорий и каналов, под которыми бот ищет их на сервере и создаёт недостающие.

У четырёх объектов (категория «Общение», правила, общий чат, управление комнатой) есть ещё ID: по нему бот находит
канал, даже если его переименовали в Discord.
"""
import tkinter as tk

from .. import state
from .. import widgets as W
from ..theme import px
from .base import Page

FIELD_W = 24     # одна ширина у всех полей (колонка ровная); в узком окне строки так не переносятся
FIELD_W_WIDE = 32  # в окне пошире — длинные названия видны целиком
WIDE_FROM = 700    # ширина страницы (при 100 %), начиная с которой поля широкие
NAME_MAX = 100   # ограничение Discord на название канала
ICONS = {"category": "folder", "text": "chat", "voice": "volume"}
NOUNS = {"category": "категорию", "text": "канал", "voice": "канал"}

# Названия функций — как в разделе «Функции».
FUNCTIONS = {
    "levels": "Уровни и достижения", "birthdays": "Дни рождения", "community": "Идеи и зал славы",
    "voice_rooms": "Личные комнаты", "server_stats": "Счётчик участников", "cinema": "Кинотеатр",
    "applications": "Заявки в состав", "family": "Семья", "adult_channels": "Каналы 18+",
}


def item(path, kind, title, description, function=None, ident=False, strip=True):
    """Строка раздела. ident — у объекта есть ID: тогда path — общий префикс (…name и …id)."""
    return {"path": path, "kind": kind, "title": title, "desc": description, "function": function,
            "ident": ident, "strip": strip}


# (раздел, пояснение, функция всего раздела, строки)
SECTIONS = [
    ("Категории", "Бот создаёт категорию, только когда в неё нужно положить новый канал. Созданные каналы "
                  "можно переносить между категориями.", None, [
        item("s:channels.main", "category", "Общение", "Общий чат, мемы и каналы 18+.", ident=True),
        item("s:channels.info", "category", "Информация", "Правила, анкета новичков, приветствия и новости."),
        item("s:channels.activity", "category", "Активность", "Календарь, уровни, достижения, идеи и зал славы."),
        item("s:channels.voice", "category", "Голосовые", "Счётчик участников и личные комнаты."),
    ]),
    ("Информация", "Участники в этих каналах только читают.", None, [
        item("s:channels.rules", "text", "Правила", "Бот публикует здесь текст из раздела «Правила».", ident=True),
        item("s:channels.welcome", "text", "Анкета новичков",
             "Пока новичок не заполнит анкету, ему видны только этот канал, правила и приветствия."),
        item("s:channels.joins", "text", "Приветствия", "Бот встречает каждого нового участника карточкой "
                                                        "с аватаркой."),
        item("s:channels.news", "text", "Новости", "Для ваших объявлений, бот этот канал только создаёт."),
    ]),
    ("Общение", "", None, [
        item("s:channels.general", "text", "Общий чат", "Сюда бот пишет поздравления с днём рождения и итоги "
                                                        "недели.", ident=True),
        item("s:channels.memes", "text", "Мемы", "Для картинок и шуток, бот этот канал только создаёт."),
    ]),
    ("Активность", "Бот пишет в эти каналы сам.", None, [
        item("s:channels.birthdays", "text", "Календарь", "Поздравления с днём рождения и праздниками.",
             "birthdays"),
        item("s:channels.levels", "text", "Уровни", "Сообщения о новых уровнях участников.", "levels"),
        item("s:channels.achievements", "text", "Достижения", "Сообщения о полученных достижениях.", "levels"),
        item("s:community.ideas", "text", "Идеи", "Предложения участников с голосованием «за» и «против».",
             "community"),
        item("s:community.starboard", "text", "Зал славы", "Сообщения, которые набрали нужное число звёзд.",
             "community"),
    ]),
    ("Голосовые", "", None, [
        item("s:channels.rooms_panel", "text", "Управление комнатой",
             "Кнопки, которыми владелец настраивает свою комнату.", "voice_rooms", ident=True),
        item("s:channels.voice_creator", "voice", "Создать комнату",
             "Участник заходит в этот канал, и бот создаёт ему личную комнату.", "voice_rooms"),
        item("s:channels.stats_prefix", "voice", "Счётчик участников", "", "server_stats", strip=False),
    ]),
    ("Администрация", "Служебные каналы для администрации и модераторов.", None, [
        item("s:admin.category", "category", "Категория",
             "Скрыта от участников; модераторы видят в ней только мод-панель и мод-чат."),
        item("s:admin.panel", "text", "Админ-панель", "Кнопки управления ботом и сервером."),
        item("s:admin.mini_panel", "text", "Mini-панель", "Кнопки для mini Admin: роли своего отдела."),
        item("s:admin.chat", "text", "Админ-чат", "Общение администрации и mini Admin отделов."),
        item("s:admin.log", "text", "Журнал действий",
             "Бот записывает сюда действия администрации, модераторов и защиты."),
        item("s:admin.mod_panel", "text", "Мод-панель", "Предупреждения, тайм-ауты и история нарушений."),
        item("s:admin.mod_chat", "text", "Мод-чат", "Единственный канал админки, где пишут модераторы."),
        item("s:admin.ratings", "text", "Рейтинги", "Таблицы уровней и достижений, бот обновляет их сам.",
             "levels"),
    ]),
    ("Кинотеатр", "Сеансы, анонсы и подборка фильмов.", "cinema", [
        item("s:cinema.category", "category", "Категория",
             "Афиша, подборка и кинозал; обсуждение и настройки находятся в админке."),
        item("s:cinema.afisha", "text", "Афиша", "Анонсы сеансов с карточкой фильма и напоминания."),
        item("s:cinema.hall", "voice", "Кинозал", "Голосовой канал для совместного просмотра."),
        item("s:cinema.wishlist", "text", "Подборка", "Участники предлагают фильмы, потом голосуют."),
        item("s:cinema.talk", "text", "Обсуждение", "Канал в админке, где выбирают, что смотреть."),
        item("s:cinema.setup", "text", "Настройки", "Кнопки для сеансов, канал находится в админке."),
    ]),
    ("Заявки в состав", "Анкеты в модераторы и администраторы, рассмотрение и обзвон.", "applications", [
        item("s:applications.category", "category", "Категория",
             "Открыта для всех: подать заявку может любой участник."),
        item("s:applications.apply", "text", "Подать заявку", "Кнопка с анкетой кандидата."),
        item("s:applications.review", "text", "Рассмотрение", "Анкеты кандидатов, их видят только проверяющие."),
        item("s:applications.voice", "voice", "Обзвон", "Голосовой канал для собеседования с кандидатом."),
    ]),
    ("Семья", "Заявки в семью, испытательный срок и HR для ролевых игр.", "family", [
        item("s:family.category", "category", "Категория", "Видна только ролям семьи."),
        item("s:family.apply", "text", "Заявка в семью", "Кнопка заявки, этот канал видят все участники сервера."),
        item("s:family.requests", "text", "Заявки", "Каждая заявка обсуждается в отдельной ветке с голосованием."),
        item("s:family.probation", "text", "Испытательный срок", "Канал для новичков семьи на время испытания."),
        item("s:family.hr", "text", "HR-чат", "Рабочий чат HR семьи."),
        item("s:family.hr_reports", "text", "Отчёты HR", "Для отчётов HR, бот этот канал только создаёт."),
    ]),
    ("Каналы 18+", "Бот создаёт их в категории «Общение» и пускает по анкете: пол и возраст.", "adult_channels", [
        item("s:adult.girls_channel", "text", "Для девушек", "Доступ получают участницы от 18 лет."),
        item("s:adult.boys_channel", "text", "Для парней", "Доступ получают участники от 18 лет."),
    ]),
]


def quoted_list(names: list[str]) -> str:
    """«А», «Б» и «В»."""
    names = [f"«{n}»" for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " и " + names[-1]


class View(Page):
    description = "Под этими названиями бот ищет каналы на сервере и создаёт недостающие."

    def build(self):
        self.example = state.load_example()
        self.entries, self.wide = [], None
        self.body.bind("<Configure>", self.fit_fields, add="+")
        W.InfoBar(self.body, "info", "Как бот находит каналы",
                  "По названию: если вы переименуете канал в Discord, поменяйте название и здесь. Если указан ID, "
                  "бот найдёт канал по нему, и название можно менять свободно.", closable=False).pack(fill="x")
        self.sections = []
        for title, description, function, rows in SECTIONS:
            box = W.section(self.body, title, description or " ")
            labels = [w for w in box.winfo_children() if isinstance(w, tk.Label)]
            g = W.Group(self.body)
            built = []
            for spec in rows:
                row = g.row(spec["title"], spec["desc"], ICONS[spec["kind"]])
                self.fields(row, spec)
                pill = self.tag(row, spec["function"]) if spec["function"] and not function else None
                built.append((spec, row, pill))
            self.sections.append({"base": description, "function": function, "desc": labels[1], "rows": built})
        self.refresh_functions()

    # --- поля строки ---
    def fit_fields(self, event):
        """Две ширины полей: узкая для маленького окна и широкая, когда места хватает."""
        wide = event.width >= px(WIDE_FROM)
        if wide != self.wide:
            self.wide = wide
            for entry in self.entries:
                entry.entry.configure(width=FIELD_W_WIDE if wide else FIELD_W)

    def default(self, path: str):
        node = self.example
        for key in path.partition(":")[2].split("."):
            node = node.get(key) if isinstance(node, dict) else None
        return node

    def fields(self, row, spec):
        path = spec["path"]
        if not spec["ident"]:
            entry = self.name_entry(row.right, path, spec["strip"],
                                    on_change=self.counter_example(row) if path.endswith("stats_prefix") else None)
            entry.pack(side="top", anchor="e")
            return
        current = self.get(path)
        legacy = current if isinstance(current, str) else None  # старый формат: просто название без ID
        name = self.name_entry(row.right, path + ".name", True, legacy=legacy, parent_path=path)
        name.pack(side="top", anchor="e")
        ident = self.id_entry(row.right, path, NOUNS[spec["kind"]])
        ident.pack(side="top", anchor="e", pady=(px(6), 0))

    def ensure_object(self, path: str):
        """Объект с ID хранится как {"name": …, "id": …}. Если в настройках просто строка — переводим."""
        current = self.get(path)
        if not isinstance(current, dict):
            name = current if isinstance(current, str) and current.strip() else self.default(path + ".name")
            self.set(path, {"name": name, "id": None})

    def name_entry(self, parent, path: str, strip: bool, legacy: str | None = None, parent_path: str | None = None,
                   on_change=None) -> W.Entry:
        """Название: пустое поле — название по умолчанию (оно же видно подсказкой); длиннее 100 — ошибка."""
        fallback = self.default(path) or ""
        value = self.get(path)
        text = legacy if legacy is not None else ("" if value is None else str(value))

        def clean(raw: str) -> str:
            value = raw.strip() if strip else raw
            return value if value.strip() else fallback

        def changed(raw: str):
            if parent_path:
                self.ensure_object(parent_path)
            value = clean(raw)
            self.set(path, value)
            if on_change:
                on_change(value)

        entry = W.Entry(parent, text, FIELD_W, fallback, command=changed,
                        validate=lambda raw: len(raw.strip() if strip else raw) <= NAME_MAX)
        self.entries.append(entry)
        if on_change:
            on_change(clean(text))
        return entry

    def id_entry(self, parent, path: str, noun: str) -> W.Entry:
        """ID Discord: 15–21 цифра или пусто. Неверное значение подсвечивается и в черновик не попадает."""
        value = self.get(path + ".id") if isinstance(self.get(path), dict) else None

        def convert(raw: str):
            raw = raw.strip()
            if not raw:
                return None
            if not raw.isdigit() or not 15 <= len(raw) <= 21:
                raise ValueError
            return int(raw)

        def valid(raw: str) -> bool:
            try:
                convert(raw)
                return True
            except ValueError:
                return False

        def changed(raw: str):
            self.ensure_object(path)
            self.set(path + ".id", convert(raw))

        entry = W.Entry(parent, "" if value is None else str(value), FIELD_W, "ID, необязательно", command=changed,
                        validate=valid)
        self.entries.append(entry)
        W.Tooltip(entry.entry, f"Нажмите в Discord на {noun} правой кнопкой и скопируйте ID. Если пункта нет, "
                               "включите режим разработчика: Настройки → Расширенные.")
        return entry

    def counter_example(self, row):
        def show(prefix: str):
            row.set_description(f"Начало названия, бот допишет число: «{prefix}128».")
        return show

    # --- выключенные функции ---
    def tag(self, row, function: str) -> W.Pill:
        """Метка «Не создаётся» рядом с названием строки; видна, только когда функция выключена."""
        line = tk.Frame(row.text, bg=W.bg_of(row.text))
        line.pack(anchor="w", fill="x", before=row.title)
        row.title.pack(in_=line, side="left")
        row.title.lift(line)  # line создан позже и иначе перекрывает название
        pill = W.Pill(line, "Не создаётся", "neutral")
        W.Tooltip(pill, f"Включите функцию «{FUNCTIONS.get(function, function)}» в разделе «Функции».")
        return pill

    def refresh_functions(self):
        for sec in self.sections:
            base, notes = sec["base"], []
            if sec["function"]:
                if not self.get(f"s:modules.{sec['function']}"):
                    notes.append("Функция выключена — каналы не создаются.")
            else:
                off, marked = [], 0
                for spec, _, pill in sec["rows"]:
                    if pill is None:
                        continue
                    if not self.get(f"s:modules.{spec['function']}"):
                        marked += 1
                        name = FUNCTIONS.get(spec["function"], spec["function"])
                        if name not in off:
                            off.append(name)
                        if not pill.winfo_manager():
                            pill.pack(side="left", padx=(px(8), 0))
                    elif pill.winfo_manager():
                        pill.pack_forget()
                if off:
                    verb = "выключена" if len(off) == 1 else "выключены"
                    what = "отмеченный канал не создаётся" if marked == 1 else "отмеченные каналы не создаются"
                    notes.append(f"{'Функция' if len(off) == 1 else 'Функции'} {quoted_list(off)} {verb} — {what}.")
            text = " ".join(x for x in [base, *notes] if x)
            label = sec["desc"]
            label.configure(text=text or " ")
            if text and not label.winfo_manager():
                label.pack(anchor="w", fill="x", pady=(px(2), 0))
            elif not text and label.winfo_manager():
                label.pack_forget()

    def on_show(self):
        self.refresh_functions()
