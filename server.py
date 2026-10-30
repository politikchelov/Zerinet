"""Локальный сервер ZERINET: сайт, прокси к AniLibria/Kodik, аккаунты, чат и «Критика».
Запуск:   py server.py        (потом открой http://localhost:8080)
Админ:    py server.py admin НИК     — сделать пользователя админом (он должен быть зарегистрирован)
          py server.py unadmin НИК   — забрать админку
          py server.py users         — список зарегистрированных
Ещё способ: впиши ник в файл admins.txt рядом с server.py (по одному в строке) — он станет админом.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Социальный backend встроен ниже — server.py теперь автономный.



# ================= ВСТРОЕННЫЙ СОЦИАЛЬНЫЙ BACKEND (из social.py) =================
"""ZERINET: аккаунты, профили, друзья, общий чат, «Критика» под аниме и админ-команды.
Только стандартная библиотека Python. Данные лежат в папке data/ (SQLite + аватарки).
"""
import base64
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))


def pick_data_dir():
    """Папка для базы и аватарок: рядом с сайтом, а если туда нельзя писать (Windows: «Отказано в доступе») —
    в домашней папке пользователя."""
    candidates = [
        os.environ.get("ZERINET_DATA"),
        os.path.join(ROOT, "data"),
        os.path.join(os.path.expanduser("~"), "zerinet-data"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            os.makedirs(os.path.join(path, "avatars"), exist_ok=True)
            probe = os.path.join(path, ".write_test")
            with open(probe, "w") as file:
                file.write("ok")
            os.remove(probe)
            return path
        except OSError:
            continue
    raise SystemExit("Не удалось создать папку для данных. Задай её сам: set ZERINET_DATA=C:\\zerinet-data")


DATA_DIR = pick_data_dir()
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")
DB_PATH = os.path.join(DATA_DIR, "zerinet.db")

# ранги дают рамку вокруг аватарки (стили рамок — в social.js); выдают их только админы
RANKS = {
    "novice": "Новичок",
    "viewer": "Зритель",
    "expert": "Знаток",
    "legend": "Легенда",
    "moderator": "Модератор",
    "admin": "Админ",
}
SESSION_DAYS = 30
MAX_AVATAR_BYTES = 250_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-А-Яа-яЁё]{3,20}$")
ALIAS_RE = re.compile(r"^[\w.\-]{1,120}$")
AVATAR_RE = re.compile(r"^[0-9]+-[0-9a-f]{8}\.jpg$")

_lock = threading.RLock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.execute("PRAGMA journal_mode=WAL")
_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        salt BLOB NOT NULL, hash BLOB NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        rank TEXT NOT NULL DEFAULT 'novice',
        points INTEGER NOT NULL DEFAULT 0,
        bio TEXT NOT NULL DEFAULT '',
        avatar TEXT,
        created INTEGER NOT NULL,
        last_seen INTEGER NOT NULL DEFAULT 0,
        banned INTEGER NOT NULL DEFAULT 0,
        ban_reason TEXT NOT NULL DEFAULT '',
        muted_until INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sessions(
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS friends(
        user_id INTEGER NOT NULL, other_id INTEGER NOT NULL,
        status TEXT NOT NULL, created INTEGER NOT NULL,
        PRIMARY KEY(user_id, other_id)
    );
    CREATE TABLE IF NOT EXISTS chat(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, kind TEXT NOT NULL DEFAULT 'msg',
        text TEXT NOT NULL, created INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alias TEXT NOT NULL, user_id INTEGER NOT NULL,
        text TEXT NOT NULL, created INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS comments_alias ON comments(alias, id);
    CREATE TABLE IF NOT EXISTS admin_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL, text TEXT NOT NULL, created INTEGER NOT NULL
    );
    """
)
_db.commit()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now():
    return int(time.time())


# ---------------------------------------------------------------- утилиты
_rate = {}


def rate_limit(key, limit, window):
    t = time.time()
    if len(_rate) > 5000:
        _rate.clear()
    hits = [x for x in _rate.get(key, []) if t - x < window]
    if len(hits) >= limit:
        raise ApiError(429, "Слишком часто, подожди немного")
    hits.append(t)
    _rate[key] = hits


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def clean_text(value, limit):
    text = str(value or "").replace("\r", "")
    text = "".join(ch for ch in text if ch == "\n" or ch >= " ")
    return text.strip()[:limit]


def avatar_url(row):
    return "/avatars/" + row["avatar"] if row["avatar"] else ""


def pub(row):
    return {
        "id": row["id"], "name": row["name"], "rank": row["rank"],
        "rank_name": RANKS.get(row["rank"], row["rank"]), "role": row["role"],
        "avatar": avatar_url(row),
    }


ADMINS_FILE = os.path.join(ROOT, "admins.txt")
_admins = {"mtime": None, "names": set()}


