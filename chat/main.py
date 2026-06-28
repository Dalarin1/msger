import mimetypes
import fastapi
import uvicorn
import hashlib
import sqlite3
import uuid
import jwt
import os

from hashlib import sha256
from typing import Literal
from urllib.parse import quote
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi import Limiter, _rate_limit_exceeded_handler
from datetime import datetime, timedelta, timezone
from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    Depends,
    Response,
    Cookie,
    UploadFile,
    File,
)
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

#    CONFIG
SECRET_KEY = os.environ.get("SECRET_KEY", "change_me_in_production_please_for_32+_char_password")
PEPPER_KEY = os.environ.get("PEPPER_KEY", "change_me_in_production_please")
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FOLDER = os.path.join(BASE_DIR, "database")
MIGRATIONS_FLD = os.path.join(BASE_DIR, "migrations")
DB_PATH = os.path.join(DATABASE_FOLDER, "app.db")
MAKE_TABLES_SCRIPT_PATH = os.path.join(BASE_DIR, "make_tables.sqlite3")
STATIC_FILES_FLD = os.path.join(BASE_DIR, "static")

ATTACHEMENTS_FLD = os.path.join(BASE_DIR, "attachments")
USER_IMAGES_FLD = os.path.join(ATTACHEMENTS_FLD, "images")
USER_AUDIO_FLD = os.path.join(ATTACHEMENTS_FLD, "audios")
USER_VIDEO_FLD = os.path.join(ATTACHEMENTS_FLD, "videos")
USER_FILES_FLD = os.path.join(ATTACHEMENTS_FLD, "others")

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 МБ
MAX_AUDIO_SIZE = 30 * 1024 * 1024  # 30 МБ
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 МБ
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 МБ

ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".jfif", ".webp", ".svg"},
    "video": {".mp4", ".webm"},
    "audio": {".mp3", ".wav", ".ogg"},
}

MAX_SIZES = {
    "image": MAX_IMAGE_SIZE,
    "video": MAX_VIDEO_SIZE,
    "audio": MAX_AUDIO_SIZE,
    "file": MAX_FILE_SIZE,
}

FOLDERS = {
    "image": USER_IMAGES_FLD,
    "video": USER_VIDEO_FLD,
    "audio": USER_AUDIO_FLD,
    "file": USER_FILES_FLD,
}

URL_PREFIXES = {
    "image": "/img",
    "video": "/video",
    "audio": "/audio",
    "file": "/file",
}

limiter = Limiter(key_func=get_remote_address)
app = fastapi.FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

bearer_scheme = HTTPBearer(auto_error=False)

conn: sqlite3.Connection
cursor: sqlite3.Cursor


def make_environ() -> None:
    global conn, cursor

    if os.name == "nt":
        os.system("")

    os.makedirs(DATABASE_FOLDER, exist_ok=True)
    os.makedirs(MIGRATIONS_FLD, exist_ok=True)
    os.makedirs(USER_IMAGES_FLD, exist_ok=True)
    os.makedirs(USER_AUDIO_FLD, exist_ok=True)
    os.makedirs(USER_VIDEO_FLD, exist_ok=True)
    os.makedirs(USER_FILES_FLD, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    cursor = conn.cursor()

    with open(MAKE_TABLES_SCRIPT_PATH, "r") as script_file:
        script = script_file.read()
    cursor.executescript(script)
    
    if db_schema_changed(cursor, script):
        run_migration(cursor, conn)

        
    conn.commit()


def db_schema_changed(cursor:sqlite3.Cursor, script:str) -> bool:
    return _parse_expected_schema(script) != _get_actual_schema(cursor)


def _parse_expected_schema(script: str) -> dict[str, set[str]]:
    tmp = sqlite3.connect(":memory:")
    tmp.executescript(script)
    
    tables = {}
    rows = tmp.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    
    for (table_name,) in rows:
        cols = tmp.execute(f"PRAGMA table_info({table_name})").fetchall()
        tables[table_name] = {col[1] for col in cols}
    
    tmp.close()
    return tables

def _get_actual_schema(cursor: sqlite3.Cursor) -> dict[str, set[str]]:
    """Читает реальную структуру из sqlite_master"""
    tables = {}
    rows = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\';"
    ).fetchall()
    for row in rows:
        table_name = row[0]
        cols = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        tables[table_name] = {col[1] for col in cols}  # col[1] — имя колонки
    return tables


