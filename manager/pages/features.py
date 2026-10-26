"""Функции бота: включение и параметры каждой функции.

Каждая функция — раскрывающийся блок: переключатель в заголовке (s:modules.<ключ>), внутри — её параметры.
Названия каналов и роли за уровни настраиваются в своих разделах («Каналы», «Роли»), сюда ведут ссылки.
"""
import os
import tkinter as tk
import unicodedata
from tkinter import filedialog

from .. import state
from .. import widgets as W
from ..theme import C, px
from .base import Page

# (ключ, иконка, название, описание) — порядок как в боте
MODULES = [
    ("welcome_card", "picture", "Карточка новичка",
     "Приветственная картинка с аватаром и номером участника в канале новичков."),
    ("music", "music", "Музыка",
     "Песни и плейлисты из YouTube, SoundCloud и ВКонтакте в голосовых каналах."),
    ("voice_rooms", "volume", "Личные голосовые комнаты",
     "Участник заходит в «Создать канал» и получает свою комнату; пустая комната удаляется."),
    ("levels", "trend", "Уровни и достижения",
     "Уровни за сообщения, роли-награды, достижения и рейтинги."),
    ("birthdays", "calendar", "Дни рождения",
     "Поздравления, роль именинника и праздники в календаре сервера."),
    ("cinema", "video", "Кинотеатр",
     "Афиша сеансов, напоминания, подборка фильмов и совместный просмотр."),
    ("applications", "contactinfo", "Заявки в состав",
     "Анкеты в модераторы и администраторы с рассмотрением и обзвоном."),
    ("family", "heart", "Семья",
     "Заявки в игровую семью, испытательный срок и каналы HR для RP-серверов."),
    ("protection", "shield", "Защита",
     "Антифлуд, мошеннические ссылки и рейды; администрацию и модераторов бот не проверяет."),
    ("community", "lightbulb", "Идеи и зал славы",
     "Канал идей с голосованием, лучшие сообщения по реакциям и итоги недели."),
    ("photo_only", "camera", "Каналы только для фото",
     "В каналах для скриншотов бот удаляет сообщения без картинок и видео."),
    ("server_stats", "people", "Счётчик участников",
     "Голосовой канал с числом участников, обновляется раз в 10 минут."),
    ("adult_channels", "lock", "Каналы 18+",
     "Закрытые каналы для девушек и парней старше 18 лет по дате рождения из анкеты."),
    ("news_forward", "megaphone", "Пересылка новостей",
     "Копирует посты из канала другого сервера в ваш канал."),
    ("hide_thread_notices", "comment", "Без уведомлений о ветках",
     "Бот удаляет служебное сообщение «начал(а) ветку» во всех каналах."),
]
TITLES = {key: title for key, _, title, _ in MODULES}

# Функции, которым при построении сервера нужны свои каналы или роли
NEEDS_BUILD = {"voice_rooms", "levels", "birthdays", "cinema", "applications", "family", "community",
               "server_stats", "adult_channels"}

