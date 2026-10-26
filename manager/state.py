"""Данные панели управления (без интерфейса): настройки, ключи (.env), этот ПК (host.json), правила, статус бота,
команды диспетчеру, Discord API, ярлыки, журналы и резервные копии.

Песочница: MANAGER_SANDBOX=1 — ничего настоящего не меняется (файлы пишутся в runtime/sandbox, команды боту и
внешние программы не запускаются). Нужна для проверки интерфейса, пока настоящий бот работает.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

SANDBOX = os.getenv("MANAGER_SANDBOX") == "1"
RUNTIME = os.path.join(APP, "runtime")
SANDBOX_DIR = os.path.join(RUNTIME, "sandbox")
os.makedirs(SANDBOX_DIR if SANDBOX else RUNTIME, exist_ok=True)

ENV_PATH = os.path.join(APP, ".env")
ENV_EXAMPLE = os.path.join(APP, ".env.example")
HOST_PATH = os.path.join(APP, "host.json")
SETTINGS_PATH = os.path.join(APP, "settings.json")
EXAMPLE_PATH = os.path.join(APP, "settings.example.json")
RULES_PATH = os.path.join(APP, "rules.json")
RULES_EXAMPLE = os.path.join(APP, "rules.example.json")
STATUS_PATH = os.path.join(RUNTIME, "status.json")
COMMAND_PATH = os.path.join(RUNTIME, "command.txt")
PREFS_PATH = os.path.join(RUNTIME, "manager.json")
BACKUPS_DIR = os.path.join(RUNTIME, "backups")
LOGS = {"bot": os.path.join(APP, "bot.log"), "supervisor": os.path.join(RUNTIME, "supervisor.log")}

PY = os.path.join(APP, ".venv", "Scripts", "python.exe")
PYW = os.path.join(APP, ".venv", "Scripts", "pythonw.exe")
if not os.path.exists(PY):
    PY = sys.executable
    PYW = sys.executable.replace("python.exe", "pythonw.exe") if sys.executable.endswith("python.exe") else PY
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SANDBOX_LOG: list[str] = []


def _out(path: str) -> str:
    """Куда писать: в песочнице — копия в runtime/sandbox."""
    return os.path.join(SANDBOX_DIR, os.path.basename(path)) if SANDBOX else path


def _in(path: str) -> str:
    """Откуда читать: в песочнице — сначала её копия."""
    if SANDBOX and os.path.exists(_out(path)):
        return _out(path)
    return path


def sandbox_note(what: str):
    SANDBOX_LOG.append(time.strftime("%H:%M:%S ") + what)


# ---------- настройки ----------
def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_example() -> dict:
    return _read_json(EXAMPLE_PATH, {})


def load_settings() -> dict:
    """Все настройки: settings.example.json + свои из settings.json поверх."""
    return merge(load_example(), _read_json(_in(SETTINGS_PATH), {}) or {})


_MISSING = object()


def diff(cur, base):
    """Только то, что отличается от settings.example.json — так settings.json остаётся коротким."""
    if isinstance(cur, dict) and isinstance(base, dict):
        out = {}
        for k, v in cur.items():
            if k.startswith("_"):
                continue
            d = diff(v, base[k]) if k in base else v
            if d is not _MISSING:
                out[k] = d
        return out or _MISSING
    return _MISSING if cur == base else cur


def save_settings(data: dict):
    d = diff(data, load_example())
    with open(_out(SETTINGS_PATH), "w", encoding="utf-8") as f:
        json.dump({} if d is _MISSING else d, f, ensure_ascii=False, indent=2)


# ---------- правила ----------
def load_rules() -> dict:
    return _read_json(_in(RULES_PATH)) or _read_json(RULES_EXAMPLE, {})


def rules_custom() -> bool:
    return os.path.exists(_in(RULES_PATH))


def save_rules(data: dict):
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    with open(_out(RULES_PATH), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- .env ----------
def read_env() -> dict:
    path = _in(ENV_PATH) if os.path.exists(_in(ENV_PATH)) else ENV_EXAMPLE
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                out[m[1]] = m[2].strip()
    return out


def write_env(updates: dict):
    """Меняет только указанные ключи, остальные строки и комментарии остаются как были."""
    src = _in(ENV_PATH) if os.path.exists(_in(ENV_PATH)) else ENV_EXAMPLE
    lines = open(src, encoding="utf-8-sig").read().splitlines() if os.path.exists(src) else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m[1] in updates:
            lines[i] = f"{m[1]}={updates[m[1]]}"
            done.add(m[1])
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    with open(_out(ENV_PATH), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def token_looks_valid(token: str) -> bool:
    return bool(re.fullmatch(r"[\w-]{20,}\.[\w-]{4,}\.[\w-]{20,}", token or ""))


# ---------- этот ПК ----------
def read_host() -> dict:
    data = _read_json(_in(HOST_PATH))
    if not isinstance(data, dict):
        name = socket.gethostname()
        data = {"name": name, "priority": 1, "id": re.sub(r"\W+", "-", name.lower()).strip("-") or "pc"}
    data.setdefault("priority", 1)
    data.setdefault("mode", "auto")
    data.setdefault("kind", "pc")
    data.setdefault("id", re.sub(r"\W+", "-", str(data.get("name", "pc")).lower()).strip("-") or "pc")
    return data


def write_host(data: dict):
    with open(_out(HOST_PATH), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ---------- черновик: всё, что можно поменять в программе ----------
class Store:
    """Сохранённое состояние и черновик. Пути: «s:bot.name» — настройки, «e:DISCORD_TOKEN» — .env,
    «h:priority» — этот ПК, «r:intro» — правила, «x:banner» — баннер (keep / remove / путь к новой картинке)."""

    KINDS = ("s", "e", "h", "r", "x")

    def __init__(self):
        self.reload()

    def reload(self):
        self.saved = {"s": load_settings(), "e": read_env(), "h": read_host(), "r": load_rules(),
                      "x": {"banner": "keep"}}
        self.draft = copy.deepcopy(self.saved)

    @staticmethod
    def _split(path: str) -> tuple[str, list[str]]:
        kind, _, rest = path.partition(":")
        if kind not in Store.KINDS:
            raise KeyError(f"неизвестный раздел в пути {path!r}")
        return kind, [p for p in rest.split(".") if p] if kind != "e" else [rest]

    def get(self, path: str, default=None, saved: bool = False):
        kind, keys = self._split(path)
        node = (self.saved if saved else self.draft)[kind]
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return copy.deepcopy(default)
        return copy.deepcopy(node)

    def set(self, path: str, value):
        kind, keys = self._split(path)
        node = self.draft[kind]
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = copy.deepcopy(value)

    def dirty(self) -> bool:
        return self.draft != self.saved

    def changed(self) -> set[str]:
        return {k for k in self.KINDS if self.draft[k] != self.saved[k]}

    def discard(self):
        self.draft = copy.deepcopy(self.saved)

    def save(self) -> set[str]:
        """Записать изменения. Возвращает, что поменялось: s, e, h, r, x."""
        ch = self.changed()
        if "s" in ch:
            save_settings(self.draft["s"])
        if "e" in ch:
            old, new = self.saved["e"], self.draft["e"]
            write_env({k: v for k, v in new.items() if old.get(k) != v})
        if "h" in ch:
            write_host(self.draft["h"])
        if "r" in ch:
            save_rules(self.draft["r"])
        if "x" in ch:
            apply_banner(self.draft["x"].get("banner", "keep"), self.draft["s"])
            self.draft["x"]["banner"] = "keep"
        self.saved = copy.deepcopy(self.draft)
        return ch


# ---------- баннер ----------
def banner_path(settings: dict) -> str:
    rel = (settings.get("theme") or {}).get("welcome_banner") or "assets/welcome_bg.png"
    return os.path.join(APP, rel)


def apply_banner(op: str, settings: dict):
    target = banner_path(settings)
    if SANDBOX:
        return sandbox_note(f"баннер: {op}")
    if op == "remove":
        if os.path.exists(target):
            os.remove(target)
    elif op not in ("keep", "", None):
        from PIL import Image
        os.makedirs(os.path.dirname(target), exist_ok=True)
        Image.open(op).convert("RGB").save(target, "PNG")


# ---------- статус бота и команды диспетчеру ----------
def read_status(max_age: float = 40) -> dict | None:
    """runtime/status.json от диспетчера; None — диспетчер не запущен на этом ПК."""
    data = _read_json(STATUS_PATH)
    if not isinstance(data, dict) or time.time() - data.get("ts", 0) > max_age:
        return None
    return data


def supervisor_running() -> bool:
    return read_status() is not None


def sync_enabled(env: dict | None = None) -> bool:
    env = env if env is not None else read_env()
    return bool(env.get("SYNC_CHANNEL_ID") and env.get("SYNC_HEARTBEAT_ID"))


def send_command(cmd: str):
    """restart_bot, backup, check_update, stop, take_here, unpin."""
    if SANDBOX:
        return sandbox_note(f"команда диспетчеру: {cmd}")
    with open(COMMAND_PATH, "w", encoding="utf-8") as f:
        f.write(cmd)


def start_supervisor():
    if SANDBOX:
        return sandbox_note("запуск диспетчера")
    vbs = os.path.join(APP, "tools", "run_hidden.vbs")
    if os.name == "nt":
        subprocess.Popen(["wscript.exe", vbs], cwd=APP)
    else:
        subprocess.Popen([PY, "-X", "utf8", "supervisor.py"], cwd=APP, start_new_session=True)


def tool_args(script: str, *args: str) -> list[str]:
    """Команда для запуска служебного скрипта из tools/."""
    return [PY, "-X", "utf8", os.path.join("tools", script), *args]


def publish_update(note: str) -> int:
    """Разослать текущий код и настройки на остальные ПК (синхронизация должна быть включена)."""
    if SANDBOX:
        sandbox_note(f"публикация обновления: {note}")
        return int(time.time())
    import asyncio
    import importlib
    import sync
    importlib.reload(sync)  # перечитать .env: ключи могли поменяться в программе
    return asyncio.run(sync.publish(note))


def local_version() -> int:
    try:
        with open(os.path.join(APP, "version.txt")) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


# ---------- Discord API (без запуска бота) ----------
def api(token: str, path: str, timeout: float = 15):
    req = urllib.request.Request("https://discord.com/api/v10" + path, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (manager, 1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check_token(token: str) -> dict:
    """Проверка ключа: имя бота, ID приложения, включены ли нужные «intents», на каких серверах бот.
    Ошибки: ValueError (неверный ключ), OSError (нет связи)."""
    try:
        me = api(token, "/users/@me")
        app = api(token, "/oauth2/applications/@me")
        guilds = api(token, "/users/@me/guilds")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ValueError("Ключ не подходит. Скопируйте его заново: Bot → Reset Token.") from e
        raise OSError(f"Discord ответил ошибкой {e.code}") from e
    except urllib.error.URLError as e:
        raise OSError(f"Нет связи с Discord: {e.reason}") from e
    flags = app.get("flags", 0)
    return {"bot": app.get("name") or me.get("global_name") or me.get("username", "?"), "username": me.get("username"),
            "bot_id": me.get("id"), "app_id": app.get("id"),
            "members_intent": bool(flags & (1 << 14 | 1 << 15)), "content_intent": bool(flags & (1 << 18 | 1 << 19)),
            "guilds": [{"id": g["id"], "name": g["name"]} for g in guilds]}


def app_id_from_token(token: str) -> str | None:
    try:
        part = token.split(".")[0]
        value = base64.b64decode(part + "=" * (-len(part) % 4)).decode()
        return value if value.isdigit() else None
    except Exception:
        return None


def invite_url(app_id: str) -> str:
    return f"https://discord.com/oauth2/authorize?client_id={app_id}&permissions=8&scope=bot%20applications.commands"


# ---------- ярлыки и автозапуск (Windows) ----------
def _ps(script: str, timeout: float = 60) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=NO_WINDOW)
    return r.stdout.strip()


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


VBS = os.path.join(APP, "tools", "run_hidden.vbs")
MANAGER = os.path.join(APP, "manager.pyw")
ICON = os.path.join(APP, "assets", "icon.ico")


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    out = _ps(f"""$sh = New-Object -ComObject WScript.Shell
$n = 0; Get-ChildItem ([Environment]::GetFolderPath('Startup')) -Filter *.lnk -ErrorAction SilentlyContinue |
 ForEach-Object {{ if ($sh.CreateShortcut($_.FullName).Arguments -like ('*' + {_q(VBS)} + '*')) {{ $n++ }} }}; $n""")
    return out.strip().isdigit() and int(out) > 0


def set_autostart(on: bool, name: str):
    if SANDBOX:
        return sandbox_note(f"автозапуск: {on}")
    if on:
        _ps(f"""$sh = New-Object -ComObject WScript.Shell
