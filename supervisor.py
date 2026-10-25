"""Диспетчер бота: запускается вместо bot.py (автозагрузка Windows) на КАЖДОМ ПК.

Работает всегда ровно ОДНА копия бота:
  • Каждые 15 сек активная копия пишет «пульс» в #🔧・bot-sync.
  • Запасная копия следит за пульсом. Пропал больше чем на 75 сек (ПК выключили) — запускается сама.
  • Если включился ПК с более высоким приоритетом (priority в host.json: 1 — главный), он вежливо
    «просит» управление, текущая копия сохраняет базу и отдаёт его — без двойных ответов.
  • База bot.db едет вместе с ботом: активная копия раз в 2 минуты кладёт снимок в Discord,
    новая активная копия перед стартом забирает самый свежий.
  • Обновления кода: кто-то нажал «Опубликовать обновление» — все ПК скачают и поставят его сами.

Если синхронизация не включена (нет SYNC_CHANNEL_ID в .env) — режим «один ПК»: диспетчер просто держит бота
запущенным (сторож + ежедневные копии базы на диске).

Статус для панели управления — runtime/status.json, команды от панели — runtime/command.txt."""
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback

import sync

TICK = 15            # сек между проверками
STALE = 75           # пульс старше — копия считается выключенной
DB_EVERY = 120       # снимок базы не чаще
DB_FORCE = 600       # и обязательно хотя бы раз в 10 минут
CODE_EVERY = 60      # проверка обновлений кода
EXIT_STOP = 3        # код выхода «остановлен вручную» (autostart.bat не перезапускает)
FROZEN_AFTER = 120   # бот столько сек без связи с Discord — перезапуск

APP = sync.APP
DB = os.path.join(APP, "bot.db")
STATUS = os.path.join(sync.RUNTIME, "status.json")
COMMAND = os.path.join(sync.RUNTIME, "command.txt")
DB_TS = os.path.join(sync.RUNTIME, "db_ts.txt")
LOG = os.path.join(sync.RUNTIME, "supervisor.log")


def log(msg: str):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_db_ts() -> float:
    try:
        return float(open(DB_TS).read().strip())
    except (OSError, ValueError):
        return 0.0


def write_db_ts(ts: float):
    with open(DB_TS, "w") as f:
        f.write(str(ts))


def snapshot_db() -> bytes:
    """Безопасная копия базы, даже пока бот с ней работает."""
    tmp = os.path.join(sync.RUNTIME, "snapshot.db")
    if os.path.exists(tmp):
        os.remove(tmp)
    src, dst = sqlite3.connect(DB), sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    with open(tmp, "rb") as f:
        return f.read()


