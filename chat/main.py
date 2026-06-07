import fastapi
import uvicorn
import hashlib
import sqlite3
import uuid
import jwt
import os

from datetime import datetime, timedelta, timezone
from fastapi import WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

#    CONFIG
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-please")
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FOLDER = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DATABASE_FOLDER, "app.db")
MAKE_TABLES_SCRIPT_PATH = os.path.join(BASE_DIR, "make_tables.sqlite3")

app = fastapi.FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=False)

conn: sqlite3.Connection | None = None
cursor: sqlite3.Cursor | None = None


def make_environ() -> None:
    global conn, cursor

    if os.name == "nt":
        os.system("")

    os.makedirs(DATABASE_FOLDER, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )  # вроде позволяет делать многопоточных чтецов, но не уверен
    conn.execute(
        "PRAGMA synchronous=NORMAL"
    )  # меньше синхронизаций по сравнению с EXTRA / FULL
    conn.execute("PRAGMA foreign_keys=ON")  # включаем отношения между таблицами

    cursor = conn.cursor()

    with open(MAKE_TABLES_SCRIPT_PATH, "r") as script:
        cursor.executescript(script.read())

    conn.commit()


#  JWT


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_token(user_id: str):
    now = _now_utc()
    data = {
        "iss": "oleg-chat-jwt-vendor",  # издатель токена (issuer)
        "type": "access",
        "sub": user_id,  # чей токен (subject)
        "iat": now,  # дата издания токена (issued at)
        "exp": now
        + ACCESS_TOKEN_TTL,  # дата истечения валидности токена (Expiration time)
    }
    return jwt.encode(data, SECRET_KEY, ALGORITHM)


