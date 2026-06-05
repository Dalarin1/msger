from flask import Flask, send_file, request
from flask_socketio import SocketIO, join_room, emit, leave_room

app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    allow_upgrades=True,
    engineio_logger=False
)

rooms = {}          # room -> set(sid)
sid_to_room = {}    # sid -> room

MAX_USERS = 2


@app.route("/")
def index():
    return send_file("voice.html")


@app.route("/socket.io.min.js")
def serve_socketio():
    return send_file("socket.io.min.js")


@socketio.on("join")
def on_join(data):
    sid = request.sid
    room = data["room"]

    if room not in rooms:
        rooms[room] = set()

    # ❗ проверка ДО добавления
    if len(rooms[room]) >= MAX_USERS:
        emit("room-full", {})
        print(f"REJECT {sid} room={room} FULL")
        return

    join_room(room)

    rooms[room].add(sid)
    sid_to_room[sid] = room

    count = len(rooms[room])

    print(f"JOIN {room} sid={sid} count={count}")

    emit("room-users", list(rooms[room]), to=room)


@socketio.on("signal")
def on_signal(data):
    emit("signal", data, to=data["room"], include_self=False)


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    room = sid_to_room.pop(sid, None)

    if not room:
        return

    if room in rooms:
        rooms[room].discard(sid)

        if len(rooms[room]) == 0:
            del rooms[room]
        else:
            emit("room-users", list(rooms[room]), to=room)
            emit("user-left", {"sid": sid}, to=room)

        leave_room(room)


if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=8080,
        allow_unsafe_werkzeug=True,
        ssl_context=("voice/cert.pem", "voice/key.pem")
    )