"""Проверка интерфейса без вмешательства в работу бота (всегда в песочнице).

  python -m manager.devtools check [раздел …]          — собрать разделы и прогнать их с разными статусами бота
  python -m manager.devtools snap раздел [--theme dark|light] [--out папка] [--pages N]
                                                       — снимки раздела (N экранов с прокруткой)

Снимок делается через PrintWindow: окно стоит за другими окнами и не мешает работать на ПК.
"""
import ctypes
import os
import sys
import time
import traceback

os.environ["MANAGER_SANDBOX"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import pages as registry  # noqa: E402
from manager import state  # noqa: E402

NOW = time.time()
SAMPLE_HOSTS = [
    {"id": "main-pc", "name": "Основной ПК", "priority": 1, "kind": "pc", "mode": "auto", "state": "active",
     "load": 23, "cpu": 20, "ram": 61, "version": 1, "ts": NOW - 20, "os": "Windows"},
    {"id": "laptop", "name": "Ноутбук", "priority": 2, "kind": "pc", "mode": "auto", "state": "standby",
     "load": 71, "cpu": 68, "ram": 77, "version": 1, "ts": NOW - 35, "os": "Windows"},
    {"id": "vps", "name": "Хостинг", "priority": 3, "kind": "server", "mode": "manual", "state": "standby",
     "load": 4, "cpu": 4, "ram": 30, "version": 1, "ts": NOW - 50, "os": "Linux"},
    {"id": "old", "name": "Ноутбук", "priority": 4, "kind": "pc", "mode": "auto", "state": "standby",
     "load": None, "version": 1, "ts": NOW - 86400 * 3, "os": "Windows"},
]
STATUSES = {
    "stopped": None,
    "solo": {"ts": NOW, "state": "active", "solo": True, "note": "работаю (один ПК)", "bot_running": True,
             "bot_started": NOW - 7200, "me": {"id": "laptop", "name": "Ноутбук", "priority": 1}, "hosts": [],
             "version": 1792952533, "last_db_upload": 0},
    "active": {"ts": NOW, "state": "active", "solo": False, "note": "работаю", "bot_running": True,
               "bot_started": NOW - 3600 * 26, "me": {"id": "main-pc", "name": "Основной ПК", "priority": 1},
               "hosts": SAMPLE_HOSTS, "active_host": "Основной ПК", "active_ts": NOW - 5, "pinned": None,
               "version": 1792952533, "last_db_upload": NOW - 70, "mode": "auto", "balance": True, "load": 23},
    "standby": {"ts": NOW, "state": "standby", "solo": False, "note": "в резерве: работает «Основной ПК»",
                "bot_running": False, "bot_started": 0, "me": {"id": "laptop", "name": "Ноутбук", "priority": 2},
                "hosts": SAMPLE_HOSTS, "active_host": "Основной ПК", "active_ts": NOW - 5, "pinned": "main-pc",
                "version": 1792952533, "last_db_upload": 0, "mode": "auto", "balance": True, "load": 71},
}


def make_app(page=None, mode="dark"):
    from manager.app import App
    return App(page, mode)


def pump(app, seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def capture(window, path: str):
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = user32.GetParent(window.winfo_id())
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)


def check(keys):
    """Собрать разделы и вызвать on_show/on_status со всеми примерами статуса. Возвращает число ошибок."""
    errors = 0
    app = make_app("overview", "dark")
    app.lower()
    for key in keys:
        try:
            app.goto(key)
            pump(app, 0.3)
            page = app.pages.get(key)
            if page is None or type(page).__name__ == "Placeholder":
                raise RuntimeError("раздел не загрузился (заглушка)")
            for name, st in STATUSES.items():
                app.status = st
                app.read_status = lambda st=st: st
                page.on_status(st)
                pump(app, 0.1)
            page.on_show()
            pump(app, 0.2)
            print(f"OK    {key}")
        except Exception:
            errors += 1
            print(f"FAIL  {key}\n{traceback.format_exc()}")
    for theme_mode in ("light",):
        try:
            app.set_theme(theme_mode)
            for key in keys:
                app.goto(key)
                pump(app, 0.2)
            print(f"OK    тема {theme_mode}: все разделы пересобрались")
        except Exception:
            errors += 1
            print(f"FAIL  тема {theme_mode}\n{traceback.format_exc()}")
    if state.SANDBOX_LOG:
        print("Действия в песочнице:", *state.SANDBOX_LOG, sep="\n  ")
    app.destroy()
    return errors


def snap(key, mode="dark", out=None, screens=2, status="active", size=(1240, 820)):
    out = out or os.path.join(state.RUNTIME, "sandbox", "snaps")
    os.makedirs(out, exist_ok=True)
    app = make_app(key, mode)
    app.geometry(f"{size[0]}x{size[1]}+30+30")
    app.status = STATUSES.get(status)
    app.read_status = lambda: STATUSES.get(status)
    app.lower()
    pump(app, 0.8)
    page = app.pages.get(key)
    if page:
        page.on_status(app.status)
    app.update_nav_status()
    pump(app, 0.6)
    files = []
    for i in range(screens):
        path = os.path.join(out, f"{key}_{mode}_{i + 1}.png")
        capture(app, path)
        files.append(path)
        if page is None or page.scroller is None:
            break
        canvas = page.scroller.canvas
        first, last = canvas.yview()
        if last >= 1:
            break
        canvas.yview_moveto(last)
        pump(app, 0.4)
    app.destroy()
    return files


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("check", "snap"):
        print(__doc__)
        sys.exit(2)
    if args[0] == "check":
        keys = args[1:] or [p[0] for p in registry.PAGES]
        sys.exit(1 if check(keys) else 0)
    key = args[1]
    mode = args[args.index("--theme") + 1] if "--theme" in args else "dark"
    out = args[args.index("--out") + 1] if "--out" in args else None
    screens = int(args[args.index("--pages") + 1]) if "--pages" in args else 2
    status = args[args.index("--status") + 1] if "--status" in args else "active"
    for f in snap(key, mode, out, screens, status):
        print(f)