$have = $false; $startup = [Environment]::GetFolderPath('Startup')
Get-ChildItem $startup -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {{
 if ($sh.CreateShortcut($_.FullName).Arguments -like ('*' + {_q(VBS)} + '*')) {{ $have = $true }} }}
if (-not $have) {{ $l = $sh.CreateShortcut((Join-Path $startup ({_q(name)} + ' (автозапуск).lnk')))
 $l.TargetPath = 'C:\\Windows\\System32\\wscript.exe'; $l.Arguments = '"' + {_q(VBS)} + '"'
 $l.WorkingDirectory = {_q(APP)}; $l.Save() }}""")
    else:
        _ps(f"""$sh = New-Object -ComObject WScript.Shell
Get-ChildItem ([Environment]::GetFolderPath('Startup')) -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {{
 if ($sh.CreateShortcut($_.FullName).Arguments -like ('*' + {_q(VBS)} + '*')) {{ Remove-Item $_.FullName }} }}""")


def ensure_shortcut(name: str):
    """Один ярлык программы на рабочем столе. Старые ярлыки панели и мастера настройки этой папки — убираем."""
    if SANDBOX:
        return sandbox_note(f"ярлык на рабочем столе: {name}")
    if os.name != "nt":
        return
    legacy = [os.path.join(APP, "control_panel.pyw"), os.path.join(APP, "configure.pyw")]
    _ps(f"""$sh = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath('Desktop')
