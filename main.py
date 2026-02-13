import sqlite3
import jwt
import datetime
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

SECRET_KEY = "DARCORD_SUPER_SECRET"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- DATABASE ----------
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
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    content TEXT,
    timestamp TEXT
)
""")

db.commit()

# ---------- JWT ----------
def create_token(username):
    return jwt.encode({
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=12)
    }, SECRET_KEY, algorithm="HS256")

def verify_token(token):
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return data["username"]
    except:
        return None

# ---------- AUTH ----------
@app.post("/register")
def register(data: dict):
    try:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (data["username"], data["password"])
        )
        db.commit()
        return {"status": "ok"}
    except:
        return {"status": "error", "message": "Username exists"}

@app.post("/login")
def login(data: dict):
    cursor.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (data["username"], data["password"])
    )
    if cursor.fetchone():
        return {"token": create_token(data["username"])}
    return {"error": "Invalid login"}

# ---------- CHAT ----------
clients = []

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    try:
        while True:
            data = await ws.receive_json()
            username = verify_token(data["token"])
            if not username:
                await ws.send_json({"error": "Unauthorized"})
                continue

            timestamp = datetime.datetime.utcnow().isoformat()

            cursor.execute(
                "INSERT INTO messages (username, content, timestamp) VALUES (?, ?, ?)",
                (username, data["message"], timestamp)
            )
            db.commit()

            for client in clients:
                await client.send_json({
                    "username": username,
                    "message": data["message"],
                    "timestamp": timestamp
                })
    except WebSocketDisconnect:
        clients.remove(ws)

# ---------- IMAGE UPLOAD ----------
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    os.makedirs("uploads", exist_ok=True)
    path = f"uploads/{file.filename}"
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"url": path}