def create_refresh_token(user_id: str):
    jti = str(uuid.uuid4())
    expires_at = _now_utc() + REFRESH_TOKEN_TTL
    data = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iat": _now_utc(),
        "exp": expires_at,
    }
    token = jwt.encode(data, SECRET_KEY, ALGORITHM)

    cursor.execute(
        "INSERT INTO refresh_tokens (jti, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
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
    cursor.execute("UPDATA refresh_tokens SET revoked = 1 WHERE jti=?", (jti,))
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


#    HELPERS


def _row_to_msg(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "sender": row["sender"],
        "sender_id": row["sender_id"],
        "text": row["text"],
        "timestamp": row["timestamp"],
    }


def get_global_history(limit: int = 100, before_id: int | None = None) -> list[dict]:
    if before_id:  # подгружаем историю чата после N-ного соо.
        cursor.execute(
            "SELECT id, sender, sender_id, text, timestamp  FROM global_messages WHERE id < ? ORDER BY id DESC LIMIT ?",
            (before_id, limit),
        )
    else:  # грузим последние 100
        cursor.execute(
            "SELECT id, sender, sender_id, text, timestamp  FROM global_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    return [_row_to_msg(i) for i in reversed(cursor.fetchall())]


def save_global_msg(sender_id: str, sender: str, text: str) -> dict:
    ts = _now_utc().isoformat()
    cur = conn.execute(
        "INSERT INTO global_messages (sender_id, sender, text, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (sender_id, sender, text, ts),
    )
    conn.commit()
    return {
        "id": cur.lastrowid,
        "sender": sender,
        "sender_id": sender_id,
        "text": text,
        "timestamp": ts,
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
    return [_row_to_msg(i) for i in reversed(cursor.fetchall())]


def save_p2p_msg(chat_id: str, sender_id: str, sender: str, text: str) -> dict:
    ts = _now_utc().isoformat()
    cursor.execute(
        "INSERT INTO p2p_messages (chat_id, sender_id, sender, text, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, sender_id, sender, text, ts),
    )
    conn.commit()
    return {
        "id": cursor.lastrowid,
        "chat_id": chat_id,
        "sender": sender,
        "sender_id": sender_id,
        "text": text,
        "timestamp": ts,
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


# ---------------------------------------------------------------------------
# WebSocket-клиенты
# ---------------------------------------------------------------------------

global_clients: list[WebSocket] = []
p2p_clients: dict[str, list[WebSocket]] = {}

# STATIC


@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTMLResponse(open("index.html").read())


@app.get("/sha256.js")
async def get_sha256():
    return FileResponse("sha256.js", media_type="application/javascript")


@app.get("/chat", response_class=HTMLResponse)
async def get_chat_html():
    return HTMLResponse(open("chat.html").read())


@app.get("/chat/", response_class=HTMLResponse)
async def get_chat_html_2():
    return HTMLResponse(open("chat.html").read())


@app.get("/profile", response_class=HTMLResponse)
async def get_profile_html():
    return HTMLResponse(open("profile.html").read())


@app.get("/login")
async def get_login_page():
    return HTMLResponse(open("login.html").read())


# Авторизация


@app.post("/auth/register")
async def register(request: fastapi.Request) -> dict:
    """
    Заголовки:
      oleg-password-hash  — sha256(login + password), уникальный ключ
      oleg-name        — отображаемое имя
    Возвращает access_token + refresh_token.
    """
    password_hash = request.headers.get("oleg-login-hash")
    username = request.headers.get("oleg-name")
    if not password_hash:
        raise HTTPException(status_code=400, detail="oleg-login-hash header missing")

    existing = cursor.execute(
        "SELECT id FROM members WHERE password_hash = ?", (password_hash,)
    ).fetchone()

    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user_id = str(uuid.uuid4())

    cursor.execute(
        "INSERT INTO members (id, password_hash, name, created_at) VALUES (?, ?, ?, ?)",
        (user_id, password_hash, username, _now_utc().isoformat()),
    )
    conn.commit()

    return {
        "ok": True,
        "id": user_id,
        "access_token": create_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
    }


@app.post("/auth/login")
async def login(request: fastapi.Request) -> dict:
    """
    Заголовок:
      oleg-password-hash  — sha256(login + password)
    Возвращает access_token + refresh_token.
    """
    password_hash = request.headers.get("oleg-password-hash")
    if not password_hash:
        raise HTTPException(400, "oleg-password-hash missing")

    row = cursor.execute(
        "SELECT id FROM members WHERE password_hash = ?", (password_hash,)
    ).fetchone()
    if not row:
        raise HTTPException(401, "Wrong login or password")

    user_id = row["id"]
    return {
        "ok": True,
        "id": user_id,
        "access_token": create_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
    }


@app.post("/auth/refresh")
async def refresh_tokens(request: fastapi.Request) -> dict:
    """
    Body JSON: { "refresh_token": "..." }
    Возвращает новый access_token. Refresh-токен остаётся тем же.
    (Можно сделать rotation — менять и refresh тоже — раскомментив строки ниже.)
    """

    body = await request.json()
    token = body.get("refresh_token", "")
    payload = decode_token(token)

    if payload.get("type") != "refresh":
        raise HTTPException(401, 'Wrong type, must be "refresh"')

    row = cursor.execute(
        "SELECT expired_at FROM refresh_tokens WHERE jti = ?", (token,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Token not found")
    if row["revoked"]:
        raise HTTPException(status_code=401, detail="Token revoked")

    user_id = row["user_id"]

    # --- Rotation (опционально) ---
    # conn.execute("UPDATE refresh_tokens SET revoked=1 WHERE jti=?", (jti,))
    # new_refresh = create_refresh_token(user_id)

    return {
        "access_token": create_token(user_id),
        # "refresh_token": new_refresh,  # при rotation
        "token_type": "bearer",
    }


@app.post("/auth/logout")
async def logout(
    request: fastapi.Request, current_user: dict = Depends(get_current_user)
) -> dict:
    body = await request.json()
    token = body.get("refresh_token", "")
    try:
        payload = decode_token(token)
        jti = str(payload.get("jti"))
        revoke_token(jti)
    except:
        pass
    return {"ok": True}


@app.post("/auth/logout_all")
async def logout_all(current_user: dict = Depends(get_current_user)) -> dict:
    """Инвалидирует все refresh-токены пользователя (выход на всех устройствах)."""
    cursor.execute(
        "UPDATE refresh_tokens SET revoked=1 WHERE user_id=?",
        (current_user["sub"],),
    )
    conn.commit()
    return {"ok": True}


# GLOBAL CHAT


@app.post("/send_msg")
async def send_msg(
    request: fastapi.Request,
    current_user: dict = Depends(get_current_user),
):
    """Body JSON: { "text": "..." }"""
    body = await request.json()
    text = body.get("text", "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Empty message")

    user_id = current_user["sub"]
    row = cursor.execute("SELECT name FROM members WHERE id = ?", (user_id,)).fetchone()

    if not row:
        raise HTTPException(403, "Username not found")

    msg = save_global_msg(user_id, row["name"], text)
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


# P2P CHATS


@app.get("/chat/open")
async def open_chat(
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
async def my_chats(current_user: dict = Depends(get_current_user)):
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
async def get_p2p_chat(
    chat_id: str,
    count: int = 100,
    before_id: int | None = None,
    current_user: dict = Depends(get_current_user),
):
    # Проверяем, что юзер — участник чата
    row = cursor.execute(
        "SELECT 1 FROM chats WHERE chat_id=? AND user_id=?",
        (chat_id, current_user["sub"]),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Not a member of this chat")

    messages = get_p2p_history(chat_id, limit=count, before_id=before_id)
    return {"messages": messages}


@app.post("/chat/{chat_id}/")
async def send_p2p_msg(
    chat_id: str,
    request: fastapi.Request,
    current_user: dict = Depends(get_current_user),
):
    sender_id = current_user["sub"]

    # Проверяем членство
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
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")

    msg = save_p2p_msg(chat_id, sender_id, row["name"], text)

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
    # Токен передаётся query-параметром, т.к. браузерный WebSocket не поддерживает заголовки
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


if __name__ == "__main__":

    make_environ()
    uvicorn.run(app, host="0.0.0.0", port=80)
