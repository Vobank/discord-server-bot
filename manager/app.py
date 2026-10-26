"""Панель управления ботом — одно окно для всего: состояние бота, настройки, компьютеры, обслуживание.

Запуск: manager.pyw (ярлык на рабочем столе). Параметры: --page <раздел>, --theme light|dark|system.
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback

from . import pages as registry
from . import state, theme
from . import widgets as W
from .theme import C, font, glyph, icon_font, px


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2,
           x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class NavItem(tk.Canvas):
    def __init__(self, parent, key, title, icon, command):
        super().__init__(parent, height=px(38), bg=C("nav"), highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=True)
        self.key, self.title, self.icon, self.command = key, title, icon, command
        self.selected = self.hover = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<Button-1>", lambda e: command(key))
        self.bind("<Return>", lambda e: command(key))
        self.bind("<space>", lambda e: command(key))

    def _hover(self, on):
        self.hover = on
        self.draw()

    def set_selected(self, on):
        self.selected = on
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if self.selected or self.hover:
            round_rect(self, px(6), px(2), w - px(6), h - px(2), px(6),
                       fill=C("nav_sel") if self.selected else C("nav_hover"), outline="")
        if self.selected:
            round_rect(self, px(6), h / 2 - px(8), px(9), h / 2 + px(8), px(2), fill=C("accent"), outline="")
        self.create_text(px(24), h / 2, text=glyph(self.icon), font=icon_font(16), fill=C("text"), anchor="w")
        self.create_text(px(56), h / 2, text=self.title, font=font("body"), fill=C("text"), anchor="w")


class App(tk.Tk):
    def __init__(self, start_page: str | None = None, theme_mode: str | None = None):
        theme.dpi_aware()
        theme.set_app_id()
        theme.load_fonts()
        super().__init__()
        self.withdraw()
        theme.STATE["k"] = self.winfo_fpixels("1i") / 96
        self.prefs = state.load_prefs()
        self.store = state.Store()
        self.status = state.read_status()
        self.pages: dict = {}
        self.current = None
        self.bars: list = []
        self._bg_queue: queue.Queue = queue.Queue()
        self.mode = theme.apply(self, theme_mode or self.prefs.get("theme", "system"))
        self._set_icon()
        self._geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<Control-s>", lambda e: self.save())
        self.bind_all("<Control-S>", lambda e: self.save())
        self.report_callback_exception = self._on_error
        self.build_shell()
        self.goto(start_page or self.prefs.get("page") or "overview")
        self.update_title()
        self.deiconify()
        theme.dark_title_bar(self, self.mode == "dark")
        self.after(2000, self.poll_status)
        self.after(60, self._pump_background)
        if state.SANDBOX and not os.getenv("MANAGER_QUIET"):  # MANAGER_QUIET — для снимков в инструкцию
            self.notify("info", "Песочница", "Изменения пишутся в runtime/sandbox, бот и файлы не трогаются.")

    # ---------- окно ----------
    def _set_icon(self):
        self.icon_photo = theme.app_icon_image(32)
        if self.icon_photo:
            self.iconphoto(True, self.icon_photo)
        ico = os.path.join(state.APP, "assets", "icon.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(default=ico)
            except tk.TclError:
                pass

    def _geometry(self):
        self.minsize(px(980), px(640))
        geo = self.prefs.get("geometry")
        if geo:
            try:
                self.geometry(geo)
                return
            except tk.TclError:
                pass
        w, h = min(px(1240), self.winfo_screenwidth() - px(60)), min(px(820), self.winfo_screenheight() - px(80))
        x, y = (self.winfo_screenwidth() - w) // 2, max(0, (self.winfo_screenheight() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def bot_name(self) -> str:
        return self.store.get("s:bot.name", saved=True) or "Бот"

    def update_title(self):
        self.title(f"{self.bot_name()} — панель управления")
        if hasattr(self, "nav_name"):
            self.nav_name.configure(text=self.bot_name())

    # ---------- каркас ----------
    def build_shell(self):
        self.configure(bg=C("bg"))
        self.shell = tk.Frame(self, bg=C("bg"))
        self.shell.pack(fill="both", expand=True)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(0, weight=1)

        nav = self.nav = tk.Frame(self.shell, bg=C("nav"), width=px(272))
        nav.grid(row=0, column=0, sticky="ns")
        nav.grid_propagate(False)
        nav.pack_propagate(False)
        head = tk.Frame(nav, bg=C("nav"))
        head.pack(fill="x", padx=px(20), pady=(px(22), px(18)))
        img = theme.app_icon_image(36)
        if img:
            tk.Label(head, image=img, bg=C("nav")).pack(side="left")
            self._head_img = img
        names = tk.Frame(head, bg=C("nav"))
        names.pack(side="left", padx=(px(12), 0))
        self.nav_name = tk.Label(names, text=self.bot_name(), font=font("strong"), fg=C("text"), bg=C("nav"))
        self.nav_name.pack(anchor="w")
        status = tk.Frame(names, bg=C("nav"), cursor="hand2")
        status.pack(anchor="w", pady=(px(3), 0))
        self.nav_dot = W.Dot(status, "idle", 8)
        self.nav_dot.pack(side="left")
        self.nav_status = tk.Label(status, text="", font=font("caption"), fg=C("text2"), bg=C("nav"), anchor="w",
                                   justify="left", wraplength=px(170))
        self.nav_status.pack(side="left", padx=(px(6), 0))
        for w in (status, self.nav_status, self.nav_dot):
            w.bind("<Button-1>", lambda e: self.goto("overview"))

        self.nav_items = {}
        group = None
        bottom = []
        for key, title, icon, grp, _ in registry.PAGES:
            if grp == "bottom":
                bottom.append((key, title, icon))
                continue
            if grp and grp != group:
                tk.Label(nav, text=grp, font=font("caption"), fg=C("text3"), bg=C("nav")).pack(
                    anchor="w", padx=px(24), pady=(px(14), px(4)))
            group = grp
            item = NavItem(nav, key, title, icon, self.goto)
            item.pack(fill="x", padx=px(4))
            self.nav_items[key] = item

        foot = tk.Frame(nav, bg=C("nav"))
        foot.pack(side="bottom", fill="x", pady=(0, px(14)))
        for key, title, icon in bottom:
            item = NavItem(foot, key, title, icon, self.goto)
            item.pack(fill="x", padx=px(4))
            self.nav_items[key] = item
        tk.Frame(self.shell, bg=C("divider"), width=1).grid(row=0, column=0, sticky="nse")

        content = self.content = tk.Frame(self.shell, bg=C("bg"))
        content.grid(row=0, column=1, sticky="nsew")
        content.rowconfigure(1, weight=1)
        content.columnconfigure(0, weight=1)
        self.bar_area = tk.Frame(content, bg=C("bg"))
        self.bar_area.grid(row=0, column=0, sticky="ew")
        self.host = tk.Frame(content, bg=C("bg"))
        self.host.grid(row=1, column=0, sticky="nsew")

        self.savebar = tk.Frame(content, bg=C("card"))
        tk.Frame(self.savebar, bg=C("divider"), height=1).pack(fill="x")
        sb = tk.Frame(self.savebar, bg=C("card"))
        sb.pack(fill="x", padx=px(28), pady=px(12))
        tk.Label(sb, text=glyph("edit"), font=icon_font(14), fg=C("accent"), bg=C("card")).pack(side="left")
        self.savebar_text = tk.Label(sb, text="Есть несохранённые изменения", font=font("body"), fg=C("text"),
                                     bg=C("card"))
        self.savebar_text.pack(side="left", padx=(px(10), 0))
        W.button(sb, "Сохранить", self.save, "accent", "save").pack(side="right")
        W.button(sb, "Отменить", self.discard).pack(side="right", padx=(0, px(8)))
        tk.Label(sb, text="Ctrl+S", font=font("caption"), fg=C("text3"), bg=C("card")).pack(side="right",
                                                                                           padx=(0, px(14)))
        self.update_nav_status()

    def rebuild(self):
        """Пересобрать окно (смена темы, отмена изменений)."""
        current = self.current or "overview"
        for bar in list(self.bars):
            bar.destroy()
        self.bars.clear()
        self.shell.destroy()
        self.pages.clear()
        self.current = None
        self.build_shell()
        self.goto(current)
        self.changed()

    def goto(self, key: str):
        if key not in self.nav_items:
            key = "overview"
        if self.current == key:
            return
        if self.current and self.current in self.pages:
            self.pages[self.current].pack_forget()
        for k, item in self.nav_items.items():
            item.set_selected(k == key)
        page = self.pages.get(key)
        if page is None:
            cls = registry.load(key)
            try:
                page = cls(self, self.host)
            except Exception:
                self._on_error(*sys.exc_info())
                return
            self.pages[key] = page
        page.pack(fill="both", expand=True)
        self.current = key
        self.prefs["page"] = key
        try:
            page.on_show()
            page.on_status(self.status)
        except Exception:
            self._on_error(*sys.exc_info())

    # ---------- черновик ----------
    def changed(self):
        dirty = self.store.dirty()
        if dirty and not self.savebar.winfo_ismapped():
            self.savebar.grid(row=2, column=0, sticky="ew")
        elif not dirty and self.savebar.winfo_ismapped():
            self.savebar.grid_remove()

    def save(self, quiet: bool = False) -> bool:
        if not self.store.dirty():
            return True
        try:
            changed = self.store.save()
        except Exception as e:
            self.notify("error", "Не удалось сохранить", str(e))
            return False
        self.changed()
        self.update_title()
        if quiet:
            return True
        needs_restart = bool(changed & {"s", "e", "r", "x"})
        if needs_restart and (self.status or state.sync_enabled(self.store.saved["e"])):
            self.notify("success", "Изменения сохранены", "Бот применит их после перезапуска.",
                        actions=[("Перезапустить сейчас", self.apply_changes)], timeout=20000)
        else:
            self.notify("success", "Изменения сохранены", timeout=5000)
        return True

    def discard(self):
        self.store.discard()
        self.rebuild()
        self.notify("info", "Изменения отменены", timeout=4000)

    def ensure_saved(self, what: str = "Сначала нужно сохранить изменения.") -> bool:
        if not self.store.dirty():
            return True
        if self.confirm("Сохранить изменения?", what, ok="Сохранить"):
            return self.save(quiet=True)
        return False

    def apply_changes(self):
        """Разослать настройки на другие ПК (если их несколько) и перезапустить бота."""
        def work():
            published = None
            if state.sync_enabled():
                published = state.publish_update("Настройки из панели управления")
            state.send_command("restart_bot")
            return published

        def done(published, error):
            if error:
                self.notify("error", "Не удалось применить", str(error))
            else:
                extra = " Остальные ПК получат настройки в течение минуты." if published else ""
                self.notify("success", "Бот перезапускается", "Это займёт около 10 секунд." + extra, timeout=8000)
        self.background(work, done)

    # ---------- статус бота ----------
    def poll_status(self):
        try:
            self.status = self.read_status()
            self.update_nav_status()
            page = self.pages.get(self.current)
            if page:
                page.on_status(self.status)
        except Exception:
            traceback.print_exc()
        self.after(2000, self.poll_status)

    def read_status(self):
        """Статус диспетчера (в проверках интерфейса подменяется примерами)."""
        return state.read_status()

    def update_nav_status(self):
        st = self.status
        if st is None:
            color, text = "idle", "Не запущен на этом ПК"
        elif st.get("state") == "active":
            ok = st.get("bot_running")
            color, text = ("success", "Работает на этом ПК") if ok else ("warning", "Запускается…")
        else:
            other = st.get("active_host")
            color, text = ("info", f"Работает на «{other}»") if other else ("warning", "Ожидание другого ПК")
        self.nav_dot.set(color)
        self.nav_status.configure(text=text)

    # ---------- уведомления и диалоги ----------
    def notify(self, kind: str, title: str, message: str = "", actions=None, timeout: int | None = None):
        for bar in list(self.bars):  # одно и то же уведомление не дублируем
            if getattr(bar, "_title", None) == title:
                bar.close()
        bar = W.InfoBar(self.bar_area, kind, title, message, actions, on_close=self._bar_closed)
        bar._title = title
        bar.pack(fill="x", padx=px(36), pady=(px(14), 0))
        self.bars.append(bar)
        while len(self.bars) > 3:
            self.bars[0].close()
        if timeout:
            self.after(timeout, lambda: bar.winfo_exists() and bar.close())
        return bar

    def _bar_closed(self, bar):
        if bar in self.bars:
            self.bars.remove(bar)

    def confirm(self, title: str, message: str, ok: str = "Продолжить", cancel: str = "Отмена",
                danger: bool = False) -> bool:
        return bool(W.MessageDialog(self, title, message, ok, cancel, danger).show())

    def message(self, title: str, message: str):
        W.MessageDialog(self, title, message, "OK", None).show()

    def prompt(self, title: str, label: str, initial: str = "", ok: str = "OK", placeholder: str = "") -> str | None:
        data = W.FormDialog(self, title, [{"key": "v", "label": label, "placeholder": placeholder}],
                            {"v": initial}, ok).show()
        return None if data is None else data["v"]

    def form(self, title: str, fields, values=None, ok: str = "Сохранить", validate=None) -> dict | None:
        return W.FormDialog(self, title, fields, values, ok, validate).show()

    def run_task(self, title: str, args: list[str], description: str = "", on_done=None, success: str = "Готово",
                 failure: str = "Не получилось"):
        return W.TaskDialog(self, title, args, description, on_done, success, failure).show()

    def background(self, fn, on_done=None):
        """fn() — в отдельном потоке; on_done(result, error) — снова в окне программы."""
        def run():
            try:
                result, error = fn(), None
            except Exception as e:
                result, error = None, e
            self._bg_queue.put((on_done, result, error))
        threading.Thread(target=run, daemon=True).start()

    def _pump_background(self):
        while not self._bg_queue.empty():
            on_done, result, error = self._bg_queue.get()
            if on_done:
                try:
                    on_done(result, error)
                except Exception:
                    self._on_error(*sys.exc_info())
        self.after(60, self._pump_background)

    def _on_error(self, exc, value, tb):
        text = "".join(traceback.format_exception(exc, value, tb))
        sys.stderr.write(text)
        try:
            with open(os.path.join(state.RUNTIME, "manager-errors.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
        except OSError:
            pass
        try:
            self.notify("error", "Внутренняя ошибка программы", f"{exc.__name__}: {value}")
        except Exception:
            pass

    # ---------- тема ----------
    def set_theme(self, mode: str):
        self.prefs["theme"] = mode
        self.mode = theme.apply(self, mode)
        self._set_icon()
        self.rebuild()

    # ---------- закрытие ----------
    def on_close(self):
        if self.store.dirty():
            choice = W.MessageDialog(self, "Сохранить изменения?",
                                     "В настройках есть несохранённые изменения.", "Сохранить", "Отмена",
                                     extra=("Не сохранять", "discard")).show()
            if choice is None:
                return
            if choice is True and not self.save(quiet=True):
                return
        try:
            if self.state() == "normal":
                self.prefs["geometry"] = self.geometry()
            state.save_prefs(self.prefs)
        except Exception:
            pass
        self.destroy()


def _single_instance():
    """Вторая копия программы не открывается — показывает первую."""
    if state.SANDBOX:
        return None
    path = os.path.join(state.RUNTIME, "manager.lock")
    try:
        import msvcrt
        f = open(path, "a+")
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except ImportError:
        return None
    except OSError:
        try:
            import ctypes
            hwnd = int(open(os.path.join(state.RUNTIME, "manager.hwnd")).read().strip())
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        sys.exit(0)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    page = argv[argv.index("--page") + 1] if "--page" in argv else None
    mode = argv[argv.index("--theme") + 1] if "--theme" in argv else None
    lock = _single_instance()
    app = App(page, mode)
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(app.winfo_id())
        if not state.SANDBOX:
            with open(os.path.join(state.RUNTIME, "manager.hwnd"), "w") as f:
                f.write(str(hwnd))
    except Exception:
        pass
    app.mainloop()
    del lock
