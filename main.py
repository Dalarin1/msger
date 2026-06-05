from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pathlib import Path

from datetime import datetime
import random

app = FastAPI()

clients = []
messages = []


@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent / "index.html").read_text(
        encoding="utf-8"
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):

    await ws.accept()
    clients.append(ws)

    try:

        await ws.send_json({
            "type": "history",
            "messages": messages
        })

        while True:

            data = await ws.receive_json()

            msg = {
                "sender": data.get("sender", "unknown"),
                "text": data["text"],
                "timestamp": datetime.now().isoformat(),
                "rnd": random.randint(0, 1024)
            }

            messages.append(msg)

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

    except WebSocketDisconnect:
        if ws in clients:
            clients.remove(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=80
    )