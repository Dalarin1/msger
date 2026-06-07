from flask import Flask, send_file, request
from flask_socketio import SocketIO, join_room, emit, leave_room
import logging
from gevent.pywsgi import WSGIServer
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="gevent",
    logger=False,
    engineio_logger=False,
)

# room_id -> { users: [sid, ...], offerer: sid|None }
rooms: dict = {}
# sid -> room_id
sid_room: dict = {}

MAX_USERS = 2


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file("voice.html")

@app.route("/socket.io.min.js")
def serve_socketio():
    return send_file("socket.io.min.js")


# ── helpers ───────────────────────────────────────────────────────────────────

def _state(room_id: str) -> dict:
    """Сериализуемое состояние комнаты для клиентов."""
    r = rooms.get(room_id, {})
    return {"users": list(r.get("users", [])), "offerer": r.get("offerer")}


def _remove(sid: str, room_id: str | None) -> None:
    sid_room.pop(sid, None)
    if not room_id or room_id not in rooms:
        return

    r = rooms[room_id]
    if sid not in r["users"]:
        return

    r["users"].remove(sid)
    leave_room(room_id, sid=sid)

    if not r["users"]:
        del rooms[room_id]
        print(f"[room] {room_id} deleted")
        return

    if r["offerer"] == sid:
        r["offerer"] = r["users"][0]

    print(f"[room] {room_id} leave={sid} remaining={r['users']} offerer={r['offerer']}")
    emit("room-state", _state(room_id), to=room_id)
    emit("user-left",  {"sid": sid},    to=room_id)


# ── socket events ─────────────────────────────────────────────────────────────

@socketio.on("join")
def on_join(data):
    sid     = request.sid
    room_id = str(data.get("room", "")).strip()
    if not room_id:
        return

    if room_id not in rooms:
        rooms[room_id] = {"users": [], "offerer": None}

    r = rooms[room_id]
    if len(r["users"]) >= MAX_USERS:
        emit("room-full", {})
        print(f"[room] {room_id} FULL — rejected {sid}")
        return

    join_room(room_id)
    r["users"].append(sid)
    sid_room[sid] = room_id

    if r["offerer"] is None:
        r["offerer"] = sid

    print(f"[room] {room_id} join={sid} n={len(r['users'])} offerer={r['offerer']}")
    # Шлём state всем в комнате — каждый клиент сам решает, слать offer или ждать
    emit("room-state", _state(room_id), to=room_id)


@socketio.on("signal")
def on_signal(data):
    room_id = data.get("room")
    if room_id:
        emit("signal", data, to=room_id, include_self=False)


@socketio.on("leave")
def on_leave(data):
    _remove(request.sid, data.get("room") or sid_room.get(request.sid))


@socketio.on("disconnect")
def on_disconnect():
    _remove(request.sid, sid_room.get(request.sid))


# ── entry ─────────────────────────────────────────────────────────────────────

# Стало:

if __name__ == "__main__":
    http_server = WSGIServer(
        ("0.0.0.0", 8080),
        app,
        keyfile="key.pem",
        certfile="cert.pem",
        handler_class=WebSocketHandler,
    )
    http_server.serve_forever()