WEEKDAYS = list(enumerate(["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]))
HOURS = [(h, f"{h:02d}:00") for h in range(24)]

FAMILY_FIELDS = [
    {"key": "name", "label": "Название роли", "required": True},
    {"key": "colour", "label": "Цвет", "kind": "color"},
    {"key": "ping", "label": "Упоминать при новой заявке", "kind": "bool"},
]
FORWARD_FIELDS = [
    {"key": "source", "label": "ID канала-источника", "required": True, "placeholder": "Например, 1123456789012345678",
     "hint": "В Discord включите режим разработчика (Настройки → Расширенные), затем щёлкните канал правой "
             "кнопкой мыши и выберите «Копировать ID канала»."},
    {"key": "target", "label": "Канал на вашем сервере", "required": True, "placeholder": "Название или ID канала",
     "hint": "Текстовый канал, куда бот копирует посты. ID надёжнее: он не меняется при переименовании."},
]


def plain(name) -> str:
    """Название канала без эмодзи и украшений: «🎬・кино-настройки» → «кино-настройки»."""
    text = "".join(ch for ch in str(name or "") if unicodedata.category(ch)[0] in "LNZ" or ch in "-_")
    return " ".join(text.split()).strip(" -_")


def join_names(names: list[str]) -> str:
    """«А» · «А» и «Б» · «А», «Б» и «В»."""
    quoted = [f"«{n}»" for n in names]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " и " + quoted[-1]


def parse_forwards(raw) -> list[list[str]]:
    """NEWS_FORWARDS: «ID_источника:канал,ID_источника:канал» → [[ID, канал], …] (как читает cogs/news.py)."""
    rows = []
    for part in str(raw or "").strip().strip("\"'").split(","):
        if ":" in part:
            source, target = part.split(":", 1)
            rows.append([source.strip(), target.strip()])
    return rows


def join_forwards(rows) -> str:
    return ",".join(f"{source}:{target}" for source, target in rows)


class _ForwardsDraft:
    """Посредник для ListEditor: в черновике NEWS_FORWARDS — строка, редактор работает со списком строк таблицы."""

    def __init__(self, page: Page):
        self.page, self.app = page, page.app

    def get(self, path: str, default=None):
        return parse_forwards(self.page.get(path, ""))

    def set(self, path: str, items):
        self.page.set(path, join_forwards(items))


class _Editor(W.ListEditor):
    """ListEditor, который помнит, добавляют элемент или меняют (для проверки повторов),
    и показывает подсказку в пустой таблице."""

    def __init__(self, *args, empty: str = "", rows=(3, 8), **kw):
        self.editing = None
        self._empty_text, self._empty, self._rows = empty, None, rows
        super().__init__(*args, **kw)

    def add(self):
        self.editing = None
        super().add()

    def edit(self):
        self.editing = self.table.selected()
        super().edit()

    def others(self) -> list:
        """Все элементы, кроме того, что сейчас меняют."""
        return [x for i, x in enumerate(self.items()) if i != self.editing]

    def refresh(self, select: int | None = None):
        super().refresh(select)
        count = len(self.items())
        self.tree.configure(height=max(self._rows[0], min(self._rows[1], count + 1)))  # таблица по содержимому
        if not self._empty_text:
            return
        if self._empty is None:
            # пустое поле таблицы sv_ttk рисует цветом фона страницы, а не карточки
            self._empty = tk.Label(self.tree.master, text=self._empty_text, font=W.font("body"), fg=C("text3"),
                                   bg=C("bg"), justify="center")
        if count:
            self._empty.place_forget()
        else:
            self._empty.configure(wraplength=max(px(200), self.tree.winfo_width() - px(48)))
            self._empty.place(in_=self.tree, relx=0.5, rely=0.56, anchor="center")


class View(Page):
    description = "Выключенные функции бот не загружает и не создаёт для них каналы."

    def build(self):
        self.expanders: dict[str, W.Expander] = {}
        self.initial = self._enabled()
        self.build_bar = None
        self._bulk = False
        self.local = state.sync_enabled(self.app.store.saved["e"])

        bar = tk.Frame(self.body, bg=C("bg"))
        bar.pack(fill="x", pady=(0, px(10)))
        self.count = W.label(bar, "", "body", "text2")
        self.count.pack(side="left")
        self.toggle_all = W.LinkButton(bar, "Развернуть все", self._toggle_all)
        self.toggle_all.pack(side="right")

        for key, icon, title, desc in MODULES:
            exp = W.Expander(self.body, title, desc, icon, on_toggle=lambda on, k=key: self._expanded(k, on))
            self.bind_switch(exp.right, f"s:modules.{key}",
                             on_toggle=lambda on, k=key: self._switched(k, on)).pack(side="left")
            self.expanders[key] = exp
            getattr(self, "_build_" + key)(exp)

        W.spacer(self.body, 10)
        self._note(self.body, "Анкета новичка, правила, админ-панель, мод-панель и панели отделов работают всегда.")
        self._update_count()

    def on_show(self):
        self.cinema_row.set_description(self._cinema_hint())

    # ---------- функции ----------
    def _build_welcome_card(self, exp):
        self._link_row(exp, "Оформление карточки", "Фон, цвета и надписи настраиваются в разделе «Оформление».",
                       "appearance")

    def _build_music(self, exp):
        row = exp.row("Ключ доступа ВКонтакте", "Нужен только для ссылок на плейлисты ВКонтакте.")
        self.bind_entry(row.right, "e:VK_TOKEN", 30, placeholder="Не задан", secret=True).pack(side="left")
        row = exp.row("Путь к FFmpeg", "Заполните, только если бот не находит FFmpeg сам.")
        self.ffmpeg = self.bind_entry(row.right, "e:FFMPEG_PATH", 30, placeholder="C:\\ffmpeg\\bin\\ffmpeg.exe")
        self.ffmpeg.pack(side="left")
        W.button(row.right, "Выбрать…", self._pick_ffmpeg).pack(side="left", padx=(px(8), 0))
        if self.local:
            self._note(exp.block(), "Ключ и путь хранятся только на этом компьютере. Чтобы они появились на "
                                    "остальных ПК, соберите для них новый установщик в разделе «Компьютеры».")

    def _build_voice_rooms(self, exp):
        self._link_row(exp, "Названия каналов",
                       "Канал «Создать канал» и панель управления комнатой задаются в разделе «Каналы».", "channels")

    def _build_levels(self, exp):
        row = exp.row("Сообщений на уровень", "Через каждые столько сообщений участник получает новый уровень.")
        self._spin(row.right, "s:levels.step", 10, 100000, 10, 8)
        row = exp.row("Пауза между сообщениями",
                      "Сообщения чаще этого не засчитываются, поэтому флуд не ускоряет рост уровня.")
        self._spin(row.right, "s:levels.cooldown", 0, 600, unit="с")
        self._link_row(exp, "Роли за сообщения и достижения",
                       "Награды за уровни и достижения настраиваются в разделе «Роли».", "roles")

    def _build_birthdays(self, exp):
        row = exp.row("Время поздравлений",
                      "Час, когда бот поздравляет именинников и пишет о праздниках, по часовому поясу сервера.")
        self.bind_combo(row.right, "s:birthday_hour", HOURS, 7).pack(side="left")
        row = exp.row("Роль именинника", "Выдаётся в день рождения и снимается на следующий день.")
        self.bind_entry(row.right, "s:roles.birthday", 28).pack(side="left")

    def _build_cinema(self, exp):
        row = exp.row("Роль для уведомлений",
                      "Выдаётся кнопкой «Уведомлять меня» в афише; бот упоминает её перед каждым сеансом.")
        self.bind_entry(row.right, "s:roles.cinema", 28).pack(side="left")
        self.cinema_row = exp.row("Сеансы и тексты анонсов", self._cinema_hint())

    def _cinema_hint(self) -> str:
        name = plain(self.get("s:cinema.setup", ""))
        where = f"в канале «{name}»" if name else "в канале настроек кинотеатра"
        return f"Настраиваются в Discord кнопками {where}."

    def _build_applications(self, exp):
        row = exp.row("Повторная заявка", "Через сколько дней после отказа можно подать новую заявку.")
        self._spin(row.right, "s:applications.cooldown_days", 0, 365, unit="дн.")
        row = exp.row("Срок рассмотрения", "Сколько дней на ответ бот обещает заявителю.")
        self._spin(row.right, "s:applications.review_days", 1, 60, unit="дн.")
        row = exp.row("Дополнительные проверяющие",
                      "Роли через запятую, которые рассматривают заявки вместе с главным админом и главным "
                      "модератором.")
        self.bind_entry(row.right, "s:roles.extra_reviewers", 28, kind="list", placeholder="Не заданы").pack(side="left")

    def _build_family(self, exp):
        row = exp.row("Название семьи", "Показывается в заявках и сообщениях бота.")
        self.bind_entry(row.right, "s:family.name", 28).pack(side="left")
        row = exp.row("Игра", "Упоминается в приглашении подать заявку.")
        self.bind_entry(row.right, "s:family.game", 28, placeholder="Например, GTA 5 RP").pack(side="left")
        row = exp.row("Испытательный срок",
                      "Бот называет этот срок принятому участнику и напоминает о нём руководству.")
        self._spin(row.right, "s:family.probation_days", 1, 365, unit="дн.")
        row = exp.row("Роль на испытательном сроке", "Выдаётся автоматически после одобрения заявки.")
        self.bind_entry(row.right, "s:family.probation_role", 28).pack(side="left")
        row = exp.row("Роль участника семьи",
                      "Выдаётся вручную после испытательного срока; с ней повторная заявка недоступна.")
        self.bind_entry(row.right, "s:family.member_role", 28).pack(side="left")
        row = exp.row("Расположение категории",
                      "ID категории, после которой бот создаст категорию семьи; без него — в конце списка.")
        self.bind_entry(row.right, "s:family.after_category_id", 28, kind="id",
                        placeholder="Необязательно").pack(side="left")

        block = self._block_header(exp, "Роли руководства",
                                   "Участники с этими ролями рассматривают заявки; отмеченные упоминаются при "
                                   "каждой новой заявке.")
        self.family_roles = _Editor(
            block, self, "s:family.roles", [("name", "Роль", 320), ("colour", "Цвет", 120), ("ping", "Упоминать", 120)],
            FAMILY_FIELDS, to_row=self._family_row,
            to_form=lambda x: {"name": x[0], "colour": x[1], "ping": bool(x[2])},
            from_form=lambda d, old: [d["name"], d["colour"], bool(d["ping"])],
            new=lambda: {"name": "", "colour": "#5865F2", "ping": False}, noun="роль", height=5,
            validate=self._check_family_role,
            empty="Ролей пока нет. Без них заявки в семью рассматривают только администраторы сервера.")
        self.family_roles.pack(fill="x")

    @staticmethod
    def _family_row(item):
        name, colour, ping = (list(item) + ["", "", False])[:3]
        return name, str(colour).upper(), "Да" if ping else "Нет"

    def _check_family_role(self, data):
        if len(data["name"]) > 100:
            return "Название роли должно быть не длиннее 100 символов."
        if any(str(x[0]) == data["name"] for x in self.family_roles.others()):
            return "Такая роль уже есть в списке."
        return None

    def _build_protection(self, exp):
        row = exp.row("Флуд", "Если участник отправит столько сообщений за это время, бот выдаст тайм-аут.")
        self._spin(row.right, "s:protection.flood_messages", 2, 50, width=4, unit="за")
        self._spin(row.right, "s:protection.flood_seconds", 1, 120, width=4, unit="с", pad=px(8))
        row = exp.row("Повторы",
                      "Если участник отправит столько одинаковых сообщений за это время, бот выдаст тайм-аут.")
        self._spin(row.right, "s:protection.repeat_messages", 2, 20, width=4, unit="за")
        self._spin(row.right, "s:protection.repeat_seconds", 5, 600, width=4, unit="с", pad=px(8))
        row = exp.row("Упоминания", "Сколько участников можно упомянуть в одном сообщении.")
        self._spin(row.right, "s:protection.max_mentions", 1, 50, width=4)
        row = exp.row("Тайм-аут за нарушение", "Наказание за флуд, повторы и массовые упоминания.")
        self._spin(row.right, "s:protection.timeout_minutes", 1, 40320, width=6, unit="мин")
        row = exp.row("Тайм-аут за мошенничество",
                      "Наказание за поддельные ссылки Discord и Steam и фальшивые раздачи Nitro.")
        self._spin(row.right, "s:protection.scam_timeout_minutes", 1, 40320, width=6, unit="мин")
        row = exp.row("Рейд", "Если столько участников зайдёт за это время, бот поднимет тревогу в канале логов.")
        self._spin(row.right, "s:protection.raid_joins", 2, 100, width=4, unit="за")
        self._spin(row.right, "s:protection.raid_seconds", 5, 600, width=4, unit="с", pad=px(8))
        row = exp.row("Новые аккаунты", "Бот отметит в канале логов участника, чей аккаунт моложе этого срока.")
        self._spin(row.right, "s:protection.new_account_days", 0, 365, width=4, unit="дн.")

    def _build_community(self, exp):
        row = exp.row("Эмодзи зала славы", "Реакция, которой участники отмечают лучшие сообщения.")
        self.bind_entry(row.right, "s:community.star_emoji", 6).pack(side="left")
        row = exp.row("Порог зала славы", "Сколько таких реакций нужно, чтобы сообщение попало в зал славы.")
        self._spin(row.right, "s:community.star_count", 1, 1000, unit="реакций")
        row = exp.row("Итоги недели", "Когда бот публикует сводку недели в общем чате.")
        self.bind_combo(row.right, "s:community.digest_weekday", WEEKDAYS, 13).pack(side="left")
        W.label(row.right, "в", "body", "text2").pack(side="left", padx=px(8))
        self.bind_combo(row.right, "s:community.digest_hour", HOURS, 7).pack(side="left")

    def _build_photo_only(self, exp):
        row = exp.row("Каналы для фото",
                      "Канал считается каналом для фото, если в его названии есть одно из этих слов.")
        self.bind_entry(row.right, "s:photo_only.keywords", 28, kind="list",
                        placeholder="Слова через запятую").pack(side="left")
        row = exp.row("Задержка удаления", "Через сколько бот удалит сообщение без картинки или видео.")
        self._spin(row.right, "s:photo_only.delay", 10, 86400, 10, 7, unit="с")

    def _build_server_stats(self, exp):
        self._link_row(exp, "Название счётчика", "Текст перед числом участников задаётся в разделе «Каналы».",
                       "channels")

    def _build_adult_channels(self, exp):
        row = exp.row("Роль для девушек 18+", "Открывает канал для девушек; бот выдаёт и снимает её сам.")
        self.bind_entry(row.right, "s:adult.girls_role", 28).pack(side="left")
        row = exp.row("Роль для парней 18+", "Открывает канал для парней; бот выдаёт и снимает её сам.")
        self.bind_entry(row.right, "s:adult.boys_role", 28).pack(side="left")
        self._link_row(exp, "Названия каналов", "Каналы для девушек и парней переименовываются в разделе «Каналы».",
                       "channels")

    def _build_news_forward(self, exp):
        block = self._block_header(exp, "Источники",
                                   "Бот должен состоять на сервере-источнике и видеть канал. Файлы больше 10 МБ "
                                   "пересылаются ссылкой.")
        self.forwards = _Editor(
            block, _ForwardsDraft(self), "e:NEWS_FORWARDS",
            [("source", "Канал-источник (ID)", 240), ("target", "Канал на вашем сервере", 320)],
            FORWARD_FIELDS, to_row=lambda x: (x[0], f"ID {x[1]}" if x[1].isdigit() else x[1]),
            to_form=lambda x: {"source": x[0], "target": x[1]},
            from_form=lambda d, old: [d["source"].replace(" ", ""), d["target"].lstrip("#").strip()],
            new=lambda: {"source": "", "target": ""}, noun="источник", height=4, reorder=False,
            validate=self._check_forward,
            empty="Источников пока нет. Добавьте канал, из которого бот будет копировать посты.")
        self.forwards.pack(fill="x")
        if self.local:
            self._note(block, "Список хранится только на этом компьютере. Чтобы он появился на остальных ПК, "
                              "соберите для них новый установщик в разделе «Компьютеры».", pady=(px(12), 0))

    def _check_forward(self, data):
        source = data["source"].replace(" ", "")
        if not source.isdigit() or not 15 <= len(source) <= 21:
            return "ID канала-источника состоит только из цифр, обычно их 18–19."
        target = data["target"].lstrip("#").strip()
        if not target:
            return "Укажите канал на вашем сервере."
        if "," in target:
            return "В названии канала не может быть запятой."
        if any(s == source for s, _ in self.forwards.others()):
            return "Этот канал-источник уже есть в списке."
        return None

    def _build_hide_thread_notices(self, exp):
        exp.row("Где найти ветку", "Ветка остаётся под исходным сообщением и в списке веток канала.")

    # ---------- общие элементы ----------
    def _spin(self, parent, path, frm, to, step=1, width=6, unit="", pad=0):
        spin = self.bind_spin(parent, path, frm, to, step, width)
        spin.pack(side="left", padx=(pad, 0))
        if unit:
            W.label(parent, unit, "body", "text2").pack(side="left", padx=(px(8), 0))
        return spin

    def _link_row(self, exp, title, desc, page):
        row = exp.row(title, desc)
        W.button(row.right, "Открыть", lambda: self.app.goto(page)).pack(side="left")

    def _block_header(self, exp, title, desc) -> tk.Frame:
        block = exp.block()
        W.label(block, title, "body").pack(anchor="w")
        hint = W.label(block, desc, "caption", "text2")
        hint.pack(anchor="w", fill="x", pady=(px(2), px(10)))
        W.autowrap(hint)
        return block

    def _note(self, parent, text, pady=(0, 0)):
        box = tk.Frame(parent, bg=W.bg_of(parent))
        box.pack(fill="x", pady=pady)
        W.icon_label(box, "info", 13, "text2").pack(side="left", anchor="n", pady=(px(1), 0))
        lb = W.label(box, text, "caption", "text2")
        lb.pack(side="left", fill="x", expand=True, padx=(px(8), 0))
        W.autowrap(lb, px(26))

    def _pick_ffmpeg(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Где находится FFmpeg",
                                          filetypes=[("FFmpeg", "ffmpeg.exe"), ("Программы", "*.exe"),
                                                     ("Все файлы", "*.*")])
        if path:
            path = os.path.normpath(path)
            self.ffmpeg.set(path)
            self.set("e:FFMPEG_PATH", path)

    # ---------- раскрытие блоков ----------
    def _toggle_all(self):
        target = not any(e.expanded for e in self.expanders.values())
        self._bulk = True
        try:
            for e in self.expanders.values():
                if e.expanded != target:
                    e.toggle(target)
        finally:
            self._bulk = False
        self._sync_toggle_all()

    def _expanded(self, key, on):
        if self._bulk:
            return
        self._sync_toggle_all()
        if on:
            self.after(30, lambda: self._reveal(self.expanders[key]))

    def _sync_toggle_all(self):
        any_open = any(e.expanded for e in self.expanders.values())
        self.toggle_all.configure(text="Свернуть все" if any_open else "Развернуть все")

    def _reveal(self, exp):
        """Прокрутить так, чтобы раскрытый блок был виден целиком (или хотя бы его начало)."""
        if self.scroller is None or not exp.winfo_exists() or not exp.expanded:
            return
        self.update_idletasks()
        canvas = self.scroller.canvas
        canvas.configure(scrollregion=canvas.bbox("all"))
        total, view = self.body.winfo_height(), canvas.winfo_height()
        if total <= view:
            return
        top = canvas.canvasy(0)
        y1 = exp.winfo_rooty() - self.body.winfo_rooty()
        y2 = y1 + exp.winfo_height()
        if y2 <= top + view:
            return
        new_top = min(y1 - px(8), y2 - view + px(16))
        canvas.yview_moveto(max(0, new_top) / total)

    # ---------- включение функций ----------
    def _enabled(self) -> dict:
        return {key: bool(self.get(f"s:modules.{key}")) for key, *_ in MODULES}

    def _update_count(self):
        on = sum(self._enabled().values())
        self.count.configure(text=f"Включено {on} из {len(MODULES)}")

    def _switched(self, key, on):
        self._update_count()
        self._update_build_hint()

    def _update_build_hint(self):
        """Включили функцию, которой нужны каналы или роли, — подсказать построить сервер."""
        now = self._enabled()
        fresh = [TITLES[k] for k, *_ in MODULES if k in NEEDS_BUILD and now[k] and not self.initial.get(k)]
        if fresh:
            what = "функции" if len(fresh) == 1 else "функций"
            self.build_bar = self.app.notify(
                "info", "Нужно построить сервер",
                f"Бот создаст недостающие каналы и роли для {what} {join_names(fresh)} при построении сервера.",
                actions=[("Построить сервер", self._build_server)])
        elif self.build_bar is not None:
            bar, self.build_bar = self.build_bar, None
            if bar.winfo_exists():
                bar.close()

    def _build_server(self):
        if not self.app.ensure_saved("Перед построением сервера изменения нужно сохранить."):
            self.after(50, self._update_build_hint)
            return
        if not self.app.confirm("Построить сервер?",
                                "Бот создаст недостающие роли, категории и каналы и выложит панели. "
                                "Существующие каналы не меняются и не удаляются.", ok="Построить"):
            self.after(50, self._update_build_hint)
            return
        self.app.run_task("Построение сервера", state.tool_args("build_server.py"),
                          "Бот подключается к Discord и создаёт недостающее. Обычно это занимает до минуты.",
                          on_done=self._built, success="Сервер построен", failure="Построить сервер не удалось")

    def _built(self, ok, _log):
        if not ok:
            return
        self.initial = self._enabled()
        if self.app.status or state.sync_enabled(self.app.store.saved["e"]):
            self.app.notify("success", "Сервер построен", "Перезапустите бота, чтобы новые функции заработали.",
                            actions=[("Перезапустить", self.app.apply_changes)], timeout=20000)