def admin_names():
    """Ники из файла admins.txt (по одному в строке) автоматически становятся админами."""
    try:
        mtime = os.path.getmtime(ADMINS_FILE)
    except OSError:
        return set()
    if _admins["mtime"] != mtime:
        try:
            with open(ADMINS_FILE, encoding="utf-8-sig") as file:
                text = file.read()
        except OSError:
            return set()
        names = {line.strip().lower() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")}
        _admins.update(mtime=mtime, names=names)
    return _admins["names"]


def find_user(name):
    return _db.execute("SELECT * FROM users WHERE name = ? COLLATE NOCASE", (str(name or "").strip(),)).fetchone()


def require_user(user):
    if user is None:
        raise ApiError(401, "Нужно войти в аккаунт")
    return user


def require_admin(user):
    if require_user(user)["role"] != "admin":
        raise ApiError(403, "Только для админов")
    return user


def check_can_post(user):
    if user["muted_until"] > now():
        minutes = (user["muted_until"] - now()) // 60 + 1
        raise ApiError(403, "Тебя заглушили ещё примерно на %d мин." % minutes)


def log_admin(admin, text):
    _db.execute("INSERT INTO admin_log(admin_id, text, created) VALUES (?,?,?)", (admin["id"], text, now()))


# ---------------------------------------------------------------- сессии
def user_from_cookie(cookie_header):
    if not cookie_header:
        return None
    try:
        cookie = http.cookies.SimpleCookie(cookie_header)
    except http.cookies.CookieError:
        return None
    if "zsid" not in cookie:
        return None
    row = _db.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires > ?",
        (sha(cookie["zsid"].value), now()),
    ).fetchone()
    if row is None or row["banned"]:
        return None
    if row["role"] != "admin" and row["name"].lower() in admin_names():
        _db.execute("UPDATE users SET role = 'admin', rank = 'admin' WHERE id = ?", (row["id"],))
        _db.commit()
        row = _db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    if now() - row["last_seen"] > 20:
        _db.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now(), row["id"]))
        _db.commit()
    return row


def start_session(user_id):
    token = secrets.token_urlsafe(32)
    _db.execute("INSERT INTO sessions(token, user_id, expires) VALUES (?,?,?)", (sha(token), user_id, now() + SESSION_DAYS * 86400))
    _db.execute("DELETE FROM sessions WHERE expires < ?", (now(),))
    _db.commit()
    return token


def cookie_header(token, secure, max_age=SESSION_DAYS * 86400):
    parts = ["zsid=%s" % token, "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=%d" % max_age]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


# ---------------------------------------------------------------- аккаунты
def self_info(user):
    if user is None:
        return None
    info = pub(user)
    info.update({"points": user["points"], "bio": user["bio"]})
    return info


def api_me(ctx):
    requests = 0
    if ctx.user:
        requests = _db.execute("SELECT COUNT(*) FROM friends WHERE other_id = ? AND status = 'pending'", (ctx.user["id"],)).fetchone()[0]
    return {"enabled": True, "user": self_info(ctx.user), "requests": requests,
            "ranks": [{"key": k, "name": v} for k, v in RANKS.items()]}


def api_register(ctx):
    rate_limit("reg:" + ctx.ip, 5, 3600)
    name = str(ctx.data.get("username", "")).strip()
    password = str(ctx.data.get("password", ""))
    if not USERNAME_RE.match(name):
        raise ApiError(400, "Ник: 3–20 символов, буквы, цифры, _ и -")
    if len(password) < 6 or len(password) > 100:
        raise ApiError(400, "Пароль: от 6 символов")
    if find_user(name):
        raise ApiError(409, "Этот ник уже занят")
    salt = secrets.token_bytes(16)
    cur = _db.execute("INSERT INTO users(name, salt, hash, created, last_seen) VALUES (?,?,?,?,?)",
                      (name, salt, hash_password(password, salt), now(), now()))
    _db.commit()
    ctx.set_cookie = start_session(cur.lastrowid)
    return {"ok": True, "user": self_info(_db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())}


def api_login(ctx):
    rate_limit("login:" + ctx.ip, 10, 600)
    row = find_user(ctx.data.get("username", ""))
    password = str(ctx.data.get("password", ""))
    ok = row is not None and hmac.compare_digest(hash_password(password, row["salt"]), row["hash"])
    if not ok:
        raise ApiError(401, "Неверный ник или пароль")
    if row["banned"]:
        raise ApiError(403, "Аккаунт заблокирован. Причина: %s" % (row["ban_reason"] or "не указана"))
    ctx.set_cookie = start_session(row["id"])
    return {"ok": True, "user": self_info(row)}


def api_logout(ctx):
    if ctx.cookie_token:
        _db.execute("DELETE FROM sessions WHERE token = ?", (sha(ctx.cookie_token),))
        _db.commit()
    ctx.set_cookie = ""
    return {"ok": True}


# ---------------------------------------------------------------- профиль
def relation(me, other):
    if me is None:
        return "none"
    if me["id"] == other["id"]:
        return "self"
    row = _db.execute(
        "SELECT * FROM friends WHERE (user_id=? AND other_id=?) OR (user_id=? AND other_id=?)",
        (me["id"], other["id"], other["id"], me["id"]),
    ).fetchone()
    if row is None:
        return "none"
    if row["status"] == "accepted":
        return "friends"
    return "sent" if row["user_id"] == me["id"] else "received"