Get-ChildItem $desk -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {{
 $a = $sh.CreateShortcut($_.FullName).Arguments
 if ($a -like ('*' + {_q(legacy[0])} + '*') -or $a -like ('*' + {_q(legacy[1])} + '*') -or $a -like ('*' + {_q(MANAGER)} + '*')) {{ Remove-Item $_.FullName }} }}
$l = $sh.CreateShortcut((Join-Path $desk ({_q(name)} + '.lnk')))
$l.TargetPath = {_q(PYW)}; $l.Arguments = '"' + {_q(MANAGER)} + '"'; $l.WorkingDirectory = {_q(APP)}
$l.Description = 'Панель управления ботом'
if (Test-Path {_q(ICON)}) {{ $l.IconLocation = {_q(ICON)} }}
$l.Save()""")


# ---------- открыть файл / папку / ссылку ----------
def open_path(path: str):
    if SANDBOX:
        return sandbox_note(f"открыть: {path}")
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def open_url(url: str):
    if SANDBOX:
        return sandbox_note(f"ссылка: {url}")
    import webbrowser
    webbrowser.open(url)


# ---------- журналы и копии базы ----------
def tail(path: str, lines: int = 500) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return data.splitlines()[-lines:]


def list_backups() -> list[dict]:
    out = []
    try:
        for name in os.listdir(BACKUPS_DIR):
            path = os.path.join(BACKUPS_DIR, name)
            if name.endswith(".db") and os.path.isfile(path):
                st = os.stat(path)
                out.append({"name": name, "path": path, "size": st.st_size, "mtime": st.st_mtime})
    except OSError:
        pass
    return sorted(out, key=lambda b: -b["mtime"])


# ---------- параметры самой программы (у каждого ПК свои) ----------
def load_prefs() -> dict:
    return _read_json(_in(PREFS_PATH), {}) or {}


def save_prefs(prefs: dict):
    with open(_out(PREFS_PATH), "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=1)
