"""Обслуживание: построение сервера, обновления кода, резервные копии базы, автозапуск и файлы бота."""
import os
import re
import time
import tkinter as tk

from .. import state
from .. import widgets as W
from ..theme import px
from .base import Page

BACKUP_COLUMNS = [("date", "Дата", 200), ("kind", "Тип", 240), ("size", "Размер", 120)]
MANUAL_BACKUP = re.compile(r"^bot-\d{4}-\d{2}-\d{2}-\d{4}\.db$")  # «Сохранить копию сейчас» (supervisor.py)
_AUTOSTART = {"value": None}  # включён ли автозапуск: PowerShell медленный, поэтому проверяем один раз

PUBLISH_ON = ("Разошлёт код и настройки этого компьютера на остальные, они установят обновление сами "
              "в течение минуты.")
PUBLISH_OFF = "Доступно, когда включена синхронизация нескольких компьютеров."


def fmt_time(ts: float) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))


def fmt_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} КБ"
    return f"{size / 1024 / 1024:.1f} МБ".replace(".", ",")


def version_text() -> str:
    version = state.local_version()
    return fmt_time(version) if version else "Локальная сборка"


def error_text(error) -> str:
    return (str(error) or type(error).__name__).rstrip(".") + "."


class View(Page):
    description = "Построение сервера, обновления, резервные копии и запуск."

    def build(self):
        self.synced = state.sync_enabled(self.app.store.saved["e"])
        self._texts: dict = {}
        self._autostart_loading = False
        self._build_server()
        self._build_updates()
        self._build_backups()
        self._build_startup()
        self._build_files()

    # ---------- разметка ----------
    def _build_server(self):
        W.section(self.body, "Сервер Discord")
        g = W.Group(self.body)
        row = g.row("Что создаст бот", "Покажет, каких каналов и ролей не хватает, и ничего не изменит.", "search")
        W.button(row.right, "Проверить", self.check_server).pack(side="left")
        self.build_row = g.row("Построить сервер", self._build_desc(), "repair")
        W.button(self.build_row.right, "Построить", self.build_server, "accent").pack(side="left")
        row = g.row("Опубликовать правила", "Выложит правила в канал правил заново, например после правок "
                                            "в разделе «Правила».", "document")
        W.button(row.right, "Опубликовать", self.post_rules).pack(side="left")
        g.row("Перед построением", "Поднимите роль бота выше остальных в настройках сервера, раздел «Роли», "
                                   "иначе он не сможет выдавать роли участникам.", "lightbulb")

    def _build_desc(self) -> str:
        text = "Создаст недостающие роли, категории и каналы и выложит панели, ничего не удаляя."
        built = self.app.prefs.get("server_built")
        if built:
            text += f"\nПоследнее построение: {fmt_time(built)}"
        return text

    def _build_updates(self):
        W.section(self.body, "Обновления")
        g = W.Group(self.body)
        row = g.row("Версия кода", "Дата сборки, которая установлена на этом компьютере.", "code")
        self.version_label = W.label(row.right, version_text(), "body", "text2")
        self.version_label.pack(side="left")
        self.publish_row = g.row("Опубликовать обновление", PUBLISH_ON if self.synced else PUBLISH_OFF, "upload")
        self.b_publish = W.button(self.publish_row.right, "Опубликовать", self.publish)
        self.b_publish.pack(side="left")
        self.check_row = g.row("Проверить обновления", "Бот сразу проверит, нет ли новой версии, и установит её сам.",
                               "download")
        self.b_check = W.button(self.check_row.right, "Проверить", self.check_updates)
        self.b_check.pack(side="left")
        self._publishing = False
        self._update_publish()

    def _build_backups(self):
        W.section(self.body, "Резервные копии базы", "Бот сохраняет копию базы раз в день и хранит 14 последних.")
        g = W.Group(self.body)
        box = g.block()
        bar = tk.Frame(box, bg=W.bg_of(box))
        bar.pack(fill="x", pady=(0, px(10)))
        W.button(bar, "Сохранить копию сейчас", self.backup_now, icon="save").pack(side="left")
        W.button(bar, "Открыть папку", self.open_backups, icon="folder").pack(side="left", padx=(px(8), 0))
        W.button(bar, "Обновить", self.refresh_backups, icon="refresh").pack(side="right")
        self.backup_count = W.label(bar, "", "caption", "text3")
        self.backup_count.pack(side="right", padx=(0, px(12)))
        self.backup_table = W.Table(box, BACKUP_COLUMNS, height=6)
        self.backup_empty = W.label(box, "Пока нет резервных копий. Они появятся после первого запуска бота.",
                                    "body", "text2")
        self._backups_shown = None
        self.refresh_backups()

    def _build_startup(self):
        W.section(self.body, "Запуск")
        g = W.Group(self.body)
        row = g.row("Запускать вместе с Windows", "Бот запустится сам после входа в Windows, даже если эта "
                                                  "программа закрыта.", "power")
        self.autostart = W.Switch(row.right, bool(_AUTOSTART["value"]), self._autostart_toggled)
        self.autostart.pack(side="left")
        self.autostart.set_enabled(_AUTOSTART["value"] is not None)
        row = g.row("Ярлык на рабочем столе", "Создаст ярлык программы заново, если он пропал или устарел.", "link")
        self.b_shortcut = W.button(row.right, "Создать заново", self.make_shortcut)
        self.b_shortcut.pack(side="left")

    def _build_files(self):
        W.section(self.body, "Файлы")
        g = W.Group(self.body)
        row = g.row("Папка бота", "Код, настройки, база данных и журналы.", "folder")
        W.button(row.right, "Открыть", lambda: self._open(state.APP), icon="open").pack(side="left")
        row = g.row("Файл настроек", "settings.json: если правите его вручную, перезапустите программу, чтобы она "
                                     "увидела изменения.", "settings")
        W.button(row.right, "Открыть", self.open_settings, icon="open").pack(side="left")
        row = g.row("Ключи бота (.env)", "Ключ бота и служебные параметры синхронизации, этот файл никому "
                                         "не показывайте.", "key")
        W.button(row.right, "Открыть", self.open_env, icon="open").pack(side="left")

    # ---------- состояние ----------
    def on_show(self):
        self.synced = state.sync_enabled(self.app.store.saved["e"])
        self._update_publish()
        self.version_label.configure(text=version_text())
        self.refresh_backups()
        if _AUTOSTART["value"] is None and not self._autostart_loading:
            self._autostart_loading = True
            self.app.background(state.autostart_enabled, self._autostart_loaded)

    def on_status(self, status):
        if not self.synced:
            desc, on = "Обновления приходят с других компьютеров, когда включена синхронизация.", False
        elif status is None:
            desc, on = "Доступно, когда бот запущен на этом компьютере.", False
        elif status.get("solo"):
            desc, on = "Станет доступно после перезапуска бота в режиме нескольких компьютеров.", False
        else:
            desc, on = "Бот сразу проверит, нет ли новой версии, и установит её сам.", True
        self._set_desc(self.check_row, desc)
        self.b_check.state(["!disabled"] if on else ["disabled"])

    def _set_desc(self, row: W.Row, text: str):
        if self._texts.get(id(row)) != text:
            self._texts[id(row)] = text
            row.set_description(text)

    def _update_publish(self):
        self._set_desc(self.publish_row, PUBLISH_ON if self.synced else PUBLISH_OFF)
        on = self.synced and not self._publishing
        self.b_publish.state(["!disabled"] if on else ["disabled"])

    # ---------- сервер ----------
    def _ready(self, what: str) -> bool:
        """Сохранить черновик и убедиться, что есть ключ бота и сервер — служебные команды берут их из .env."""
        if not self.app.ensure_saved(what):
            return False
        env = self.app.store.saved["e"]
        if state.token_looks_valid(env.get("DISCORD_TOKEN", "")) and env.get("GUILD_ID"):
            return True
        if self.app.confirm("Сначала подключите бота", "Для этой команды нужны ключ бота и сервер. Укажите их "
                            "в разделе «Подключение».", ok="Открыть «Подключение»"):
            self.app.goto("connection")
        return False

    def check_server(self):
        if not self._ready("Проверка берёт ключ бота и сервер из сохранённых настроек. "
                           "Сохранить изменения и продолжить?"):
            return
        self.app.run_task("Что создаст бот", state.tool_args("build_server.py", "--check"),
                          "Бот подключится к серверу и покажет, чего не хватает. Сервер не изменится.",
                          success="Проверка завершена", failure="Не удалось проверить сервер")

    def build_server(self):
        if not self.app.confirm("Построить сервер?", "Бот создаст недостающие роли, категории и каналы и выложит "
                                "панели. Существующие каналы и роли он не удаляет и не переименовывает.",
                                ok="Построить"):
            return
        if not self._ready("Бот строит сервер по сохранённым настройкам. Сохранить изменения и продолжить?"):
            return
        self.app.run_task("Построение сервера", state.tool_args("build_server.py"),
                          "Бот подключится к серверу и создаст всё недостающее. Обычно это занимает до минуты.",
                          on_done=self._built, success="Сервер построен", failure="Не удалось построить сервер")

    def _built(self, ok: bool, _log: str):
        if not ok:
            return
        self.app.prefs["server_built"] = time.time()
        try:
            state.save_prefs(self.app.prefs)
        except OSError:
            pass
        if self.winfo_exists():
            self.build_row.set_description(self._build_desc())

    def post_rules(self):
        if not self._ready("Бот публикует сохранённые правила. Сохранить изменения и продолжить?"):
            return
        self.app.run_task("Публикация правил", state.tool_args("build_server.py", "--rules-only"),
                          "Бот выложит правила в канал правил заново.",
                          success="Правила опубликованы", failure="Не удалось опубликовать правила")

    # ---------- обновления ----------
    def publish(self):
        if not self.app.ensure_saved("Обновление собирается из сохранённых файлов. "
                                     "Сохранить изменения и продолжить?"):
            return
        note = self.app.prompt("Опубликовать обновление", "Что изменилось", ok="Опубликовать",
                               placeholder="Коротко, для истории обновлений")
        if note is None:
            return
        self._publishing = True
        self._update_publish()
        self.b_publish.configure(text="Публикация…")
        self.app.background(lambda: state.publish_update(note.strip()), self._published)

    def _published(self, _version, error):
        self._publishing = False
        if self.winfo_exists():
            self.b_publish.configure(text="Опубликовать")
            self._update_publish()
            self.version_label.configure(text=version_text())
        if error:
            self.app.notify("error", "Не удалось опубликовать обновление",
                            error_text(error) + " Проверьте подключение к интернету и попробуйте ещё раз.")
        else:
            self.app.notify("success", "Обновление опубликовано",
                            "Остальные компьютеры установят его в течение минуты.", timeout=8000)

    def check_updates(self):
        if self.app.status is None:
            return
        state.send_command("check_update")
        self.app.notify("info", "Проверка обновлений", "Если есть новая версия, бот установит её и перезапустится.",
                        timeout=8000)

    # ---------- резервные копии ----------
    def refresh_backups(self):
        items = state.list_backups()
        rows = [(fmt_time(b["mtime"]), "Сохранена вручную" if MANUAL_BACKUP.match(b["name"]) else "Ежедневная",
                 fmt_size(b["size"])) for b in items]
        self.backup_table.set_rows(rows)
        shown = bool(items)
        if shown != self._backups_shown:
            self._backups_shown = shown
            if shown:
                self.backup_empty.pack_forget()
                self.backup_table.pack(fill="x")
            else:
                self.backup_table.pack_forget()
                self.backup_empty.pack(anchor="w", pady=(px(4), px(2)))
        self.backup_count.configure(text=f"Всего: {len(items)}" if items else "")

    def backup_now(self):
        st = self.app.status
        if st is None:
            self.app.notify("warning", "Бот не запущен", "Копию сохраняет бот. Запустите его на этом компьютере "
                            "и повторите.", actions=[("Открыть обзор", lambda: self.app.goto("overview"))])
            return
        state.send_command("backup")
        if st.get("solo"):
            self.app.notify("success", "Копия базы сохраняется", "Она появится в списке через несколько секунд.",
                            timeout=6000)
            self.after(6000, lambda: self.winfo_exists() and self.refresh_backups())
        else:
            self.app.notify("success", "Копия базы сохраняется",
                            "Снимок базы появится в канале bot-sync в течение минуты.", timeout=8000)

    def open_backups(self):
        try:
            if not state.SANDBOX:
                os.makedirs(state.BACKUPS_DIR, exist_ok=True)
            state.open_path(state.BACKUPS_DIR)
        except OSError as e:
            self.app.notify("error", "Не удалось открыть папку", error_text(e))

    # ---------- запуск ----------
    def _autostart_loaded(self, value, error):
        self._autostart_loading = False
        if error is None:
            _AUTOSTART["value"] = bool(value)
        if not self.winfo_exists():
            return
        self.autostart.set(bool(value) if error is None else False)
        self.autostart.set_enabled(True)

    def _autostart_toggled(self, on: bool):
        self.autostart.set_enabled(False)
        name = self.app.bot_name()

        def work():
            state.set_autostart(on, name)
            return on if state.SANDBOX else state.autostart_enabled()  # проверяем, что Windows и правда записала
        self.app.background(work, lambda result, error: self._autostart_set(on, result, error))

    def _autostart_set(self, on: bool, result, error):
        ok = error is None and bool(result) == on
        if ok:
            _AUTOSTART["value"] = on
        if self.winfo_exists():
            self.autostart.set(on if ok else not on)
            self.autostart.set_enabled(True)
        if ok:
            self.app.notify("success", "Автозапуск включён" if on else "Автозапуск выключен",
                            "Бот будет запускаться вместе с Windows." if on else
                            "Бот больше не будет запускаться вместе с Windows.", timeout=5000)
        else:
            self.app.notify("error", "Не удалось изменить автозапуск",
                            (error_text(error) + " " if error else "") + "Попробуйте ещё раз.")

    def make_shortcut(self):
        name = self.app.bot_name()
        self.b_shortcut.state(["disabled"])
        self.app.background(lambda: state.ensure_shortcut(name), lambda _r, e: self._shortcut_done(name, e))

    def _shortcut_done(self, name: str, error):
        if self.winfo_exists():
            self.b_shortcut.state(["!disabled"])
        if error:
            self.app.notify("error", "Не удалось создать ярлык", error_text(error) + " Попробуйте ещё раз.")
        else:
            self.app.notify("success", "Ярлык создан", f"На рабочем столе появился ярлык «{name}».", timeout=6000)

    # ---------- файлы ----------
    def _open(self, path: str):
        try:
            state.open_path(path)
        except OSError as e:
            self.app.notify("error", "Не удалось открыть", error_text(e))

    def open_settings(self):
        self._open(state.SETTINGS_PATH if os.path.exists(state.SETTINGS_PATH) else state.EXAMPLE_PATH)

    def open_env(self):
        if not os.path.exists(state.ENV_PATH):
            self.app.notify("info", "Файла с ключами пока нет",
                            "Он появится, когда вы сохраните ключ бота в разделе «Подключение».", timeout=8000)
            return
        if self.app.confirm("Открыть файл с ключами?", "В файле лежит ключ бота: с ним можно полностью управлять "
                            "ботом. Не показывайте этот файл никому и не делайте снимков экрана, пока он открыт.",
                            ok="Открыть"):
            self._open(state.ENV_PATH)
