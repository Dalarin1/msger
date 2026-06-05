import fastapi
import uvicorn
import json
import hashlib
import random
import sqlite3
import uuid
import os

from pathlib import Path
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

app = fastapi.FastAPI()

HEAD = "OLEG.TXT"
GLOBAL_CHAT_FOLDER = os.path.join(os.curdir, "global_chat")
P2P_CHATS_FOLDER = os.path.join(os.curdir, "personal_chats")
conn = sqlite3.connect("members.db")
cursor = conn.cursor()
clients = []


def make_environ() -> None:
    if os.name == "nt":
        os.system("")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id TEXT PRIMARY KEY,
        name TEXT,
        created_at TEXT
    )""")

    conn.commit()

    if not os.path.exists(HEAD):
        with open(HEAD, "w") as f:
            f.write("")
    
    if not os.path.exists(GLOBAL_CHAT_FOLDER):
        os.mkdir(GLOBAL_CHAT_FOLDER)

    if not os.path.exists(P2P_CHATS_FOLDER):
        os.mkdir(P2P_CHATS_FOLDER)


def get_last_global_msg_hash() -> str:
    if os.path.exists(HEAD):
        with open(HEAD, "r") as f:
            return f.readline().strip()
    else:
        with open(HEAD, "w"):
            return ""


@app.get("/register")
async def register(reqv: fastapi.Request, name: str):
    new_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO members (id, name, created_at) VALUES (?, ?, ?)",
        (new_id, name, datetime.now().isoformat()),
    )
    conn.commit()
    return {"id": new_id, "name": name}


def get_history(limit=100):
    msgs = []

    if not os.path.exists(HEAD):
        return msgs

    curhash = get_last_global_msg_hash()

    while len(msgs) < limit:

        if not curhash:
            break

        if not os.path.exists(os.path.join(GLOBAL_CHAT_FOLDER, curhash)):
            break

        with open(os.path.join(GLOBAL_CHAT_FOLDER, curhash), "r") as f:
            data = json.load(f)

        msgs.append(data)

        curhash = data.get("prev", "").strip()

    msgs.reverse()

    return msgs


@app.get("/send_msg")
async def send_msg(reqv: fastapi.Request, text: str, id: str):
    row = cursor.execute("SELECT name FROM members WHERE id = ?", (id,)).fetchone()

    if not row:
        return {"type": "register"}

    sender_name = row[0]

    last = ""

    last = get_last_global_msg_hash()

    msg = {
        "sender": sender_name,
        "sender_id": id,
        "id": id,
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "rnd": random.randint(0, 1024),
        "prev": last,
    }

    raw = json.dumps(msg)

    hsh = hashlib.sha1(raw.encode("utf-8")).hexdigest()

    with open(os.path.join(GLOBAL_CHAT_FOLDER, hsh), "w") as f:
        f.write(raw)

    with open(HEAD, "w") as f:
        f.write(hsh)

    dead = []

    for client in clients:

        try:
            await client.send_json({"type": "message", "message": msg})

        except:
            dead.append(client)

    for client in dead:
        if client in clients:
            clients.remove(client)

    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):

    await ws.accept()

    clients.append(ws)

    try:

        await ws.send_json({"type": "history", "messages": get_history()})

        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        pass

    finally:

        if ws in clients:
            clients.remove(ws)


@app.get("/", response_class=HTMLResponse)
async def get_index():

    path = Path(__file__).parent / "index.html"

    return path.read_text(encoding="utf-8")

# chat_id -> list of websockets
p2p_clients: dict[str, list[WebSocket]] = {}


def get_chat_dir(chat_id: str) -> str:
    return os.path.join(P2P_CHATS_FOLDER, chat_id)


def get_p2p_history(chat_id: str, limit: int = 100) -> list:
    msgs = []
    dirpath = get_chat_dir(chat_id)
    headpath = os.path.join(dirpath, "head.txt")

    if not os.path.exists(headpath):
        return msgs

    with open(headpath, "r") as f:
        curhash = f.readline().strip()

    while len(msgs) < limit:
        if not curhash:
            break

        msgpath = os.path.join(dirpath, curhash)
        if not os.path.exists(msgpath):
            break

        with open(msgpath, "r") as f:
            data = json.load(f)

        msgs.append(data)
        curhash = data.get("prev", "").strip()

    msgs.reverse()
    return msgs


def make_chat(id_1: str, id_2: str) -> str:
    # детерминированный chat_id — одинаковый для обоих порядков
    key = "".join(sorted([id_1, id_2]))
    chat_id = hashlib.sha1(key.encode()).hexdigest()
    dirpath = get_chat_dir(chat_id)

    if not os.path.exists(dirpath):
        os.makedirs(dirpath)
        with open(os.path.join(dirpath, "head.txt"), "w") as f:
            f.write("")

    return chat_id


@app.get("/chat/open")
async def open_chat(with_id: str, request: fastapi.Request):
    """Создаёт (или находит существующий) чат между двумя юзерами, возвращает chat_id"""
    my_id = request.headers.get("X-User-Id")
    if not my_id:
        raise fastapi.HTTPException(status_code=400, detail="Missing X-User-Id header")

    row = cursor.execute("SELECT id FROM members WHERE id = ?", (with_id,)).fetchone()
    if not row:
        raise fastapi.HTTPException(status_code=404, detail="User not found")

    chat_id = make_chat(my_id, with_id)
    return {"chat_id": chat_id}


@app.get("/chat/{chat_id}")
async def get_personal_chat(chat_id: str, count: int = 100, from_hash: str | None = None):
    dirpath = get_chat_dir(chat_id)
    if not os.path.exists(dirpath):
        raise fastapi.HTTPException(status_code=404, detail="Chat not found")

    if from_hash:
        # догрузка истории начиная с конкретного сообщения
        msgs = []
        curhash = from_hash
        while len(msgs) < count:
            if not curhash:
                break
            msgpath = os.path.join(dirpath, curhash)
            if not os.path.exists(msgpath):
                break
            with open(msgpath, "r") as f:
                data = json.load(f)
            msgs.append(data)
            curhash = data.get("prev", "").strip()
        msgs.reverse()
        return {"messages": msgs}

    return {"messages": get_p2p_history(chat_id, limit=count)}


@app.post("/chat/{chat_id}/")
async def send_p2p_msg(chat_id: str, request: fastapi.Request):
    sender_id = request.headers.get("X-User-Id")
    if not sender_id:
        raise fastapi.HTTPException(status_code=400, detail="Missing X-User-Id header")

    row = cursor.execute("SELECT name FROM members WHERE id = ?", (sender_id,)).fetchone()
    if not row:
        raise fastapi.HTTPException(status_code=403, detail="Unknown sender")

    dirpath = get_chat_dir(chat_id)
    if not os.path.exists(dirpath):
        raise fastapi.HTTPException(status_code=404, detail="Chat not found")

    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise fastapi.HTTPException(status_code=400, detail="Empty message")

    headpath = os.path.join(dirpath, "head.txt")
    with open(headpath, "r") as f:
        last = f.readline().strip()

    msg = {
        "sender": row[0],
        "sender_id": sender_id,
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "rnd": random.randint(0, 1024),
        "prev": last,
    }

    raw = json.dumps(msg)
    hsh = hashlib.sha1(raw.encode()).hexdigest()

    with open(os.path.join(dirpath, hsh), "w") as f:
        f.write(raw)

    with open(headpath, "w") as f:
        f.write(hsh)

    # рассылаем только участникам этого чата
    dead = []
    for ws in p2p_clients.get(chat_id, []):
        try:
            await ws.send_json({"type": "message", "message": msg})
        except:
            dead.append(ws)

    for ws in dead:
        p2p_clients[chat_id].remove(ws)

    return {"ok": True}


@app.websocket("/ws/chat/{chat_id}")
async def p2p_ws(chat_id: str, ws: WebSocket):
    dirpath = get_chat_dir(chat_id)
    if not os.path.exists(dirpath):
        await ws.close(code=4004)
        return

    await ws.accept()
    p2p_clients.setdefault(chat_id, []).append(ws)

    try:
        await ws.send_json({
            "type": "history",
            "messages": get_p2p_history(chat_id)
        })

        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        pass

    finally:
        if chat_id in p2p_clients and ws in p2p_clients[chat_id]:
            p2p_clients[chat_id].remove(ws)


@app.get("/chat", response_class=HTMLResponse)
async def get_chat_html():
    return HTMLResponse(open("chat.html").read())
if __name__ == "__main__":

    make_environ()

    uvicorn.run(app, host="0.0.0.0", port=80)
