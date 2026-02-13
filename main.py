import sqlite3, jwt, datetime, os, random, string
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

SECRET_KEY = "SUPER_SECRET_KEY_CHANGE_THIS"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("avatars", exist_ok=True)
app.mount("/avatars", StaticFiles(directory="avatars"), name="avatars")

db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()

# ===== TABLES =====
cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, avatar TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS status (username TEXT, state TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS xp (username TEXT, points INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS friends (user1 TEXT, user2 TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS servers (id INTEGER PRIMARY KEY, name TEXT, owner TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY, server_id INTEGER, name TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS members (server_id INTEGER, username TEXT, role TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS invites (code TEXT, server_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS muted (server_id INTEGER, username TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS messages (channel_id INTEGER, username TEXT, content TEXT, timestamp TEXT)")
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

# ===== AUTH =====
@app.post("/register")
def register(data: dict):
    try:
        cursor.execute("INSERT INTO users VALUES (NULL,?,?,?)",
                       (data["username"], data["password"], ""))
        db.commit()
        return {"status": "ok"}
    except:
        return {"error": "exists"}

@app.post("/login")
def login(data: dict):
    cursor.execute("SELECT * FROM users WHERE username=? AND password=?",
                   (data["username"], data["password"]))
    if cursor.fetchone():
        token = create_token(data["username"])
        cursor.execute("DELETE FROM status WHERE username=?",(data["username"],))
        cursor.execute("INSERT INTO status VALUES (?,?)",(data["username"],"online"))
        db.commit()
        return {"token": token}
    return {"error": "invalid"}

# ===== AVATAR =====
@app.post("/upload_avatar")
async def upload_avatar(token:str, file:UploadFile=File(...)):
    username = verify_token(token)
    if not username: return {"error":"Unauthorized"}

    path = f"avatars/{username}.png"
    with open(path,"wb") as f:
        f.write(await file.read())

    cursor.execute("UPDATE users SET avatar=? WHERE username=?",(path,username))
    db.commit()
    return {"status":"uploaded"}

# ===== FRIENDS =====
@app.post("/add_friend")
def add_friend(data:dict):
    user = verify_token(data["token"])
    cursor.execute("INSERT INTO friends VALUES (?,?)",(user,data["target"]))
    db.commit()
    return {"status":"added"}

@app.get("/friends/{username}")
def get_friends(username:str):
    cursor.execute("SELECT user2 FROM friends WHERE user1=?",(username,))
    return cursor.fetchall()

# ===== SERVERS =====
@app.post("/create_server")
def create_server(data:dict):
    user = verify_token(data["token"])
    cursor.execute("INSERT INTO servers VALUES (NULL,?,?)",(data["name"],user))
    db.commit()
    sid = cursor.lastrowid
    cursor.execute("INSERT INTO members VALUES (?,?,?)",(sid,user,"Owner"))
    cursor.execute("INSERT INTO channels VALUES (NULL,?,?)",(sid,"general"))
    db.commit()
    return {"server_id":sid}

@app.post("/create_channel")
def create_channel(data:dict):
    user = verify_token(data["token"])
    cursor.execute("INSERT INTO channels VALUES (NULL,?,?)",(data["server_id"],data["name"]))
    db.commit()
    return {"status":"created"}

# ===== INVITE =====
@app.post("/create_invite")
def create_invite(data:dict):
    code=''.join(random.choices(string.ascii_letters+string.digits,k=8))
    cursor.execute("INSERT INTO invites VALUES (?,?)",(code,data["server_id"]))
    db.commit()
    return {"code":code}

@app.post("/join_invite")
def join_invite(data:dict):
    user = verify_token(data["token"])
    cursor.execute("SELECT server_id FROM invites WHERE code=?",(data["code"],))
    result = cursor.fetchone()
    if result:
        cursor.execute("INSERT INTO members VALUES (?,?,?)",(result[0],user,"Member"))
        db.commit()
        return {"joined":result[0]}
    return {"error":"invalid"}

# ===== LOAD MESSAGES =====
@app.get("/messages/{channel_id}")
def get_messages(channel_id:int):
    cursor.execute("SELECT username,content FROM messages WHERE channel_id=?",(channel_id,))
    return cursor.fetchall()

# ===== WEBSOCKET CHAT + XP =====
clients={}

@app.websocket("/ws/{channel_id}")
async def ws(ws:WebSocket, channel_id:int):
    await ws.accept()
    clients.setdefault(channel_id,[]).append(ws)

    try:
        while True:
            data=await ws.receive_json()
            username=verify_token(data["token"])

            timestamp=datetime.datetime.utcnow().isoformat()
            cursor.execute("INSERT INTO messages VALUES (?,?,?,?)",
                           (channel_id,username,data["message"],timestamp))

            # XP
            cursor.execute("SELECT points FROM xp WHERE username=?",(username,))
            row=cursor.fetchone()
            if row:
                cursor.execute("UPDATE xp SET points=points+5 WHERE username=?",(username,))
            else:
                cursor.execute("INSERT INTO xp VALUES (?,?)",(username,5))
            db.commit()

            for c in clients[channel_id]:
                await c.send_json({
                    "username":username,
                    "message":data["message"]
                })

    except WebSocketDisconnect:
        clients[channel_id].remove(ws)
        cursor.execute("UPDATE status SET state='offline' WHERE username=?",(username,))
        db.commit()