def friends_of(user_id, limit=60):
    return _db.execute(
        """SELECT u.* FROM friends f JOIN users u ON u.id = CASE WHEN f.user_id = ? THEN f.other_id ELSE f.user_id END
           WHERE (f.user_id = ? OR f.other_id = ?) AND f.status = 'accepted' ORDER BY u.last_seen DESC LIMIT ?""",
        (user_id, user_id, user_id, limit),
    ).fetchall()


def api_user(ctx):
    row = find_user(ctx.query.get("name", ""))
    if row is None:
        raise ApiError(404, "Пользователь не найден")
    info = pub(row)
    info.update({
        "points": row["points"], "bio": row["bio"], "created": row["created"],
        "online": now() - row["last_seen"] < 120, "banned": bool(row["banned"]),
        "relation": relation(ctx.user, row),
        "friends": [pub(f) for f in friends_of(row["id"])],
        "comments": _db.execute("SELECT COUNT(*) FROM comments WHERE user_id = ? AND deleted = 0", (row["id"],)).fetchone()[0],
    })
    return info


def api_profile(ctx):
    user = require_user(ctx.user)
    bio = clean_text(ctx.data.get("bio", ""), 200)
    _db.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user["id"]))
    _db.commit()
    return {"ok": True, "bio": bio}


def remove_avatar_file(name):
    if name and AVATAR_RE.match(name):
        try:
            os.remove(os.path.join(AVATAR_DIR, name))
        except OSError:
            pass


def api_avatar(ctx):
    user = require_user(ctx.user)
    rate_limit("avatar:%d" % user["id"], 6, 600)
    data = ctx.data.get("data")
    new_name = None
    if data:
        match = re.match(r"^data:image/jpeg;base64,([A-Za-z0-9+/=]+)$", str(data))
        if not match:
            raise ApiError(400, "Нужна картинка JPEG")
        try:
            raw = base64.b64decode(match.group(1), validate=True)
        except ValueError:
            raise ApiError(400, "Битая картинка")
        if len(raw) > MAX_AVATAR_BYTES:
            raise ApiError(413, "Картинка слишком большая")
        if raw[:3] != b"\xff\xd8\xff":
            raise ApiError(400, "Это не JPEG")
        new_name = "%d-%s.jpg" % (user["id"], secrets.token_hex(4))
        with open(os.path.join(AVATAR_DIR, new_name), "wb") as file:
            file.write(raw)
    remove_avatar_file(user["avatar"])
    _db.execute("UPDATE users SET avatar = ? WHERE id = ?", (new_name, user["id"]))
    _db.commit()
    return {"ok": True, "avatar": "/avatars/" + new_name if new_name else ""}


def read_avatar(name):
    if not AVATAR_RE.match(name or ""):
        return None
    try:
        with open(os.path.join(AVATAR_DIR, name), "rb") as file:
            return file.read()
    except OSError:
        return None


# ---------------------------------------------------------------- друзья
def api_friends(ctx):
    user = require_user(ctx.user)
    incoming = _db.execute("SELECT u.* FROM friends f JOIN users u ON u.id = f.user_id WHERE f.other_id = ? AND f.status = 'pending'", (user["id"],)).fetchall()
    outgoing = _db.execute("SELECT u.* FROM friends f JOIN users u ON u.id = f.other_id WHERE f.user_id = ? AND f.status = 'pending'", (user["id"],)).fetchall()
    friends = []
    for row in friends_of(user["id"], 200):
        item = pub(row)
        item["online"] = now() - row["last_seen"] < 120
        friends.append(item)
    return {"friends": friends, "incoming": [pub(r) for r in incoming], "outgoing": [pub(r) for r in outgoing]}


def api_friend(ctx):
    user = require_user(ctx.user)
    rate_limit("friend:%d" % user["id"], 30, 3600)
    other = find_user(ctx.data.get("name", ""))
    action = ctx.data.get("action")
    if other is None or other["id"] == user["id"]:
        raise ApiError(404, "Пользователь не найден")
    state = relation(user, other)
    if action == "add" and state == "received":
        action = "accept"  # он уже звал нас в друзья — просто принимаем
    if action == "add":
        if state == "friends":
            raise ApiError(409, "Вы уже друзья")
        if state == "sent":
            raise ApiError(409, "Заявка уже отправлена")
        _db.execute("INSERT OR REPLACE INTO friends(user_id, other_id, status, created) VALUES (?,?, 'pending', ?)", (user["id"], other["id"], now()))
    elif action == "accept":
        if state != "received":
            raise ApiError(409, "Нет входящей заявки")
        _db.execute("UPDATE friends SET status = 'accepted' WHERE user_id = ? AND other_id = ? AND status = 'pending'", (other["id"], user["id"]))
    elif action in ("decline", "remove"):
        _db.execute("DELETE FROM friends WHERE (user_id=? AND other_id=?) OR (user_id=? AND other_id=?)", (user["id"], other["id"], other["id"], user["id"]))
    else:
        raise ApiError(400, "Неизвестное действие")
    _db.commit()
    return {"ok": True, "relation": relation(user, other)}


def api_users(ctx):
    query = clean_text(ctx.query.get("q", ""), 20)
    if len(query) < 2:
        return {"users": []}
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = _db.execute("SELECT * FROM users WHERE name LIKE ? ESCAPE '\\' AND banned = 0 ORDER BY last_seen DESC LIMIT 20", (pattern,)).fetchall()
    return {"users": [pub(r) for r in rows]}


