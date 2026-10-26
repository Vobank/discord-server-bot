"""Разделы программы (порядок — как в меню слева). Модуль раздела: manager/pages/<module>.py с классом View."""
import importlib
import traceback

# (ключ, название, иконка, группа меню, модуль)
PAGES = [
    ("overview", "Обзор", "home", "", "overview"),
    ("connection", "Подключение", "link", "Настройка бота", "connection"),
    ("general", "Основное", "globe", "Настройка бота", "general"),
    ("features", "Функции", "puzzle", "Настройка бота", "features"),
    ("games", "Игры и отделы", "game", "Настройка бота", "games"),
    ("roles", "Роли", "group", "Настройка бота", "roles"),
    ("channels", "Каналы", "chat", "Настройка бота", "channels"),
    ("rules", "Правила", "document", "Настройка бота", "rules"),
    ("appearance", "Оформление", "brush", "Настройка бота", "appearance"),
    ("computers", "Компьютеры", "monitor", "Работа", "computers"),
    ("maintenance", "Обслуживание", "repair", "Работа", "maintenance"),
    ("logs", "Журнал", "log", "Работа", "logs"),
    ("about", "О программе", "info", "bottom", "about"),
]


def meta(key: str) -> tuple:
    return next(p for p in PAGES if p[0] == key)


def load(key: str):
    """Класс раздела. Если модуль ещё не готов или упал при импорте — заглушка с описанием ошибки."""
    from .base import Page
    _, title, icon, _, module = meta(key)
    try:
        mod = importlib.import_module(f"{__name__}.{module}")
        cls = mod.View
    except Exception:
        error = traceback.format_exc(limit=3)

        class Placeholder(Page):
            def build(self):
                from .. import widgets as W
                g = W.Group(self.body)
                W.label(g.block(), "Раздел не загрузился. Подробности ниже — их можно отправить разработчику.",
                        "body").pack(anchor="w")
                W.label(g.block(), error, "mono", "text2", justify="left").pack(anchor="w")
        cls = Placeholder
    cls.key, cls.title, cls.icon = key, title, icon
    return cls