def _get_db_version(cursor: sqlite3.Cursor) -> int:
    cursor.executescript("CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER NOT NULL);")
    
    row = cursor.execute("SELECT version FROM _schema_version").fetchone()

    return row["version"] if row else 0

def _set_db_version(cursor: sqlite3.Cursor, version: int) -> None:
    cursor.execute("DELETE FROM _schema_version")
    cursor.execute("INSERT INTO _schema_version (version) VALUES (?)", (version,))


def run_migration(cursor: sqlite3.Cursor, conn: sqlite3.Connection):
    """
    Version naming: 
    <version_before>_to_<version_to>_[optional_description].sqlite3
    """
    curversion = _get_db_version(cursor)

    # Собираем все файлы миграций и сортируем по номеру
    files = sorted(
        f for f in os.listdir(MIGRATIONS_FLD) if f.endswith(".sqlite3") or f.endswith(".sql")
    )
    for filename in files:
        version = int(filename.split("_")[0])  # "002_add_avatar..." -> 2
        if version <= curversion:
            continue

        path = os.path.join(MIGRATIONS_FLD, filename)
        with open(path) as f:
            cursor.executescript(f.read())

        _set_db_version(cursor, version)
        curversion = version
        conn.commit()


# ── JWT ───────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_token(user_id: str, user_name: str | None = "anon"):
    now = _now_utc()
    data = {
        "iss": "oleg-chat-jwt-vendor",
        "type": "access",
        "sub": user_id,
        "nam": user_name,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(data, SECRET_KEY, ALGORITHM)


def create_refresh_token(user_id: str):
    jti = str(uuid.uuid4())
    iat = _now_utc()
    expires_at = iat + REFRESH_TOKEN_TTL
    data = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iat": iat,
        "exp": expires_at,
    }
    token = jwt.encode(data, SECRET_KEY, ALGORITHM)
    cursor.execute(
        "INSERT INTO refresh_tokens (jti, user_id, expires_at) VALUES (?, ?, ?)",
        (jti, user_id, expires_at.isoformat()),
    )
    conn.commit()
    return token


