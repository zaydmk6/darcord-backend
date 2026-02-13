import sqlite3, jwt, datetime, os, random, string, bcrypt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

SECRET_KEY = "CHANGE_THIS_SECRET_NOW"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== FILES =====
os.makedirs("avatars", exist_ok=True)
app.mount("/avatars", StaticFiles(directory="avatars"), name="avatars")

# ===== DATABASE =====
db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password BLOB, avatar TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS status (username TEXT, state TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS servers (id INTEGER PRIMARY KEY, name TEXT, owner TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS members (server_id INTEGER, username TEXT, role TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS messages (channel_id INTEGER, username TEXT, content TEXT, timestamp TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS voice_rooms (id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT)")
db.commit()

# ===== JWT =====
def create_token(username):
    return jwt.encode({
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, SECRET_KEY, algorithm="HS256")

def verify_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])["username"]
    except:
        return None

# ===== PASSWORD =====
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed)

# ===== AUTH =====
@app.post("/register")
def register(data: dict):
    try:
        hashed = hash_password(data["password"])
        cursor.execute("INSERT INTO users VALUES (NULL,?,?,?)",
                       (data["username"], hashed, ""))
        db.commit()
        return {"status": "ok"}
    except:
        return {"error": "exists"}

@app.post("/login")
def login(data: dict):
    cursor.execute("SELECT password FROM users WHERE username=?",
                   (data["username"],))
    row = cursor.fetchone()

    if row and verify_password(data["password"], row[0]):
        token = create_token(data["username"])
        return {"token": token}

    return {"error": "invalid"}

# ===== CREATE VOICE ROOM =====
@app.post("/create_voice_room")
def create_voice_room(data:dict):
    user = verify_token(data["token"])
    if not user:
        return {"error":"unauthorized"}

    cursor.execute("INSERT INTO voice_rooms VALUES (NULL,?,?)",
                   (data["server_id"], data["name"]))
    db.commit()
    return {"status":"created"}

# ===== WEBSOCKET VOICE ROOM =====
voice_rooms_ws = {}

@app.websocket("/ws/voice/{room_id}")
async def voice_ws(ws: WebSocket, room_id:int):
    await ws.accept()
    username = None

    voice_rooms_ws.setdefault(room_id, [])

    try:
        while True:
            data = await ws.receive_json()
            username = verify_token(data.get("token"))

            if username and ws not in voice_rooms_ws[room_id]:
                voice_rooms_ws[room_id].append(ws)

            for client in voice_rooms_ws[room_id]:
                if client != ws:
                    await client.send_json({
                        "type": data["type"],
                        "from": username,
                        "offer": data.get("offer"),
                        "answer": data.get("answer"),
                        "candidate": data.get("candidate")
                    })

    except WebSocketDisconnect:
        if ws in voice_rooms_ws[room_id]:
            voice_rooms_ws[room_id].remove(ws)