def api_top(ctx):
    rows = _db.execute("SELECT * FROM users WHERE banned = 0 ORDER BY points DESC, id ASC LIMIT 20").fetchall()
    return {"users": [dict(pub(r), points=r["points"]) for r in rows]}


# ---------------------------------------------------------------- чат
def chat_rows(limit=80):
    rows = _db.execute(
        "SELECT id, user_id, kind, text, created FROM chat WHERE deleted = 0 ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    authors = {}
    for r in rows:
        if r["user_id"] and r["user_id"] not in authors:
            author = _db.execute("SELECT * FROM users WHERE id = ?", (r["user_id"],)).fetchone()
            authors[r["user_id"]] = pub(author) if author else None
    return [
        {"id": r["id"], "kind": r["kind"], "text": r["text"], "ts": r["created"], "user": authors.get(r["user_id"])}
        for r in reversed(rows)
    ]


def api_chat_get(ctx):
    online = _db.execute("SELECT COUNT(*) FROM users WHERE last_seen > ?", (now() - 120,)).fetchone()[0]
    return {"messages": chat_rows(), "online": online}


def api_chat_post(ctx):
    user = require_user(ctx.user)
    text = clean_text(ctx.data.get("text", ""), 500)
    if not text:
        raise ApiError(400, "Пустое сообщение")
    if text.startswith("/"):
        if user["role"] != "admin":
            raise ApiError(403, "Команды доступны только админам")
        reply = run_command(user, text)
        return {"ok": True, "reply": reply}
    check_can_post(user)
    rate_limit("chat:%d" % user["id"], 4, 6)
    cur = _db.execute("INSERT INTO chat(user_id, text, created) VALUES (?,?,?)", (user["id"], text, now()))
    _db.commit()
    return {"ok": True, "id": cur.lastrowid}


# ---------------------------------------------------------------- команды админов
HELP = [
    "/help — список команд",
    "/ranks — список рангов",
    "/userinfo <ник> — данные игрока",
    "/points <ник> <±число> — добавить или забрать очки",
    "/setpoints <ник> <число> — установить очки",
    "/rank <ник> <ранг> — выдать ранг (рамка у аватарки)",
    "/mute <ник> <минуты> и /unmute <ник>",
    "/ban <ник> [причина] и /unban <ник>",
    "/del <id> — удалить сообщение чата; /delc <id> — удалить комментарий",
    "/clear [число|all] — удалить последние сообщения чата (по умолчанию 50)",
    "/announce <текст> — объявление в чат",
]


def cmd_target(parts, index=1):
    if len(parts) <= index:
        raise ApiError(400, "Не указан ник")
    row = find_user(parts[index])
    if row is None:
        raise ApiError(404, "Нет такого пользователя: %s" % parts[index])
    return row


def parse_int(value, what="число"):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, "Нужно %s" % what)
    return max(-1_000_000_000, min(1_000_000_000, number))


def run_command(admin, text):
    parts = text[1:].split()
    if not parts:
        raise ApiError(400, "Пустая команда. /help — список")
    cmd = parts[0].lower()
    try:
        reply = execute_command(admin, cmd, parts, text)
    except ApiError as error:
        return "⚠ " + error.message
    if cmd not in ("help", "ranks", "userinfo"):
        log_admin(admin, text)
    _db.commit()
    return reply


