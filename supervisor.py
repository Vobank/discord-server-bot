"""Диспетчер бота: запускается вместо bot.py (автозагрузка Windows, systemd, Docker) на КАЖДОМ ПК/сервере.

Работает всегда ровно ОДНА копия бота, компьютеров может быть до 5 (и больше):
  • Каждые 15 сек активная копия пишет «пульс» в #🔧・bot-sync.
  • Запасные следят за пульсом. Пропал (ПК выключили) — бота забирает следующий по очереди:
    priority 1 через 75 сек, 2 — через 95, 3 — через 115… Так они не толкаются.
  • Если включился ПК с более высоким приоритетом (priority в host.json: 1 — главный), он вежливо
    «просит» управление, текущая копия сохраняет базу и отдаёт его — без двойных ответов.
  • Выбор по нагрузке (по умолчанию включён): каждый ПК сообщает, насколько он загружен (процессор, память —
    без учёта самого бота). Если на ПК с ботом начали играть и он загружен, а другой ПК заметно свободнее —
    бот переезжает туда (не чаще раза в 10 минут и не во время музыки). Когда главный пропал — бота
    забирает самый свободный. Без выбора по нагрузке — строго по приоритетам.
  • Режим ПК «только по кнопке» (mode: manual в host.json): этот ПК сам бота не забирает никогда.
  • «📌 Забрать бота сюда» в панели любого ПК закрепляет бота за ним (приоритеты и нагрузка не действуют),
    «↩ Вернуть по приоритету» — снимает закрепление.
  • База bot.db едет вместе с ботом: активная копия раз в 2 минуты кладёт снимок в Discord,
    новая активная копия перед стартом забирает самый свежий.
  • Обновления кода: кто-то нажал «Опубликовать обновление» — все ПК скачают и поставят его сами.
  • Каждый ПК раз в минуту отмечается сообщением «HOST …» — панель и /status показывают все компьютеры.
  • Команды с других ПК («перезапусти бота», «отдай бота мне») приходят сообщениями «CMD …».

Если синхронизация не включена (нет SYNC_CHANNEL_ID в .env) — режим «один ПК»: диспетчер просто держит бота
запущенным (сторож + ежедневные копии базы на диске).

Статус для панели управления — runtime/status.json, команды от панели — runtime/command.txt."""
import asyncio
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
import traceback

import sync

try:  # нагрузка ПК; без psutil выбор по нагрузке просто выключается
    import psutil
except Exception:
    psutil = None

TICK = 15            # сек между проверками
STALE = 75           # пульс старше — копия считается выключенной
TAKEOVER_STEP = 20   # каждый следующий по приоритету ждёт на столько дольше, прежде чем забрать бота
DB_EVERY = 120       # снимок базы не чаще
DB_FORCE = 600       # и обязательно хотя бы раз в 10 минут
CODE_EVERY = 60      # проверка обновлений кода
PRESENCE_EVERY = 60  # отметка «я на связи» (HOST) и список всех ПК
EXIT_STOP = 3        # код выхода «остановлен вручную» (autostart.bat / systemd не перезапускают)
FROZEN_AFTER = 120   # бот столько сек без связи с Discord — перезапуск
ONLINE = 150         # ПК, отметившийся позже, считается на связи
BALANCE_DWELL = 600  # после переезда бот живёт на ПК минимум 10 минут
BUSY_LOAD = 60       # ПК с ботом считается загруженным от 60%…
LOAD_GAP = 25        # …и переезд — только если другой свободнее хотя бы на 25 пунктов

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


def balance_enabled() -> bool:
    """Выбор ПК по нагрузке — настройка multi_pc.balance (Мастер → «Несколько ПК»)."""
    try:
        import config
        return bool(config.S.get("multi_pc", {}).get("balance", True))
    except Exception:
        return True


def restart_self():
    """Перезапуск диспетчера с новым кодом. Windows: выходим, автозапуск (tools/autostart.pyw) запустит заново.
    Linux (VPS, Docker, панель хостинга): заменяем процесс сами — не всякий хостинг перезапускает упавшее."""
    if os.name == "nt":
        sys.exit(0)
    os.execv(sys.executable, [sys.executable, *sys.argv])