def decode_token(encoded_token: str) -> dict:
    try:
        return jwt.decode(encoded_token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def revoke_token(jti: str) -> None:
    cursor.execute("UPDATE refresh_tokens SET revoked = 1 WHERE jti=?", (jti,))
    conn.commit()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Expected access token")
    return payload


# ── HELPERS ───────────────────────────────────────────────────────────────


def _get_attachments(message_id: int, message_type: str) -> list[dict]:
    rows = cursor.execute(
        "SELECT url, mime, original_name FROM message_attachments "
        "WHERE message_id = ? AND message_type = ?",
        (message_id, message_type),
    ).fetchall()
    return [
        {"url": r["url"], "mime": r["mime"], "original_name": r["original_name"]}
        for r in rows
    ]


def _save_attachments(
    message_id: int, message_type: str, attachments: list[dict]
) -> None:
    """attachments — список {"url": ..., "mime": ..., "original_name": ...}"""
    for a in attachments:
        cursor.execute(
            "INSERT INTO message_attachments (message_id, message_type, url, mime, original_name) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, message_type, a["url"], a.get("mime"), a.get("original_name")),
        )
    conn.commit()


def _row_to_msg(row: sqlite3.Row, message_type: str) -> dict:
    msg_id = row["id"]
    return {
        "id": msg_id,
        "sender": row["sender"],
        "sender_id": row["sender_id"],
        "text": row["text"],
        "timestamp": row["timestamp"],
        "attachments": _get_attachments(msg_id, message_type),
    }


def get_global_history(limit: int = 100, before_id: int | None = None) -> list[dict]:
    if before_id:
        cursor.execute(
            "SELECT id, sender, sender_id, text, timestamp FROM global_messages "
            "WHERE id < ? ORDER BY id DESC LIMIT ?",
            (before_id, limit),
        )
    else:
        cursor.execute(
            "SELECT id, sender, sender_id, text, timestamp FROM global_messages "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_msg(i, "global") for i in reversed(cursor.fetchall())]


def save_global_msg(
    sender_id: str, sender: str, text: str, attachments: list[dict] | None = None
) -> dict:
    ts = _now_utc().isoformat()
    cur = conn.execute(
        "INSERT INTO global_messages (sender_id, sender, text, timestamp) VALUES (?, ?, ?, ?)",
        (sender_id, sender, text, ts),
    )
    conn.commit()
    msg_id = cur.lastrowid
    if attachments:
        _save_attachments(msg_id, "global", attachments)
    return {
        "id": msg_id,
        "sender": sender,
        "sender_id": sender_id,
        "text": text,
        "timestamp": ts,
        "attachments": attachments or [],
    }


def get_p2p_history(
    chat_id: str, limit: int = 100, before_id: int | None = None
) -> list[dict]:
    if before_id:
        cursor.execute(
            "SELECT id, sender, sender_id, text, timestamp FROM p2p_messages "
            "WHERE chat_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (chat_id, before_id, limit),
        )
    else:
        cursor.execute(
            "SELECT id, sender, sender_id, text, timestamp FROM p2p_messages "
            "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
    return [_row_to_msg(i, "p2p") for i in reversed(cursor.fetchall())]


def save_p2p_msg(
    chat_id: str,
    sender_id: str,
    sender: str,
    text: str,
    attachments: list[dict] | None = None,
) -> dict:
    ts = _now_utc().isoformat()
    cursor.execute(
        "INSERT INTO p2p_messages (chat_id, sender_id, sender, text, timestamp) VALUES (?, ?, ?, ?, ?)",
        (chat_id, sender_id, sender, text, ts),
    )
    conn.commit()
    msg_id = cursor.lastrowid
    if attachments:
        _save_attachments(msg_id, "p2p", attachments)
    return {
        "id": msg_id,
        "chat_id": chat_id,
        "sender": sender,
        "sender_id": sender_id,
        "text": text,
        "timestamp": ts,
        "attachments": attachments or [],
    }


def make_p2p_chat(id_1: str, id_2: str) -> str:
    key = "".join(sorted([id_1, id_2]))
    chat_id = hashlib.sha1(key.encode()).hexdigest()
    cursor.execute(
        "INSERT OR IGNORE INTO chats (chat_id, user_id, other_id) VALUES (?, ?, ?)",
        (chat_id, id_1, id_2),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO chats (chat_id, user_id, other_id) VALUES (?, ?, ?)",
        (chat_id, id_2, id_1),
    )
    conn.commit()
    return chat_id


# ── WebSocket clients ─────────────────────────────────────────────────────

global_clients: list[WebSocket] = []
p2p_clients: dict[str, list[WebSocket]] = {}


# ── STATIC ────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def get_index(request: fastapi.Request):
    return HTMLResponse(open(os.path.join(STATIC_FILES_FLD, "index.html")).read())


@app.get("/sha256.js")
@limiter.limit("30/minute")
async def get_sha256(request: fastapi.Request):
    return FileResponse(
        os.path.join(STATIC_FILES_FLD, "sha256.js"), media_type="application/javascript"
    )


@app.get("/chat", response_class=HTMLResponse)
@app.get("/chat/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def get_chat_html(request: fastapi.Request):
    return HTMLResponse(open(os.path.join(STATIC_FILES_FLD, "chat.html")).read())


@app.get("/profile", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def get_profile_html(request: fastapi.Request):
    return HTMLResponse(open(os.path.join(STATIC_FILES_FLD, "profile.html")).read())


@app.get("/login")
@limiter.limit("30/minute")
async def get_login_page(request: fastapi.Request):
    return HTMLResponse(open(os.path.join(STATIC_FILES_FLD, "login.html")).read())


# ── AUTH ──────────────────────────────────────────────────────────────────
def hash_with_salt_pepper(client_hash: str, salt: str) -> str:
    combined = PEPPER_KEY + client_hash + salt
    return sha256(combined.encode()).hexdigest()


@app.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: fastapi.Request, response: Response) -> dict:
    username = request.headers.get("oleg-name")
    password_hash = request.headers.get("oleg-password-hash")

    if not password_hash:
        raise HTTPException(status_code=400, detail="oleg-password-hash header missing")

    if not username or len(username) > 32:
        raise HTTPException(status_code=400, detail="oleg-name header missing")

    existing = cursor.execute(
        "SELECT id FROM members WHERE name = ?", (username,)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user_id = str(uuid.uuid4())
    salt = os.urandom(32).hex()
    final_hash = hash_with_salt_pepper(password_hash, salt)
    cursor.execute(
        "INSERT INTO members (id, password_hash, name, salt, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, final_hash, username, salt, _now_utc().isoformat()),
    )
    conn.commit()

    response.set_cookie(
        key="refresh-token",
        value=create_refresh_token(user_id),
        samesite="lax",
        httponly=True,
        secure=True,
        max_age=60 * 60 * 24 * 30,
    )
    return {
        "ok": True,
        "id": user_id,
        "access_token": create_token(user_id, username),
        "token_type": "bearer",
    }


@app.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: fastapi.Request, response: Response) -> dict:
    username = (request.headers.get("oleg-name") or "").strip()
    client_hash = request.headers.get("oleg-password-hash")

    if not client_hash:
        raise HTTPException(400, "oleg-password-hash missing")
    if not username or len(username) > 32:
        raise HTTPException(400, "Invalid username")

    row = cursor.execute(
        "SELECT id, name, password_hash, salt FROM members WHERE name = ?", (username,)
    ).fetchone()

    if not row:
        raise HTTPException(401, "Wrong login or password")
    
    final_hash = hash_with_salt_pepper(client_hash, row["salt"])
    if final_hash != row["password_hash"]:
        raise HTTPException(401, "Wrong login or password")
    
    user_id = row["id"]
    user_name = row["name"]

    response.set_cookie(
        key="refresh-token",
        value=create_refresh_token(user_id),
        samesite="lax",
        httponly=True,
        secure=True,
        max_age=60 * 60 * 24 * 30,
    )
    return {
        "ok": True,
        "id": user_id,
        "access_token": create_token(user_id, user_name),
        "token_type": "bearer",
    }


@app.post("/auth/refresh")
@limiter.limit("30/minute")
async def refresh_tokens(
    request: fastapi.Request,
    refresh_token: str | None = Cookie(alias="refresh-token", default=None),
) -> dict:
    if not refresh_token:
        raise HTTPException(400, "Refresh token not found")

    payload = decode_token(refresh_token)
    jti = payload.get("jti")
    user_id = payload.get("sub")
    _type = payload.get("type")

    if not _type or _type != "refresh" or user_id is None:
        if not _type:
            raise HTTPException(401, "Invalid token: \"type\" not set")
        if _type != "refresh":
            raise HTTPException(401, "Invalid token: \"type\" != \"refresh\"")
        if user_id is None:
            raise HTTPException(401, "Invalid token: \"user_id\" aka \"sub\" not set")

    row = cursor.execute(
        "SELECT expires_at, revoked FROM refresh_tokens WHERE jti = ?", (jti,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Token not found")
    if row["revoked"]:
        raise HTTPException(status_code=401, detail="Token revoked")

    user_row = cursor.execute(
        "SELECT name FROM members WHERE id = ?", (user_id,)
    ).fetchone()
    if not user_row:
        raise HTTPException(400, "There are no user with that token")

    user_name = user_row["name"]
    return {
        "access_token": create_token(user_id, user_name),
        "token_type": "bearer",
        "name": user_name,
    }


@app.post("/auth/logout")
@limiter.limit("10/minute")
async def logout(
    request: fastapi.Request,
    refresh_token: str | None = Cookie(alias="refresh-token", default=None),
    current_user: dict = Depends(get_current_user),
) -> dict:
    if not refresh_token:
        raise HTTPException(400, "Refresh token not found")
    try:
        payload = decode_token(refresh_token)
        revoke_token(payload.get("jti", ""))
    except Exception:
        pass
    return {"ok": True}


@app.post("/auth/logout_all")
@limiter.limit("1/minutes")
async def logout_all(
    request: fastapi.Request, current_user: dict = Depends(get_current_user)
) -> dict:
    cursor.execute(
        "UPDATE refresh_tokens SET revoked=1 WHERE user_id=?", (current_user["sub"],)
    )
    conn.commit()
    return {"ok": True}


# ── GLOBAL CHAT ───────────────────────────────────────────────────────────


@app.post("/send_msg")
@limiter.limit("30/minute")
async def send_msg(
    request: fastapi.Request,
    current_user: dict = Depends(get_current_user),
):
    """Body JSON: { "text": "...", "attachments": [{"url": "/img/...", "mime": "image/jpeg", "original_name": "photo.jpg"}] }"""
    body = await request.json()
    text = body.get("text", "").strip()
    attachments: list[dict] = body.get("attachments") or []

    if not text and not attachments:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="Message too long")

    user_id = current_user["sub"]
    row = cursor.execute("SELECT name FROM members WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(403, "Username not found")

    msg = save_global_msg(user_id, row["name"], text, attachments)

    dead = []
    for ws in global_clients:
        try:
            await ws.send_json({"type": "message", "message": msg})
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in global_clients:
            global_clients.remove(ws)

    return {"ok": True}


@app.websocket("/ws")
async def global_ws(ws: WebSocket):
    await ws.accept()
    global_clients.append(ws)
    try:
        await ws.send_json({"type": "history", "messages": get_global_history()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in global_clients:
            global_clients.remove(ws)


# ── P2P CHATS ─────────────────────────────────────────────────────────────


@app.get("/chat/open")
@limiter.limit("60/minute")
async def open_chat(
    request: fastapi.Request,
    with_id: str,
    current_user: dict = Depends(get_current_user),
):
    my_id = current_user["sub"]
    row = conn.execute("SELECT id FROM members WHERE id=?", (with_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    chat_id = make_p2p_chat(my_id, with_id)
    return {"chat_id": chat_id}


@app.get("/my/chats")
@limiter.limit("60/minute")
async def my_chats(
    request: fastapi.Request, current_user: dict = Depends(get_current_user)
):
    my_id = current_user["sub"]
    rows = cursor.execute(
        """
        SELECT c.chat_id, c.other_id, m.name
        FROM chats c
        LEFT JOIN members m ON m.id = c.other_id
        WHERE c.user_id = ?
        """,
        (my_id,),
    ).fetchall()

    result = []
    for row in rows:
        chat_id, other_id, other_name = row["chat_id"], row["other_id"], row["name"]
        history = get_p2p_history(chat_id, limit=1)
        last_msg = None
        if history:
            last_msg = {
                "text": history[-1]["text"],
                "timestamp": history[-1]["timestamp"],
                "sender_id": history[-1]["sender_id"],
            }
        result.append(
            {
                "chat_id": chat_id,
                "other_id": other_id,
                "other_name": other_name or other_id[:8],
                "last_message": last_msg,
            }
        )

    result.sort(
        key=lambda x: x["last_message"]["timestamp"] if x["last_message"] else "",
        reverse=True,
    )
    return {"chats": result}


@app.get("/chat/{chat_id}")
@limiter.limit("60/minute")
async def get_p2p_chat(
    request: fastapi.Request,
    chat_id: str,
    count: int = 100,
    before_id: int | None = None,
    current_user: dict = Depends(get_current_user),
):
    row = cursor.execute(
        "SELECT 1 FROM chats WHERE chat_id=? AND user_id=?",
        (chat_id, current_user["sub"]),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Not a member of this chat")

    messages = get_p2p_history(chat_id, limit=count, before_id=before_id)
    return {"messages": messages}


@app.post("/chat/{chat_id}/")
@limiter.limit("60/minute")
async def send_p2p_msg(
    chat_id: str,
    request: fastapi.Request,
    current_user: dict = Depends(get_current_user),
):
    """Body JSON: { "text": "...", "attachments": [...] }"""
    sender_id = current_user["sub"]

    membership = cursor.execute(
        "SELECT 1 FROM chats WHERE chat_id=? AND user_id=?", (chat_id, sender_id)
    ).fetchone()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this chat")

    row = conn.execute("SELECT name FROM members WHERE id=?", (sender_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Unknown sender")

    body = await request.json()
    text = body.get("text", "").strip()
    attachments: list[dict] = body.get("attachments") or []

    if not text and not attachments:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="Message too long")

    msg = save_p2p_msg(chat_id, sender_id, row["name"], text, attachments)

    dead = []
    for ws in p2p_clients.get(chat_id, []):
        try:
            await ws.send_json({"type": "message", "message": msg})
        except Exception:
            dead.append(ws)
    for ws in dead:
        p2p_clients[chat_id].remove(ws)

    return {"ok": True}


@app.websocket("/ws/chat/{chat_id}")
async def p2p_ws(chat_id: str, ws: WebSocket):
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001)
        return
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401)
    except HTTPException:
        await ws.close(code=4001)
        return

    user_id = payload["sub"]
    row = cursor.execute(
        "SELECT 1 FROM chats WHERE chat_id=? AND user_id=?", (chat_id, user_id)
    ).fetchone()
    if not row:
        await ws.close(code=4003)
        return

    await ws.accept()
    p2p_clients.setdefault(chat_id, []).append(ws)
    try:
        await ws.send_json({"type": "history", "messages": get_p2p_history(chat_id)})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if chat_id in p2p_clients and ws in p2p_clients[chat_id]:
            p2p_clients[chat_id].remove(ws)


# ── FILE SERVING ──────────────────────────────────────────────────────────


async def __default_get_content(
    entry_id: str | None, folder: str, ttype: Literal["Image", "Audio", "Video", "File"]
) -> FileResponse:

    if entry_id is None:
        raise HTTPException(404, f"{ttype} not found")

    path_to = os.path.join(folder, entry_id)
    real_folder = os.path.realpath(folder)
    if not os.path.isfile(path_to):
        raise HTTPException(404, f"{ttype} not found")
    if not os.path.realpath(path_to).startswith(real_folder):
        raise HTTPException(404, f"{ttype} not found")

    mime, _ = mimetypes.guess_type(entry_id)
    media_type = mime or "application/octet-stream"
    url = URL_PREFIXES[ttype.lower()] + "/" + entry_id
    filename = cursor.execute(
        "SELECT original_name FROM message_attachments WHERE url = ?", (url,)
    ).fetchone()

    if filename is None:
        raise HTTPException(404, "Requested file not found")

    filename = filename["original_name"]

    return FileResponse(
        path_to,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={quote(filename)};"},
    )


@app.get("/img/{img_id}", response_class=FileResponse)
@limiter.limit("60/minute")
async def get_image(request: fastapi.Request, img_id: str | None = None):
    return await __default_get_content(img_id, USER_IMAGES_FLD, "Image")


@app.get("/audio/{audio_id}", response_class=FileResponse)
@limiter.limit("60/minute")
async def get_audio(request: fastapi.Request, audio_id: str | None = None):
    return await __default_get_content(audio_id, USER_AUDIO_FLD, "Audio")


@app.get("/video/{video_id}", response_class=FileResponse)
@limiter.limit("60/minute")
async def get_video(request: fastapi.Request, video_id: str | None = None):
    return await __default_get_content(video_id, USER_VIDEO_FLD, "Video")


@app.get("/file/{file_id}")
@limiter.limit("60/minute")
async def get_file(request: fastapi.Request, file_id: str | None = None):
    return await __default_get_content(file_id, USER_FILES_FLD, "File")


# ── FILE UPLOAD ───────────────────────────────────────────────────────────


def _get_category(ext: str) -> str:
    for category, exts in ALLOWED_EXTENSIONS.items():
        if ext in exts:
            return category
    return "file"


@app.post("/upload")
@limiter.limit("20/minute")
async def upload_file(
    request: fastapi.Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    original_name = file.filename or "file"
    ext = os.path.splitext(original_name)[1].lower()
    if not ext:
        raise HTTPException(400, "Cannot determine file extension")

    mime, _ = mimetypes.guess_type(original_name)
    mime = mime or "application/octet-stream"

    category = _get_category(ext)
    max_size = MAX_SIZES[category]

    data = await file.read(max_size + 1)
    if len(data) > max_size:
        raise HTTPException(413, f"File too large (max {max_size // 1024 // 1024} MB)")

    file_id = sha256(data).hexdigest() + ext
    folder = FOLDERS[category]

    path = os.path.join(folder, file_id)

    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)

    url = f"{URL_PREFIXES[category]}/{file_id}"

    return {
        "ok": True,
        "file_id": file_id,
        "url": url,
        "category": category,
        "mime": mime,
        "original_name": original_name,
    }


if __name__ == "__main__":
    make_environ()
    uvicorn.run(app, host="0.0.0.0", port=80)