def execute_command(admin, cmd, parts, text):
    if cmd == "help":
        return "\n".join(HELP)
    if cmd == "ranks":
        return "Ранги: " + ", ".join("%s (%s)" % (k, v) for k, v in RANKS.items())
    if cmd == "userinfo":
        t = cmd_target(parts)
        return "%s: ранг %s, очки %d, роль %s, %s, заглушен до %s, создан %s" % (
            t["name"], t["rank"], t["points"], t["role"], "ЗАБАНЕН" if t["banned"] else "активен",
            time.strftime("%d.%m %H:%M", time.localtime(t["muted_until"])) if t["muted_until"] > now() else "—",
            time.strftime("%d.%m.%Y", time.localtime(t["created"])))
    if cmd in ("points", "setpoints"):
        t = cmd_target(parts)
        amount = parse_int(parts[2] if len(parts) > 2 else None)
        total = t["points"] + amount if cmd == "points" else amount
        total = max(-1_000_000_000, min(1_000_000_000, total))
        _db.execute("UPDATE users SET points = ? WHERE id = ?", (total, t["id"]))
        return "%s: очки теперь %d" % (t["name"], total)
    if cmd == "rank":
        t = cmd_target(parts)
        wanted = (parts[2] if len(parts) > 2 else "").lower()
        key = next((k for k, v in RANKS.items() if wanted in (k, v.lower())), None)
        if key is None:
            raise ApiError(400, "Нет такого ранга. /ranks — список")
        _db.execute("UPDATE users SET rank = ? WHERE id = ?", (key, t["id"]))
        return "%s: ранг «%s»" % (t["name"], RANKS[key])
    if cmd in ("mute", "unmute"):
        t = cmd_target(parts)
        if t["role"] == "admin" and t["id"] != admin["id"]:
            raise ApiError(403, "Нельзя заглушать другого админа")
        minutes = 0 if cmd == "unmute" else max(1, min(parse_int(parts[2] if len(parts) > 2 else None, "число минут"), 525600))
        until = now() + minutes * 60 if minutes else 0
        _db.execute("UPDATE users SET muted_until = ? WHERE id = ?", (until, t["id"]))
        return "%s: %s" % (t["name"], "заглушен на %d мин." % minutes if minutes else "мут снят")
    if cmd in ("ban", "unban"):
        t = cmd_target(parts)
        if cmd == "ban":
            if t["role"] == "admin":
                raise ApiError(403, "Нельзя банить админов")
            reason = clean_text(" ".join(parts[2:]), 100)
            _db.execute("UPDATE users SET banned = 1, ban_reason = ? WHERE id = ?", (reason, t["id"]))
            _db.execute("DELETE FROM sessions WHERE user_id = ?", (t["id"],))
            return "%s забанен" % t["name"]
        _db.execute("UPDATE users SET banned = 0, ban_reason = '' WHERE id = ?", (t["id"],))
        return "%s разбанен" % t["name"]
    if cmd == "del":
        message_id = parse_int(parts[1] if len(parts) > 1 else None, "id сообщения")
        _db.execute("UPDATE chat SET deleted = 1 WHERE id = ?", (message_id,))
        return "Сообщение %d удалено" % message_id
    if cmd == "delc":
        comment_id = parse_int(parts[1] if len(parts) > 1 else None, "id комментария")
        _db.execute("UPDATE comments SET deleted = 1 WHERE id = ?", (comment_id,))
        return "Комментарий %d удалён" % comment_id
    if cmd == "clear":
        arg = (parts[1] if len(parts) > 1 else "50").lower()
        if arg == "all":
            count = _db.execute("UPDATE chat SET deleted = 1 WHERE deleted = 0").rowcount
        else:
            n = max(1, min(parse_int(arg), 500))
            count = _db.execute("UPDATE chat SET deleted = 1 WHERE id IN (SELECT id FROM chat WHERE deleted = 0 ORDER BY id DESC LIMIT ?)", (n,)).rowcount
        return "Удалено сообщений: %d" % count
    if cmd == "announce":
        message = clean_text(text[len("/announce"):], 300)
        if not message:
            raise ApiError(400, "Нужен текст объявления")
        _db.execute("INSERT INTO chat(user_id, kind, text, created) VALUES (NULL, 'system', ?, ?)", (message, now()))
        return "Объявление отправлено"
    raise ApiError(404, "Неизвестная команда. /help — список")


# ---------------------------------------------------------------- «Критика»
def api_comments_get(ctx):
    alias = ctx.query.get("alias", "")
    if not ALIAS_RE.match(alias):
        raise ApiError(400, "Плохой адрес аниме")
    try:
        before = int(ctx.query.get("before") or 0) or 2 ** 62
    except ValueError:
        raise ApiError(400, "Плохой параметр")
    rows = _db.execute(
        "SELECT * FROM comments WHERE alias = ? AND deleted = 0 AND id < ? ORDER BY id DESC LIMIT 21", (alias, before)
    ).fetchall()
    total = _db.execute("SELECT COUNT(*) FROM comments WHERE alias = ? AND deleted = 0", (alias,)).fetchone()[0]
    items = []
    for r in rows[:20]:
        author = _db.execute("SELECT * FROM users WHERE id = ?", (r["user_id"],)).fetchone()
        items.append({"id": r["id"], "text": r["text"], "ts": r["created"], "user": pub(author)})
    return {"comments": items, "total": total, "has_more": len(rows) > 20}


def api_comments_post(ctx):
    user = require_user(ctx.user)
    alias = str(ctx.data.get("alias", ""))
    if not ALIAS_RE.match(alias):
        raise ApiError(400, "Плохой адрес аниме")
    text = clean_text(ctx.data.get("text", ""), 2000)
    if len(text) < 2:
        raise ApiError(400, "Слишком короткий текст")
    check_can_post(user)
    rate_limit("comment:%d" % user["id"], 3, 60)
    cur = _db.execute("INSERT INTO comments(alias, user_id, text, created) VALUES (?,?,?,?)", (alias, user["id"], text, now()))
    _db.commit()
    return {"ok": True, "id": cur.lastrowid}


