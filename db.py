"""لایه دیتابیس (SQLite، async)"""
import time
from typing import Optional

import aiosqlite

DEFAULT_SETTINGS = {
    "enabled": "1",            # ربات روشن/خاموش
    "confirm": "1",            # ارسال رسید به کاربر
    "rate_limit": "10",        # حداکثر پیام در دقیقه برای هر کاربر (0 = نامحدود)
    "force_channel": "",       # کانال جوین اجباری
    "force_link": "",
    "welcome": (
        "سلام {name} 👋\n\n"
        "به ربات پیام‌رسان خوش اومدی ✨\n"
        "هر پیامی داری همین‌جا بفرست؛ مستقیم به دست مدیر می‌رسه "
        "و جوابت رو همین‌جا می‌گیری."
    ),
    "sent_text": "✅ پیامت ارسال شد. به‌زودی جواب می‌گیری.",
    "off_text": "🔧 ربات موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کن.",
    "inline_text": "📩 برای ارسال پیام به من، روی دکمه‌ی زیر بزن و پیامت رو توی ربات بفرست.",
    "biz_enabled": "1",       # پاسخ خودکار در حالت Business (پیوی اکانت شخصی)
    "biz_text": (
        "سلام 👋 پیامت رسید.\n"
        "به‌زودی جواب می‌دم. اگه ضروریه همین‌جا بنویس."
    ),
}


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def init(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                first_name TEXT, last_name TEXT, username TEXT,
                joined_at INTEGER, last_seen INTEGER,
                banned INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                msg_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS msgmap(
                admin_id INTEGER, admin_msg_id INTEGER,
                user_id INTEGER, user_msg_id INTEGER,
                PRIMARY KEY(admin_id, admin_msg_id)
            );
            CREATE TABLE IF NOT EXISTS log(
                ts INTEGER, uid INTEGER, dir TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_log_ts ON log(ts);
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY, value TEXT
            );
            """
        )
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    # ---------- users ----------
    async def upsert_user(self, u) -> bool:
        """کاربر را ثبت/به‌روز می‌کند. اگر جدید بود True برمی‌گرداند."""
        now = int(time.time())
        cur = await self.conn.execute("SELECT id FROM users WHERE id=?", (u.id,))
        exists = await cur.fetchone()
        if exists:
            await self.conn.execute(
                "UPDATE users SET first_name=?, last_name=?, username=?, last_seen=?, blocked=0 WHERE id=?",
                (u.first_name, u.last_name, u.username, now, u.id),
            )
        else:
            await self.conn.execute(
                "INSERT INTO users(id,first_name,last_name,username,joined_at,last_seen) VALUES(?,?,?,?,?,?)",
                (u.id, u.first_name, u.last_name, u.username, now, now),
            )
        await self.conn.commit()
        return not exists

    async def get_user(self, uid: int):
        cur = await self.conn.execute("SELECT * FROM users WHERE id=?", (uid,))
        return await cur.fetchone()

    async def set_banned(self, uid: int, banned: bool):
        await self.conn.execute("UPDATE users SET banned=? WHERE id=?", (int(banned), uid))
        await self.conn.commit()

    async def set_blocked(self, uid: int, blocked: bool = True):
        await self.conn.execute("UPDATE users SET blocked=? WHERE id=?", (int(blocked), uid))
        await self.conn.commit()

    async def inc_msg(self, uid: int):
        await self.conn.execute("UPDATE users SET msg_count=msg_count+1 WHERE id=?", (uid,))
        await self.conn.commit()

    async def list_users(self, page: int, per: int = 8, banned_only: bool = False):
        where = "WHERE banned=1" if banned_only else ""
        cur = await self.conn.execute(f"SELECT COUNT(*) c FROM users {where}")
        total = (await cur.fetchone())["c"]
        cur = await self.conn.execute(
            f"SELECT * FROM users {where} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (per, page * per),
        )
        return await cur.fetchall(), total

    async def search_users(self, q: str, limit: int = 10):
        q = q.strip().lstrip("@")
        if q.isdigit():
            cur = await self.conn.execute("SELECT * FROM users WHERE id=?", (int(q),))
        else:
            like = f"%{q}%"
            cur = await self.conn.execute(
                "SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? OR last_name LIKE ? LIMIT ?",
                (like, like, like, limit),
            )
        return await cur.fetchall()

    async def broadcast_ids(self):
        cur = await self.conn.execute("SELECT id FROM users WHERE banned=0 AND blocked=0")
        return [r["id"] for r in await cur.fetchall()]

    # ---------- message map ----------
    async def map_msg(self, admin_id, admin_msg_id, user_id, user_msg_id):
        await self.conn.execute(
            "INSERT OR REPLACE INTO msgmap VALUES(?,?,?,?)",
            (admin_id, admin_msg_id, user_id, user_msg_id),
        )
        await self.conn.commit()

    async def mapped_user(self, admin_id, admin_msg_id) -> Optional[int]:
        cur = await self.conn.execute(
            "SELECT user_id FROM msgmap WHERE admin_id=? AND admin_msg_id=?",
            (admin_id, admin_msg_id),
        )
        r = await cur.fetchone()
        return r["user_id"] if r else None

    # ---------- log / stats ----------
    async def log(self, uid: int, direction: str):
        await self.conn.execute("INSERT INTO log VALUES(?,?,?)", (int(time.time()), uid, direction))
        await self.conn.commit()

    async def stats(self) -> dict:
        now = int(time.time())
        day = now - 86400

        async def one(sql, *a):
            cur = await self.conn.execute(sql, a)
            return (await cur.fetchone())[0]

        return {
            "users": await one("SELECT COUNT(*) FROM users"),
            "new24": await one("SELECT COUNT(*) FROM users WHERE joined_at>?", day),
            "active24": await one("SELECT COUNT(*) FROM users WHERE last_seen>?", day),
            "banned": await one("SELECT COUNT(*) FROM users WHERE banned=1"),
            "blocked": await one("SELECT COUNT(*) FROM users WHERE blocked=1"),
            "in_total": await one("SELECT COUNT(*) FROM log WHERE dir='in'"),
            "out_total": await one("SELECT COUNT(*) FROM log WHERE dir='out'"),
            "in24": await one("SELECT COUNT(*) FROM log WHERE dir='in' AND ts>?", day),
            "out24": await one("SELECT COUNT(*) FROM log WHERE dir='out' AND ts>?", day),
        }

    # ---------- settings ----------
    async def get(self, key: str) -> str:
        cur = await self.conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = await cur.fetchone()
        return r["value"] if r else DEFAULT_SETTINGS.get(key, "")

    async def set(self, key: str, value: str):
        await self.conn.execute(
            "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.conn.commit()
