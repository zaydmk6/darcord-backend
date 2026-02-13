import sqlite3, jwt, datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

SECRET_KEY = "DARCORD_SUPER_SECRET_KEY_32_CHAR_LONG"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== DATABASE =====
db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    owner TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER,
    name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS members (
    server_id INTEGER,
    username TEXT,
    role TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    channel_id INTEGER,
    username TEXT,
    content TEXT,
    timestamp TEXT
)
""")

db.commit()

# ===== JWT =====
def create_token(username):
    return jwt.encode({
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=12)
    }, SECRET_KEY, algorithm="HS256")

def verify_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])["username"]
    except:
        return None

# ===== AUTH =====
@app.post("/register")
def register(data: dict):
    try:
        cursor.execute("INSERT INTO users VALUES (NULL, ?, ?)", (data["username"], data["password"]))
        db.commit()
        return {"status":"ok"}
    except:
        return {"error":"Username exists"}

@app.post("/login")
def login(data: dict):
    cursor.execute("SELECT * FROM users WHERE username=? AND password=?",
                   (data["username"], data["password"]))
    if cursor.fetchone():
        return {"token": create_token(data["username"])}
    return {"error":"Invalid login"}

# ===== CREATE SERVER =====
@app.post("/create_server")
def create_server(data: dict):
    user = verify_token(data["token"])
    if not user: return {"error":"Unauthorized"}

    cursor.execute("INSERT INTO servers VALUES (NULL, ?, ?)", (data["name"], user))
    db.commit()
    server_id = cursor.lastrowid

    cursor.execute("INSERT INTO members VALUES (?, ?, ?)", (server_id, user, "Owner"))
    cursor.execute("INSERT INTO channels VALUES (NULL, ?, ?)", (server_id, "general"))
    db.commit()

    return {"server_id": server_id}

# ===== WEBSOCKET CHAT =====
clients = {}

@app.websocket("/ws/{channel_id}")
async def websocket(ws: WebSocket, channel_id: int):
    await ws.accept()
    clients.setdefault(channel_id, []).append(ws)

    try:
        while True:
            data = await ws.receive_json()
            username = verify_token(data["token"])
            if not username:
                await ws.send_json({"error":"Unauthorized"})
                continue

            timestamp = datetime.datetime.utcnow().isoformat()

            cursor.execute("INSERT INTO messages VALUES (?, ?, ?, ?)",
                           (channel_id, username, data["message"], timestamp))
            db.commit()

            for client in clients[channel_id]:
                await client.send_json({
                    "username": username,
                    "message": data["message"],
                    "timestamp": timestamp
                })

    except WebSocketDisconnect:
        clients[channel_id].remove(ws)
