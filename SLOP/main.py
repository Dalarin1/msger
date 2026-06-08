import uuid
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import socketio

# --- Socket.IO + FastAPI setup ---
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI()
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Serve static files (our HTML/JS client)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- In-memory room storage ---
# rooms = { room_id: { socket_id: { "name": str } } }
rooms: dict[str, dict[str, dict]] = {}


@app.get("/")
async def index():
    with open("static/index.html") as f:
        return HTMLResponse(f.read())


@app.get("/api/rooms")
async def list_rooms():
    """Показать все активные комнаты (для дебага)"""
    return {
        room_id: {
            "participants": len(users),
            "users": list(users.keys())
        }
        for room_id, users in rooms.items()
    }


# ─────────────────────────────────────────────
#  Socket.IO события
# ─────────────────────────────────────────────

@sio.event
async def connect(sid, environ):
    print(f"[+] Connected: {sid}")


@sio.event
async def disconnect(sid):
    """Пользователь отключился — убрать из всех комнат"""
    print(f"[-] Disconnected: {sid}")

    for room_id, users in list(rooms.items()):
        if sid in users:
            del users[sid]
            # Уведомить остальных участников
            await sio.emit("user_left", {"sid": sid}, room=room_id, skip_sid=sid)
            print(f"    Removed {sid} from room {room_id}")

            # Удалить пустую комнату
            if not users:
                del rooms[room_id]
                print(f"    Room {room_id} deleted (empty)")
            break


@sio.event
async def join_room(sid, data):
    """
    Клиент хочет войти в комнату.
    data = { "room_id": str, "name": str }
    """
    room_id = data.get("room_id", "").strip()
    name = data.get("name", f"User-{sid[:4]}")

    if not room_id:
        await sio.emit("error", {"message": "room_id is required"}, to=sid)
        return

    # Создать комнату если не существует
    if room_id not in rooms:
        rooms[room_id] = {}

    # Получить список уже подключённых (ДО добавления нового)
    existing_users = [
        {"sid": s, "name": info["name"]}
        for s, info in rooms[room_id].items()
    ]

    # Добавить нового участника
    rooms[room_id][sid] = {"name": name}
    await sio.enter_room(sid, room_id)

    print(f"[Room {room_id}] {name} ({sid}) joined. Total: {len(rooms[room_id])}")

    # Отправить новому участнику список существующих (чтобы он инициировал offer)
    await sio.emit("room_joined", {
        "room_id": room_id,
        "your_sid": sid,
        "existing_users": existing_users
    }, to=sid)

    # Уведомить всех остальных о новом участнике
    await sio.emit("user_joined", {
        "sid": sid,
        "name": name
    }, room=room_id, skip_sid=sid)


@sio.event
async def webrtc_offer(sid, data):
    """
    Переслать WebRTC offer конкретному пиру.
    data = { "target_sid": str, "sdp": str }
    """
    target = data.get("target_sid")
    if target:
        await sio.emit("webrtc_offer", {
            "from_sid": sid,
            "sdp": data["sdp"]
        }, to=target)


@sio.event
async def webrtc_answer(sid, data):
    """
    Переслать WebRTC answer.
    data = { "target_sid": str, "sdp": str }
    """
    target = data.get("target_sid")
    if target:
        await sio.emit("webrtc_answer", {
            "from_sid": sid,
            "sdp": data["sdp"]
        }, to=target)


@sio.event
async def ice_candidate(sid, data):
    """
    Переслать ICE-кандидата.
    data = { "target_sid": str, "candidate": object }
    """
    target = data.get("target_sid")
    if target:
        await sio.emit("ice_candidate", {
            "from_sid": sid,
            "candidate": data["candidate"]
        }, to=target)


# ─────────────────────────────────────────────
#  Запуск
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn, os
    os.system("")
    uvicorn.run(socket_app, host="0.0.0.0", port=8000)