class Supervisor:
    def __init__(self):
        self.me = sync.host_info()
        self.state = "standby"           # standby | active
        self.bot: subprocess.Popen | None = None
        self.started_at = 0.0
        self.last_db_upload = 0.0
        self.last_db_mtime = 0.0
        self.last_code_check = 0.0
        self.hb: dict = {}
        self.note = ""

    # ---------- бот как дочерний процесс ----------
    def start_bot(self):
        env = dict(os.environ, BOT_HOST=self.me["name"], BOT_VERSION=str(sync.local_version()), BOT_SUPERVISED="1")
        out = open(os.path.join(APP, "bot.log"), "a", encoding="utf-8")
        self.bot = subprocess.Popen([sys.executable, "-X", "utf8", "-W", "ignore", "bot.py"], cwd=APP, env=env,
                                    stdout=out, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.started_at = time.time()
        log(f"▶ бот запущен (pid {self.bot.pid})")

    def stop_bot(self):
        if self.bot and self.bot.poll() is None:
            self.bot.terminate()
            try:
                self.bot.wait(15)
            except subprocess.TimeoutExpired:
                self.bot.kill()
            log("⏹ бот остановлен")
        self.bot = None

    def frozen(self) -> bool:
        """Бот сам пишет runtime/bot_alive.txt раз в 30 сек, пока подключён к Discord."""
        if time.time() - self.started_at < FROZEN_AFTER:
            return False
        try:
            return time.time() - float(open(os.path.join(sync.RUNTIME, "bot_alive.txt")).read()) > FROZEN_AFTER
        except (OSError, ValueError):
            return True

    def local_watchdog(self):
        """Без всякой сети: упал — поднять, завис/потерял связь — перезапустить. Перезапуск сразу пробует
        подключиться, вместо того чтобы библиотека Discord ждала по 10–16 минут после обрыва интернета."""
        if self.state != "active":
            return
        if self.bot is None or self.bot.poll() is not None:
            if self.bot is not None:
                log(f"бот завершился с кодом {self.bot.returncode} — перезапуск")
            self.start_bot()
        elif self.frozen():
            log(f"⚠ бот без связи с Discord больше {FROZEN_AFTER // 60} мин — перезапускаю")
            self.stop_bot()
            self.start_bot()

    # ---------- база ----------
    async def upload_db(self, d: sync.Discord, force=False):
        if not os.path.exists(DB):
            return
        mtime = os.path.getmtime(DB)
        now = time.time()
        if not force and (now - self.last_db_upload < DB_EVERY or
                          (mtime == self.last_db_mtime and now - self.last_db_upload < DB_FORCE)):
            return
        data = snapshot_db()
        self.local_backup(data)
        await d.send_file("DB", {"ts": now, "host": self.me["name"], "size": len(data)}, "bot.db", data)
        for old in (await d.latest("DB"))[5:]:
            await d.delete(old["id"])
        self.last_db_upload, self.last_db_mtime = now, mtime
        write_db_ts(now)

    def local_backup(self, data: bytes | None = None, force: bool = False):
        """Копия базы на диске: раз в день, храним 14 дней (force — ещё одна прямо сейчас)."""
        if not os.path.exists(DB):
            return
        backups = os.path.join(sync.RUNTIME, "backups")
        os.makedirs(backups, exist_ok=True)
        path = os.path.join(backups, time.strftime("bot-%Y-%m-%d-%H%M.db" if force else "bot-%Y-%m-%d.db"))
        if os.path.exists(path):
            return
        with open(path, "wb") as f:
            f.write(data or snapshot_db())
        for old in sorted(os.listdir(backups))[:-14]:
            os.remove(os.path.join(backups, old))

    async def download_db(self, d: sync.Discord):
        snaps = await d.latest("DB")
        if not snaps:
            log("снимков базы в Discord нет — работаю со своей")
            return
        snap = snaps[0]
        if snap["meta"]["ts"] <= read_db_ts():
            log("моя база не старее снимка — оставляю свою")
            return
        data = await d.download(snap["url"])
        tmp = DB + ".download"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, DB)
        write_db_ts(snap["meta"]["ts"])
        log(f"⬇ база взята из снимка от {snap['meta'].get('host')} ({len(data)} байт)")

    # ---------- обновления кода ----------
    async def check_code(self, d: sync.Discord):
        if time.time() - self.last_code_check < CODE_EVERY:
            return
        self.last_code_check = time.time()
        codes = await d.latest("CODE")
        if not codes or codes[0]["meta"]["version"] <= sync.local_version():
            return
        new = codes[0]
        data = await d.download(new["url"])
        if hashlib.sha256(data).hexdigest() != new["meta"]["sha256"]:
            log("⚠ обновление повреждено — пропускаю")
            return
        req = os.path.join(APP, "requirements.txt")
        old_req = open(req, "rb").read() if os.path.exists(req) else b""
        log(f"⬇ обновление {new['meta']['version']} от {new['meta'].get('by')}: {new['meta'].get('note', '')}")
        was_active = self.state == "active"
        if was_active:
            self.stop_bot()
            await self.upload_db(d, force=True)
        sync.apply_code(data)
        sync.set_local_version(new["meta"]["version"])
        if open(req, "rb").read() != old_req:
            log("ставлю новые библиотеки…")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", req], cwd=APP)
        if was_active:  # отдаём пульс, чтобы не было «двоих» во время перезапуска
            await d.write_heartbeat({**self.hb, "active": None, "released_to": self.me["id"], "released_ts": time.time()})
        log("🔄 перезапускаю диспетчер с новым кодом")
        sys.exit(0)  # autostart.bat запустит заново уже обновлённый supervisor.py

    # ---------- выборы «кто главный» ----------
    def fresh(self, item: dict | None) -> bool:
        return bool(item) and time.time() - item.get("ts", 0) < STALE

    def outranks(self, other: dict) -> bool:
        """Я важнее другого? Меньше priority — важнее; при равенстве решает id."""
        return (self.me["priority"], self.me["id"]) < (other.get("priority", 99), other.get("id", ""))

    def my_record(self) -> dict:
        return {"id": self.me["id"], "host": self.me["name"], "priority": self.me["priority"], "ts": time.time(),
                "version": sync.local_version(), "started": self.started_at}

    async def tick(self, d: sync.Discord):
        hb = self.hb = await d.read_heartbeat()
        active, claim = hb.get("active"), hb.get("claim")
        other_active = self.fresh(active) and active["id"] != self.me["id"]

        if self.state == "active":
            if other_active and not self.outranks(active):        # двое сразу — уступает менее важный
                log(f"другая копия ({active['host']}) важнее — ухожу в резерв")
                return await self.release(d, active["id"])
            if self.fresh(claim) and claim["id"] != self.me["id"] and not self.outranks(claim):
                log(f"ПК «{claim['host']}» просит управление — передаю")
                return await self.release(d, claim["id"])
            self.local_watchdog()
            await d.write_heartbeat({"active": self.my_record(),
                                     "claim": claim if self.fresh(claim) and claim["id"] != self.me["id"] else None})
            await self.upload_db(d)
            self.note = "работаю"
            return

        # --- я в резерве ---
        if other_active:
            if self.outranks(active):   # я главнее — прошу управление
                if not (self.fresh(claim) and claim["id"] == self.me["id"]):
                    log(f"я важнее, чем «{active['host']}» — прошу управление")
                await d.write_heartbeat({**hb, "claim": self.my_record()})
                self.note = f"забираю управление у «{active['host']}»"
            else:
                self.note = f"в резерве: работает «{active['host']}»"
            return
        released_to = hb.get("released_to")
        if released_to and released_to != self.me["id"] and time.time() - hb.get("released_ts", 0) < 45:
            self.note = "жду, пока заберёт другой ПК"
            return
        await self.become_active(d)

    async def become_active(self, d: sync.Discord):
        log("становлюсь главным")
        await d.write_heartbeat({"active": self.my_record(), "claim": None})
        await asyncio.sleep(5)       # защита от гонки: вдруг другой ПК стартовал в ту же секунду
        hb = await d.read_heartbeat()
        active = hb.get("active")
        if self.fresh(active) and active["id"] != self.me["id"] and not self.outranks(active):
            log("другой ПК успел раньше — остаюсь в резерве")
            return
        await self.download_db(d)
        self.state = "active"
        self.start_bot()
        await self.upload_db(d, force=True)

    async def release(self, d: sync.Discord, to: str):
        self.stop_bot()
        await self.upload_db(d, force=True)
        await d.write_heartbeat({"active": None, "claim": None, "released_to": to, "released_ts": time.time()})
        self.state = "standby"
        self.note = "передал управление"

    # ---------- панель управления ----------
    def write_status(self):
        active = self.hb.get("active") or {}
        data = {"ts": time.time(), "state": self.state, "me": self.me, "note": self.note,
                "version": sync.local_version(), "bot_running": bool(self.bot and self.bot.poll() is None),
                "bot_started": self.started_at if self.state == "active" else 0,
                "active_host": active.get("host"), "active_ts": active.get("ts"),
                "last_db_upload": self.last_db_upload, "pid": os.getpid()}
        tmp = STATUS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, STATUS)

    async def handle_command(self, d: sync.Discord | None) -> bool:
        """d = None — режим «один ПК» (без синхронизации)."""
        if not os.path.exists(COMMAND):
            return False
        cmd = open(COMMAND, encoding="utf-8").read().strip()
        os.remove(COMMAND)
        log(f"команда из панели: {cmd}")
        if cmd == "restart_bot" and self.state == "active":
            self.stop_bot()
            self.start_bot()
        elif cmd == "backup" and self.state == "active":
            if d:
                await self.upload_db(d, force=True)
            else:
                self.local_backup(force=True)
        elif cmd == "check_update":
            self.last_code_check = 0
        elif cmd == "stop":
            if self.state == "active" and d:
                await self.release(d, "")
            self.stop_bot()
            return True
        return False

    async def run_solo(self):
        """Один ПК: держим бота запущенным, без пульса и снимков в Discord."""
        log(f"диспетчер запущен (один ПК, синхронизация выключена), версия {sync.local_version()}")
        self.state, self.note = "active", "работаю (один ПК)"
        while True:
            if await self.handle_command(None):
                self.write_status()
                log("остановлен из панели")
                sys.exit(EXIT_STOP)
            self.local_watchdog()
            try:
                self.local_backup()
            except Exception:
                log("ошибка копии базы: " + traceback.format_exc(limit=2).replace("\n", " | "))
            self.write_status()
            for _ in range(TICK):
                await asyncio.sleep(1)
                if os.path.exists(COMMAND):
                    break

    async def run(self):
        if not (sync.SYNC_CHANNEL_ID and sync.SYNC_HEARTBEAT_ID):
            return await self.run_solo()
        log(f"диспетчер запущен: ПК «{self.me['name']}», приоритет {self.me['priority']}, "
            f"версия {sync.local_version()}")
        async with sync.Discord() as d:
            while True:
                try:
                    if await self.handle_command(d):
                        self.write_status()
                        log("остановлен из панели")
                        sys.exit(EXIT_STOP)
                    await self.check_code(d)
                    await self.tick(d)
                except SystemExit:
                    raise
                except Exception as e:  # нет интернета и т.п. — бот продолжает работать, пробуем снова
                    self.note = f"нет связи с Discord: {e}"[:200]
                    log("ошибка: " + traceback.format_exc(limit=2).replace("\n", " | "))
                    self.local_watchdog()  # сторож работает и без интернета
                self.write_status()
                for _ in range(TICK):
                    await asyncio.sleep(1)
                    if os.path.exists(COMMAND):
                        break


def single_instance():
    """Второй диспетчер на этом же ПК (два ярлыка автозапуска и т.п.) сразу выходит."""
    try:
        import msvcrt
    except ImportError:
        return None
    f = open(os.path.join(sync.RUNTIME, "supervisor.lock"), "w")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        log("диспетчер уже запущен на этом ПК — выхожу")
        sys.exit(EXIT_STOP)
    return f


if __name__ == "__main__":
    if not sync.TOKEN:
        log("нет DISCORD_TOKEN в .env — открой Мастер настройки (configure.pyw)")
        sys.exit(EXIT_STOP)
    lock = single_instance()
    sv = Supervisor()
    try:
        asyncio.run(sv.run())
    finally:
        sv.stop_bot()
