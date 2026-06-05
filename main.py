import fastapi
import uvicorn
import json
import hashlib
import random
import os

from pathlib import Path
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = fastapi.FastAPI()

HEAD = "OLEG.TXT"

clients = []


def get_history(limit=100):
    msgs = []

    if not os.path.exists(HEAD):
        return msgs

    with open(HEAD, "r") as f:
        curhash = f.readline().strip()

    while len(msgs) < limit:

        if not curhash:
            break

        if not os.path.exists(curhash):
            break

        with open(curhash, "r") as f:
            data = json.load(f)

        msgs.append(data)

        curhash = data.get("prev", "").strip()

    msgs.reverse()

    return msgs


@app.get("/send_msg")
async def send_msg(reqv: fastapi.Request, text: str, id: str):

    last = ""

    if os.path.exists(HEAD):
        with open(HEAD, "r") as f:
            last = f.readline().strip()

    msg = {
        "sender": reqv.client.host,
        "id" : id,
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "rnd": random.randint(0, 1024),
        "prev": last
    }

    raw = json.dumps(msg)

    hsh = hashlib.sha1(
        raw.encode("utf-8")
    ).hexdigest()

    with open(hsh, "w") as f:
        f.write(raw)

    with open(HEAD, "w") as f:
        f.write(hsh)

    dead = []

    for client in clients:

        try:
            await client.send_json({
                "type": "message",
                "message": msg
            })

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

        await ws.send_json({
            "type": "history",
            "messages": get_history()
        })

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

    return path.read_text(
        encoding="utf-8"
    )


if __name__ == "__main__":

    if not os.path.exists(HEAD):

        with open(HEAD, "w") as f:
            f.write("")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=80
    )