class Supervisor:
    def __init__(self):
        self.me = sync.host_info()
        self.state = "standby"           # standby | active
        self.bot: subprocess.Popen | None = None
        self.started_at = 0.0
        self.last_db_upload = 0.0
        self.last_db_mtime = 0.0
        self.last_code_check = 0.0
        self.last_presence = 0.0
        self.hb: dict = {}
        self.hosts: list[dict] = []
        self.pinned = False              # бот закреплён за этим ПК («📌 Забрать бота сюда»)
        self.note = ""
        self.mode = self.me.get("mode", "auto")   # auto — в очереди, manual — только по кнопке
        self.balance = balance_enabled() and psutil is not None
        self.load: int | None = None    # нагрузка ПК без самого бота, %
        self.cpu_ema: float | None = None
        self.ram = 0.0
        self.procs: dict = {}
        self.became_active_at = 0.0
        self.last_balance = 0.0
        if psutil:
            psutil.cpu_percent(interval=None)

    # ---------- нагрузка ----------
    def measure_load(self):
        if not psutil:
            return
        try:
            cpu = psutil.cpu_percent(interval=None)
            bot_cpu = 0.0
            if self.bot and self.bot.poll() is None:  # сам бот (и его ffmpeg) переедет вместе с ним — не считаем
                root = self.procs.get(self.bot.pid) or psutil.Process(self.bot.pid)
                alive = {}
                for proc in [root, *root.children(recursive=True)]:
                    proc = self.procs.get(proc.pid, proc)
                    alive[proc.pid] = proc
                    bot_cpu += proc.cpu_percent(None)
                self.procs = alive
                bot_cpu /= psutil.cpu_count() or 1
            own = max(0.0, cpu - bot_cpu)
            self.cpu_ema = own if self.cpu_ema is None else self.cpu_ema * 0.75 + own * 0.25
            self.ram = psutil.virtual_memory().percent
            self.load = round(self.cpu_ema + max(0.0, self.ram - 85) * 2)  # память важна, только когда почти кончилась
        except Exception:
            pass

    def busy(self) -> bool:
        """Бот сейчас в голосовом (музыка) — не переносим."""
        try:
            return open(os.path.join(sync.RUNTIME, "bot_busy.txt")).read().strip() == "1"
        except OSError:
            return False

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
        failed = sync.apply_code(data)
        if failed:
            log("⚠ не удалось обновить (заняты другой программой): " + ", ".join(failed[:5]))
        sync.set_local_version(new["meta"]["version"])
        if open(req, "rb").read() != old_req:
            log("ставлю новые библиотеки…")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", req], cwd=APP)
        if was_active:  # отдаём пульс себе же, чтобы не было «двоих» во время перезапуска
            await d.write_heartbeat({**self.hb, "active": None, "released_to": self.me["id"], "released_ts": time.time(),
                                     "pinned": self.me["id"] if self.pinned else self.hb.get("pinned")})
        log("🔄 перезапускаю диспетчер с новым кодом")
        restart_self()

    # ---------- все ПК: кто на связи ----------
    def presence_record(self) -> dict:
        return {"id": self.me["id"], "name": self.me["name"], "priority": self.me["priority"],
                "kind": self.me.get("kind", "pc"), "mode": self.mode, "os": platform.system(), "state": self.state,
                "load": self.load, "cpu": round(self.cpu_ema) if self.cpu_ema is not None else None,
                "ram": round(self.ram), "version": sync.local_version(), "ts": time.time()}

    async def presence(self, d: sync.Discord, force=False):
        """Раз в минуту обновляем своё сообщение «HOST …» и читаем, какие ещё ПК на связи."""
        if not force and time.time() - self.last_presence < PRESENCE_EVERY:
            return
        self.last_presence = time.time()
        me = self.presence_record()
        msgs = await d.messages("HOST")
        mine = [m for m in msgs if m["meta"].get("id") == self.me["id"]]
        if mine:
            await d.edit_text(mine[0]["id"], "HOST", me)
            for dup in mine[1:]:
                await d.delete(dup["id"])
        else:
            await d.send_text("HOST", me)
        others = []
        for m in msgs:
            if m["meta"].get("id") == self.me["id"]:
                continue
            if time.time() - m["meta"].get("ts", 0) > 30 * 86400:  # ПК не появлялся месяц — убираем из списка
                await d.delete(m["id"])
            else:
                others.append(m["meta"])
        self.hosts = sorted([me, *others], key=lambda h: (h.get("priority", 99), h.get("id", "")))

    # ---------- команды между ПК ----------
    async def send_remote(self, d: sync.Discord, what: str, **extra):
        await d.send_text("CMD", {"what": what, "by": self.me["name"], "from": self.me["id"], "ts": time.time(), **extra})
        log(f"→ команда другим ПК: {what}")

    async def remote_commands(self, d: sync.Discord) -> bool:
        """Выполняет команды «CMD …» (только активная копия). True — бот отдан другому ПК."""
        cmds = await d.messages("CMD", 50)
        for m in reversed(cmds):  # от старых к новым
            c = m["meta"]
            await d.delete(m["id"])
            if time.time() - c.get("ts", 0) > 300:  # протухшая
                continue
            what = c.get("what")
            log(f"команда от «{c.get('by')}»: {what}")
            if what == "restart_bot":
                self.stop_bot()
                self.start_bot()
            elif what == "backup":
                await self.upload_db(d, force=True)
            elif what == "unpin":
                self.pinned = False
            elif what == "bot_task" and c.get("task"):  # разовое задание боту, он заберёт его за 30 с
                with open(os.path.join(sync.RUNTIME, "bot_task.txt"), "w", encoding="utf-8") as f:
                    f.write(str(c["task"]))
            elif what == "move" and c.get("to") and c["to"] != self.me["id"]:
                log(f"передаю бота ПК «{c.get('by')}» по его просьбе (закреплено за ним)")
                await self.release(d, c["to"], pin=True)
                return True
        return False

    # ---------- выборы «кто главный» ----------
    def fresh(self, item: dict | None) -> bool:
        return bool(item) and time.time() - item.get("ts", 0) < STALE

    def outranks(self, other: dict) -> bool:
        """Я важнее другого? Меньше priority — важнее; при равенстве решает id."""
        return (self.me["priority"], self.me["id"]) < (other.get("priority", 99), other.get("id", ""))

    def my_delay(self) -> float:
        """Сколько ещё ждать после пропажи главного. По нагрузке: самый свободный — первым;
        иначе по очереди приоритетов (+ немного от id при равенстве)."""
        jitter = int(hashlib.md5(self.me["id"].encode()).hexdigest(), 16) % 5
        if self.balance and self.load is not None:
            now = time.time()
            me = (self.load, self.me["priority"], self.me["id"])
            rank = sum(1 for h in self.hosts if h.get("id") != self.me["id"] and now - h.get("ts", 0) < ONLINE
                       and h.get("state") != "active" and h.get("mode", "auto") != "manual" and h.get("load") is not None
                       and (h["load"], h.get("priority", 99), h.get("id", "")) < me)
            return rank * TAKEOVER_STEP + jitter
        return (max(1, self.me["priority"]) - 1) * TAKEOVER_STEP + jitter

    async def balance_check(self, d: sync.Discord) -> bool:
        """Активная копия раз в минуту смотрит, не пора ли переехать на более свободный ПК. True — переехали."""
        now = time.time()
        if self.pinned or now - self.last_balance < 60:
            return False
        self.last_balance = now
        cands = [h for h in self.hosts if h.get("id") != self.me["id"] and now - h.get("ts", 0) < ONLINE
                 and h.get("state") == "standby" and h.get("mode", "auto") != "manual"
                 and h.get("version") == sync.local_version()]
        if not cands:
            return False
        best = min(cands, key=lambda h: (h.get("load") if h.get("load") is not None else 50, h.get("priority", 99),
                                         h.get("id", "")))
        if self.mode == "manual":  # «только по кнопке», а закрепление сняли — отдаём бота
            log(f"этот ПК — «только по кнопке», бот не закреплён — отдаю «{best['name']}»")
            await self.release(d, best["id"])
            return True
        if not self.balance or self.load is None or best.get("load") is None or self.busy():
            return False
        if now - self.became_active_at < BALANCE_DWELL:
            return False
        if self.load >= BUSY_LOAD and best["load"] + LOAD_GAP <= self.load:
            log(f"этот ПК загружен ({self.load}%), «{best['name']}» свободнее ({best['load']}%) — переношу бота")
            await self.release(d, best["id"])
            return True
        return False

    def my_record(self) -> dict:
        return {"id": self.me["id"], "host": self.me["name"], "priority": self.me["priority"], "ts": time.time(),
                "version": sync.local_version(), "started": self.started_at}

    async def tick(self, d: sync.Discord):
        hb = self.hb = await d.read_heartbeat()
        active, claim = hb.get("active"), hb.get("claim")
        other_active = self.fresh(active) and active["id"] != self.me["id"]

        if self.state == "active":
            if await self.remote_commands(d):
                return
            if other_active and not self.outranks(active):        # двое сразу — уступает менее важный
                log(f"другая копия ({active['host']}) важнее — ухожу в резерв")
                return await self.release(d, active["id"])
            if not self.pinned and self.fresh(claim) and claim["id"] != self.me["id"] and not self.outranks(claim):
                log(f"ПК «{claim['host']}» просит управление — передаю")
                return await self.release(d, claim["id"])
            self.local_watchdog()
            await d.write_heartbeat({"active": self.my_record(),
                                     "claim": claim if self.fresh(claim) and claim["id"] != self.me["id"] else None,
                                     "pinned": self.me["id"] if self.pinned else None})
            await self.upload_db(d)
            self.note = "работаю" + (" (закреплён за этим ПК)" if self.pinned else "")
            await self.balance_check(d)
            return

        # --- я в резерве ---
        if other_active:
            if hb.get("pinned") == active["id"]:
                self.note = f"в резерве: бот закреплён за «{active['host']}»"
            elif self.outranks(active) and not self.balance and self.mode != "manual":
                # я главнее — прошу управление (если не просит кто-то ещё главнее). По нагрузке — не просим:
                # там бот сам переезжает на свободный ПК
                if self.fresh(claim) and claim["id"] != self.me["id"] and not self.outranks(claim):
                    self.note = f"в резерве: управление просит «{claim['host']}»"
                    return
                if not (self.fresh(claim) and claim["id"] == self.me["id"]):
                    log(f"я важнее, чем «{active['host']}» — прошу управление")
                await d.write_heartbeat({**hb, "claim": self.my_record()})
                self.note = f"забираю управление у «{active['host']}»"
            else:
                self.note = f"в резерве: работает «{active['host']}»"
            return
        now = time.time()
        released_to, released_ts = hb.get("released_to"), hb.get("released_ts", 0)
        if released_to and released_to != self.me["id"] and now - released_ts < 45:
            self.note = "жду, пока заберёт другой ПК"
            return
        if self.mode == "manual" and released_to != self.me["id"]:
            self.note = "только по кнопке: бот здесь, когда нажмёшь «📌 Забрать бота сюда»"
            return
        # главный пропал или остановлен — забираем по очереди (по нагрузке или приоритетам), чтобы не толкаться
        gone_since = max((active or {}).get("ts", 0), released_ts if released_to != self.me["id"] else 0)
        wait = (STALE if active else 0) + self.my_delay() - (now - gone_since) if gone_since else 0
        mine_before = bool(active) and active["id"] == self.me["id"]  # это я и был главным (просто перезапустился)
        if released_to != self.me["id"] and not mine_before and wait > 0:
            self.note = f"главный не отвечает — моя очередь через {int(wait)} сек"
            return
        await self.become_active(d)

    async def become_active(self, d: sync.Discord):
        log("становлюсь главным")
        pinned_here = self.hb.get("pinned") == self.me["id"]
        await d.write_heartbeat({"active": self.my_record(), "claim": None,
                                 "pinned": self.me["id"] if pinned_here else None})
        await asyncio.sleep(5)       # защита от гонки: вдруг другой ПК стартовал в ту же секунду
        hb = await d.read_heartbeat()
        active = hb.get("active")
        if self.fresh(active) and active["id"] != self.me["id"] and not self.outranks(active):
            log("другой ПК успел раньше — остаюсь в резерве")
            return
        self.pinned = pinned_here
        self.became_active_at = time.time()
        await self.download_db(d)
        self.state = "active"
        self.start_bot()
        await self.upload_db(d, force=True)
        await self.presence(d, force=True)

    async def release(self, d: sync.Discord, to: str, pin: bool = False):
        self.stop_bot()
        await self.upload_db(d, force=True)
        await d.write_heartbeat({"active": None, "claim": None, "released_to": to, "released_ts": time.time(),
                                 "pinned": to if pin else None})
        self.state = "standby"
        self.pinned = False
        self.note = "передал управление"
        await self.presence(d, force=True)

    # ---------- панель управления ----------
    def write_status(self, solo: bool = False):
        active = self.hb.get("active") or {}
        data = {"ts": time.time(), "state": self.state, "me": self.me, "note": self.note, "solo": solo,
                "version": sync.local_version(), "bot_running": bool(self.bot and self.bot.poll() is None),
                "bot_started": self.started_at if self.state == "active" else 0,
                "active_host": active.get("host"), "active_ts": active.get("ts"),
                "pinned": self.hb.get("pinned"), "hosts": self.hosts, "mode": self.mode, "balance": self.balance,
                "load": self.load,
                "last_db_upload": self.last_db_upload, "pid": os.getpid()}
        tmp = STATUS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, STATUS)

    async def handle_command(self, d: sync.Discord | None) -> bool:
        """Команда из панели этого ПК. d = None — режим «один ПК». True — остановиться."""
        if not os.path.exists(COMMAND):
            return False
        cmd = open(COMMAND, encoding="utf-8").read().strip()
        os.remove(COMMAND)
        log(f"команда из панели: {cmd}")
        active = self.state == "active"
        if cmd == "restart_bot":
            if active:
                self.stop_bot()
                self.start_bot()
            elif d:
                await self.send_remote(d, "restart_bot")
        elif cmd == "backup":
            if active and d:
                await self.upload_db(d, force=True)
            elif active:
                self.local_backup(force=True)
            elif d:
                await self.send_remote(d, "backup")
        elif cmd == "take_here" and d:
            if active:
                self.pinned = True
            else:
                await self.send_remote(d, "move", to=self.me["id"])
        elif cmd == "unpin" and d:
            if active:
                self.pinned = False
            else:
                await self.send_remote(d, "unpin")
        elif cmd == "check_update":
            self.last_code_check = 0
        elif cmd == "stop":
            if active and d:
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
                self.write_status(solo=True)
                log("остановлен из панели")
                sys.exit(EXIT_STOP)
            self.local_watchdog()
            try:
                self.local_backup()
            except Exception:
                log("ошибка копии базы: " + traceback.format_exc(limit=2).replace("\n", " | "))
            self.write_status(solo=True)
            for _ in range(TICK):
                await asyncio.sleep(1)
                if os.path.exists(COMMAND):
                    break

    async def run(self):
        if not (sync.SYNC_CHANNEL_ID and sync.SYNC_HEARTBEAT_ID):
            return await self.run_solo()
        log(f"диспетчер запущен: «{self.me['name']}» ({self.me.get('kind', 'pc')}, {platform.system()}), "
            f"приоритет {self.me['priority']}, версия {sync.local_version()}")
        async with sync.Discord() as d:
            while True:
                try:
                    if await self.handle_command(d):
                        self.write_status()
                        log("остановлен из панели")
                        sys.exit(EXIT_STOP)
                    self.measure_load()
                    await self.check_code(d)
                    await self.tick(d)
                    await self.presence(d)
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
    f = open(os.path.join(sync.RUNTIME, "supervisor.lock"), "w")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("диспетчер уже запущен на этом ПК — выхожу")
        sys.exit(EXIT_STOP)
    return f


if __name__ == "__main__":
    if not sync.TOKEN:
        log("нет DISCORD_TOKEN в .env — откройте панель управления (Запуск.bat) или впишите ключ в .env")
        sys.exit(EXIT_STOP)
    lock = single_instance()
    sv = Supervisor()
    try:
        asyncio.run(sv.run())
    finally:
        sv.stop_bot()
