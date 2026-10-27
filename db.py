import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS birthdays (
    guild_id INTEGER, user_id INTEGER,
    day INTEGER, month INTEGER, year INTEGER,
    last_congrats INTEGER,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS levels (
    guild_id INTEGER, user_id INTEGER,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS feature_roles (
    guild_id INTEGER, feature TEXT, role_id INTEGER,
    PRIMARY KEY (guild_id, feature, role_id)
);
CREATE TABLE IF NOT EXISTS punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, user_id INTEGER, moderator_id INTEGER,
    action TEXT, reason TEXT, dept TEXT, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS stats (
    guild_id INTEGER, user_id INTEGER, key TEXT, value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, key)
);
CREATE TABLE IF NOT EXISTS pending_roles (
    guild_id INTEGER, user_id INTEGER, role_id INTEGER,
    PRIMARY KEY (guild_id, user_id, role_id)
);
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER, key TEXT, value TEXT,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS cinema_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, title TEXT, start_ts INTEGER, link TEXT, description TEXT,
    morning_sent INTEGER DEFAULT 0, reminders_sent TEXT DEFAULT '', started INTEGER DEFAULT 0,
    event_id INTEGER
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, user_id INTEGER, kind TEXT, answers TEXT,
    status TEXT DEFAULT 'new', reviewer_id INTEGER, message_id INTEGER,
    created_at INTEGER, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS films (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, title TEXT, norm TEXT, count INTEGER DEFAULT 1, suggested_by TEXT DEFAULT '',
    status TEXT DEFAULT 'wish', watched_before INTEGER DEFAULT 0, watched_at INTEGER, created_at INTEGER,
    UNIQUE (guild_id, norm)
);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, user_id INTEGER, title TEXT, text TEXT, status TEXT DEFAULT 'new',
    message_id INTEGER, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, user_id INTEGER, channel_id INTEGER, text TEXT, due INTEGER
);
CREATE TABLE IF NOT EXISTS starboard (
    guild_id INTEGER, message_id INTEGER PRIMARY KEY, board_message_id INTEGER
);
CREATE TABLE IF NOT EXISTS voice_creators (
    channel_id INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS temp_voice (
    channel_id INTEGER PRIMARY KEY,
    owner_id INTEGER
);
CREATE TABLE IF NOT EXISTS voice_waiting (
    guild_id INTEGER, user_id INTEGER, channel_id INTEGER, msg_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS song_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, title TEXT, url TEXT, duration INTEGER, thumbnail TEXT, author TEXT,
    added_by INTEGER, created_at INTEGER
);
"""

_conn: aiosqlite.Connection | None = None


async def init(path: str = "bot.db"):
    global _conn
    _conn = await aiosqlite.connect(path)
    await _conn.executescript(SCHEMA)
    # миграции старых баз
    cols = [r[1] for r in await (await _conn.execute("PRAGMA table_info(birthdays)")).fetchall()]
    if "public" not in cols:
        await _conn.execute("ALTER TABLE birthdays ADD COLUMN public INTEGER DEFAULT 1")
    cols = [r[1] for r in await (await _conn.execute("PRAGMA table_info(films)")).fetchall()]
    if "genre" not in cols:
        await _conn.execute("ALTER TABLE films ADD COLUMN genre TEXT DEFAULT 'other'")
    for col, kind in (("genres", "TEXT"), ("year", "TEXT"), ("country", "TEXT"), ("duration", "TEXT"),
                      ("description", "TEXT"), ("poster", "BLOB"), ("card_msg", "INTEGER"), ("author_id", "INTEGER"),
                      ("episodes_total", "INTEGER"), ("episodes_watched", "INTEGER DEFAULT 0")):
        if col not in cols:  # карточки фильмов
            await _conn.execute(f"ALTER TABLE films ADD COLUMN {col} {kind}")
    cols = [r[1] for r in await (await _conn.execute("PRAGMA table_info(cinema_sessions)")).fetchall()]
    if "created_ts" not in cols:
        await _conn.execute("ALTER TABLE cinema_sessions ADD COLUMN created_ts INTEGER DEFAULT 0")
    await _conn.commit()


async def get_setting(guild_id: int, key: str, default: str | None = None) -> str | None:
    row = await fetchone("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
    return row[0] if row else default


async def set_setting(guild_id: int, key: str, value: str):
    await execute("INSERT INTO settings (guild_id, key, value) VALUES (?,?,?) "
                  "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value", (guild_id, key, value))


async def execute(sql: str, params=()):
    await _conn.execute(sql, params)
    await _conn.commit()


async def fetchone(sql: str, params=()):
    async with _conn.execute(sql, params) as cur:
        return await cur.fetchone()


async def fetchall(sql: str, params=()):
    async with _conn.execute(sql, params) as cur:
        return await cur.fetchall()