def api_delete(ctx):
    user = require_user(ctx.user)
    kind = ctx.data.get("kind")
    item_id = parse_int(ctx.data.get("id"), "id")
    if kind == "comment":
        row = _db.execute("SELECT * FROM comments WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ApiError(404, "Не найдено")
        if row["user_id"] != user["id"] and user["role"] != "admin":
            raise ApiError(403, "Нельзя")
        _db.execute("UPDATE comments SET deleted = 1 WHERE id = ?", (item_id,))
    elif kind == "chat":
        require_admin(user)
        _db.execute("UPDATE chat SET deleted = 1 WHERE id = ?", (item_id,))
    else:
        raise ApiError(400, "Неизвестный тип")
    if user["role"] == "admin":
        log_admin(user, "delete %s %d" % (kind, item_id))
    _db.commit()
    return {"ok": True}



# ---------------------------------------------------------------- совместный просмотр (комнаты)
# Комнаты живут в памяти сервера (после перезапуска пропадают). Клиенты опрашивают состояние раз в секунду
# и подстраивают своё видео под серверные часы комнаты.
ROOMS = {}
ROOM_TTL = 6 * 3600
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def room_expire():
    t = time.time()
    for code in [c for c, r in ROOMS.items() if t - r["touched"] > ROOM_TTL]:
        del ROOMS[code]


def get_room(code):
    room = ROOMS.get(str(code or "").strip().upper())
    if room is None:
        raise ApiError(404, "Комната не найдена или уже закрыта")
    return room


def room_position(room):
    return room["pos"] + (time.time() - room["ts"]) if room["playing"] else room["pos"]


def room_state(room):
    host = _db.execute("SELECT * FROM users WHERE id = ?", (room["host_id"],)).fetchone()
    return {"version": room["version"], "code": room["code"], "alias": room["alias"], "title": room["title"],
            "episode": room["episode"], "playing": room["playing"], "pos": room["pos"], "ts": room["ts"],
            "shared": room["shared"], "host": pub(host) if host else None}


def can_control(room, user):
    return room["shared"] or room["host_id"] == user["id"]


def api_room_create(ctx):
    user = require_user(ctx.user)
    rate_limit("roomnew:%d" % user["id"], 10, 3600)
    alias = str(ctx.data.get("alias", ""))
    if not ALIAS_RE.match(alias):
        raise ApiError(400, "Плохой адрес аниме")
    room_expire()
    if sum(1 for r in ROOMS.values() if r["host_id"] == user["id"]) >= 3:
        raise ApiError(429, "У тебя уже 3 открытые комнаты")
    code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
    while code in ROOMS:
        code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
    try:
        episode = max(1, min(int(ctx.data.get("episode") or 1), 5000))
    except (TypeError, ValueError):
        episode = 1
    ROOMS[code] = {
        "code": code, "host_id": user["id"], "alias": alias, "title": clean_text(ctx.data.get("title", ""), 100),
        "episode": episode, "playing": False, "pos": 0.0, "ts": time.time(), "version": 1, "shared": False,
        "touched": time.time(), "members": {}, "chat": [], "chat_seq": 0,
    }
    return {"ok": True, "code": code}


def api_room_get(ctx):
    user = require_user(ctx.user)
    room = get_room(ctx.query.get("code"))
    try:
        version = int(ctx.query.get("v") or 0)
        chat_after = int(ctx.query.get("c") or 0)
    except ValueError:
        raise ApiError(400, "Плохой параметр")
    t = time.time()
    room["members"][user["id"]] = t
    room["touched"] = t
    members = []
    for uid, seen in list(room["members"].items()):
        if t - seen > 10:
            continue
        row = _db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if row:
            members.append(dict(pub(row), host=(uid == room["host_id"])))
    chat = []
    for message in room["chat"]:
        if message["id"] > chat_after:
            author = _db.execute("SELECT * FROM users WHERE id = ?", (message["uid"],)).fetchone()
            chat.append({"id": message["id"], "text": message["text"], "ts": message["ts"], "user": pub(author) if author else None})
    same = version == room["version"]
    result = {"now": t, "same": same, "controller": can_control(room, user), "members": members,
              "chat": chat, "chat_last": room["chat_seq"]}
    if not same:
        result["state"] = room_state(room)
    return result


def api_room_control(ctx):
    user = require_user(ctx.user)
    rate_limit("roomctl:%d" % user["id"], 30, 10)
    room = get_room(ctx.data.get("code"))
    if not can_control(room, user):
        raise ApiError(403, "Управляет хост")
    action = ctx.data.get("action")
    try:
        position = float(ctx.data["position"]) if ctx.data.get("position") is not None else None
    except (TypeError, ValueError):
        raise ApiError(400, "Плохая позиция")
    if position is not None and not (0 <= position <= 86400):
        raise ApiError(400, "Плохая позиция")
    t = time.time()
    if action == "play":
        room.update(pos=position if position is not None else room_position(room), ts=t, playing=True)
    elif action == "pause":
        room.update(pos=position if position is not None else room_position(room), ts=t, playing=False)
    elif action == "seek":
        if position is None:
            raise ApiError(400, "Нужна позиция")
        room.update(pos=position, ts=t)
    elif action == "episode":
        try:
            episode = int(ctx.data.get("episode"))
        except (TypeError, ValueError):
            raise ApiError(400, "Нужен номер серии")
        episode = max(1, min(episode, 5000))
        if episode != room["episode"]:
            room.update(episode=episode, pos=0.0, ts=t, playing=True)
        else:
            return {"ok": True, "state": room_state(room)}
    else:
        raise ApiError(400, "Неизвестное действие")
    room["version"] += 1
    room["touched"] = t
    return {"ok": True, "state": room_state(room)}


def api_room_say(ctx):
    user = require_user(ctx.user)
    room = get_room(ctx.data.get("code"))
    text = clean_text(ctx.data.get("text", ""), 300)
    if not text:
        raise ApiError(400, "Пустое сообщение")
    check_can_post(user)
    rate_limit("roomsay:%d" % user["id"], 4, 6)
    room["chat_seq"] += 1
    room["chat"].append({"id": room["chat_seq"], "uid": user["id"], "text": text, "ts": now()})
    del room["chat"][:-80]
    return {"ok": True}


def api_room_settings(ctx):
    user = require_user(ctx.user)
    room = get_room(ctx.data.get("code"))
    if room["host_id"] != user["id"]:
        raise ApiError(403, "Только хост")
    room["shared"] = bool(ctx.data.get("shared"))
    room["version"] += 1
    return {"ok": True, "state": room_state(room)}

# ---------------------------------------------------------------- маршрутизация
ROUTES = {
    ("GET", "/social/me"): api_me,
    ("POST", "/social/register"): api_register,
    ("POST", "/social/login"): api_login,
    ("POST", "/social/logout"): api_logout,
    ("GET", "/social/user"): api_user,
    ("POST", "/social/profile"): api_profile,
    ("POST", "/social/avatar"): api_avatar,
    ("GET", "/social/friends"): api_friends,
    ("POST", "/social/friend"): api_friend,
    ("GET", "/social/users"): api_users,
    ("GET", "/social/top"): api_top,
    ("GET", "/social/chat"): api_chat_get,
    ("POST", "/social/chat"): api_chat_post,
    ("GET", "/social/comments"): api_comments_get,
    ("POST", "/social/comments"): api_comments_post,
    ("POST", "/social/delete"): api_delete,
    ("POST", "/social/room/create"): api_room_create,
    ("GET", "/social/room"): api_room_get,
    ("POST", "/social/room/control"): api_room_control,
    ("POST", "/social/room/say"): api_room_say,
    ("POST", "/social/room/settings"): api_room_settings,
}


class Ctx:
    def __init__(self):
        self.user = None
        self.data = {}
        self.query = {}
        self.ip = ""
        self.cookie_token = ""
        self.set_cookie = None  # None — не трогать, "" — удалить, строка — выдать


def handle(method, path, query_string, body, headers, ip, secure):
    """Возвращает (status, payload_dict, set_cookie_header_or_None)."""
    route = ROUTES.get((method, path))
    if route is None:
        return 404, {"error": "Не найдено"}, None
    ctx = Ctx()
    ctx.ip = ip
    ctx.query = {k: v[0] for k, v in parse_qs(query_string).items()}
    try:
        if method == "POST":
            # защита от CSRF: чужой сайт не может поставить такой заголовок без нашего разрешения (CORS)
            if headers.get("X-Requested-With") != "zerinet":
                raise ApiError(403, "Запрос отклонён")
            origin = headers.get("Origin")
            if origin and origin.split("://", 1)[-1] != headers.get("Host"):
                raise ApiError(403, "Запрос отклонён")
            try:
                ctx.data = json.loads(body or b"{}")
            except ValueError:
                raise ApiError(400, "Плохой JSON")
            if not isinstance(ctx.data, dict):
                raise ApiError(400, "Плохой JSON")
        cookie_value = headers.get("Cookie")
        with _lock:
            ctx.user = user_from_cookie(cookie_value)
            if cookie_value:
                try:
                    ctx.cookie_token = http.cookies.SimpleCookie(cookie_value)["zsid"].value
                except (KeyError, http.cookies.CookieError):
                    ctx.cookie_token = ""
            payload = route(ctx)
    except ApiError as error:
        return error.status, {"error": error.message}, None
    set_cookie = None
    if ctx.set_cookie is not None:
        set_cookie = cookie_header(ctx.set_cookie, secure, max_age=0 if ctx.set_cookie == "" else SESSION_DAYS * 86400)
    return 200, payload, set_cookie


# ---------------------------------------------------------------- консольные команды
def set_admin(name, make):
    with _lock:
        row = find_user(name)
        if row is None:
            return "Пользователь %s не найден (сначала зарегистрируйся на сайте)" % name
        if make:
            _db.execute("UPDATE users SET role = 'admin', rank = 'admin' WHERE id = ?", (row["id"],))
        else:
            _db.execute("UPDATE users SET role = 'user', rank = 'novice' WHERE id = ?", (row["id"],))
        _db.commit()
        return "%s теперь %s" % (row["name"], "админ" if make else "обычный пользователь")


def list_users():
    with _lock:
        rows = _db.execute("SELECT name, role, rank, points, banned FROM users ORDER BY id").fetchall()
    if not rows:
        return "Пока никто не зарегистрирован. Сначала создай аккаунт на сайте."
    return "\n".join("%-20s %-6s ранг=%-10s очки=%d%s" % (r["name"], r["role"], r["rank"], r["points"], "  ЗАБАНЕН" if r["banned"] else "") for r in rows)

# ================= КОНЕЦ СОЦИАЛЬНОГО BACKEND =================

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "127.0.0.1")           # для интернета на своём сервере: HOST=0.0.0.0
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"   # за nginx/Caddy/Render: брать IP из X-Forwarded-For
UPSTREAMS = os.environ.get(
    "UPSTREAMS",
    "https://anilibria.top/api/v1,https://api.anilibria.app/api/v1",
).split(",")
ROOT = os.path.dirname(os.path.abspath(__file__))
# отдаём наружу ТОЛЬКО эти файлы (токен, база данных и код сервера недоступны по адресу)
STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/social.js": "social.js"}
MAX_BODY = 400_000

