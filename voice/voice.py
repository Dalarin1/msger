from flask import Flask, send_file, request
from flask_socketio import SocketIO, join_room, emit

app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    allow_upgrades=True,
    engineio_logger=False
)

# room -> set of session ids
rooms = {}
# sid -> room
sid_to_room = {}

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

    join_room(room)

    if room not in rooms:
        rooms[room] = set()
    rooms[room].add(sid)
    sid_to_room[sid] = room

    count = len(rooms[room])
    print(f"JOIN {room} sid={sid} count={count}")

    emit("room-state", {"count": count}, to=room)

    if count >= 2:
        emit("user-joined", {}, to=room, include_self=False)

@socketio.on("signal")
def on_signal(data):
    emit("signal", data, to=data["room"], include_self=False)

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    room = sid_to_room.pop(sid, None)
    if room and room in rooms:
        rooms[room].discard(sid)
        count = len(rooms[room])
        print(f"DISCONNECT {sid} room={room} count={count}")
        if count == 0:
            del rooms[room]
        else:
            emit("room-state", {"count": count}, to=room)

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=8080,
        allow_unsafe_werkzeug=True,
        ssl_context=("voice/cert.pem", "voice/key.pem")
    )