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
from fastapi.responses import HTMLResponse

app = fastapi.FastAPI()

HEAD = "OLEG.TXT"
GLOBAL_CHAT_FOLDER = os.path.join(os.curdir, "global_chat")

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


if __name__ == "__main__":

    make_environ()

    uvicorn.run(app, host="0.0.0.0", port=80)