# Токен Kodik: переменная окружения KODIK_TOKEN или файл kodik_token.txt рядом с server.py.
KODIK_API = os.environ.get("KODIK_API", "https://kodik-api.com").rstrip("/")
KODIK_ALLOWED = {"title", "shikimori_id", "with_material_data", "types", "limit", "strict", "year"}


def read_kodik_token():
    token = os.environ.get("KODIK_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(os.path.join(ROOT, "kodik_token.txt"), encoding="utf-8-sig") as file:
            return file.read().strip()
    except OSError:
        return ""


KODIK_TOKEN = read_kodik_token()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        # файлы сайта не должны застревать в кеше браузера после обновления
        if not getattr(self, "_has_cache_header", False):
            self.send_header("Cache-Control", "no-cache")
        self._has_cache_header = False
        super().end_headers()

    def client_ip(self):
        if TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def is_https(self):
        return self.headers.get("X-Forwarded-Proto", "") == "https"

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # Same-origin proxy used by the browser. Keeps API calls away from CORS
        # restrictions and centralizes the official AniLibria v1 mirrors.
        if path.startswith("/aniapi/"):
            return self.proxy(self.path[len("/aniapi"):])
        if path.startswith("/api/"):
            return self.proxy(self.path[len("/api"):])
        if path.startswith("/kodik/"):
            return self.kodik(parsed)
        if path.startswith("/social/"):
            return self.social("GET", parsed, b"")
        if path.startswith("/avatars/"):
            data = read_avatar(path[len("/avatars/"):])
            if data is None:
                return self.reply(404, "text/plain", b"not found")
            return self.reply(200, "image/jpeg", data, cache="public, max-age=604800")
        if path in STATIC_FILES:
            self.path = "/" + STATIC_FILES[path]
            return super().do_GET()
        return self.reply(404, "text/plain; charset=utf-8", b"Not found")

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/social/"):
            return self.reply(404, "text/plain", b"not found")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return self.reply(413, "application/json", '{"error":"Слишком большой запрос"}'.encode())
        body = self.rfile.read(length) if length else b""
        return self.social("POST", parsed, body)

    def social(self, method, parsed, body):
        status, payload, cookie = handle(
            method, parsed.path, parsed.query, body, self.headers, self.client_ip(), self.is_https()
        )
        extra = {"Set-Cookie": cookie} if cookie is not None else None
        self.reply(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode(), extra=extra)

    # ---------------------------------------------------------------- прокси
    def kodik(self, parsed):
        if parsed.path == "/kodik/status":
            return self.reply(200, "application/json", json.dumps({"enabled": bool(KODIK_TOKEN)}).encode())
        if parsed.path != "/kodik/search" or not KODIK_TOKEN:
            return self.reply(404, "application/json", b'{"error":"not_available"}')
        # из запроса берём только разрешённые параметры, свой токен браузера игнорируем
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items() if k in KODIK_ALLOWED}
        query["token"] = KODIK_TOKEN
        url = KODIK_API + "/search?" + urllib.parse.urlencode(query)
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 zerinet-local"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return self.reply(response.status, "application/json", response.read())
        except urllib.error.HTTPError as error:
            body = error.read() or b'{"error":"kodik_error"}'
            print("Kodik ответил HTTP %d: %s" % (error.code, body[:200].decode("utf-8", "replace")), file=sys.stderr)
            return self.reply(error.code, "application/json", body)
        except Exception as error:
            print("kodik error:", error, file=sys.stderr)
            return self.reply(502, "application/json", b'{"error":"kodik_unavailable"}')

    def proxy(self, path):
        last_status = 502
        for base in UPSTREAMS:
            request = urllib.request.Request(base.strip() + path, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 zerinet-local"})
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    return self.reply(response.status, response.headers.get("Content-Type", "application/json"), response.read())
            except urllib.error.HTTPError as error:
                body = error.read()
                if error.code == 404 and "json" in (error.headers.get("Content-Type") or ""):
                    return self.reply(404, "application/json", body)
                last_status = error.code
            except Exception as error:  # сеть, таймаут и т.п. -> пробуем зеркало
                print("upstream error:", base, error, file=sys.stderr)
                last_status = 504
        self.reply(502, "application/json", ('{"error":"upstream_unavailable","status":%d}' % last_status).encode())

    def reply(self, status, content_type, body, extra=None, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self._has_cache_header = True
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "users":
        print(list_users())
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] in ("admin", "unadmin"):
        print(set_admin(sys.argv[2], sys.argv[1] == "admin"))
        sys.exit(0)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://localhost:%d" % PORT
    print("Сайт запущен:", url, "(останови: Ctrl+C)")
    print("Kodik:", "включён (токен найден)" if KODIK_TOKEN else "выключен (нет токена)")
    print("Данные (база и аватарки):", DATA_DIR)
    if os.environ.get("NO_BROWSER") != "1" and HOST == "127.0.0.1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
