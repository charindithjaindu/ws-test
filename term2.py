from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List

app = FastAPI()

DATABASE_URL = "mongodb://localhost:27017"
client = AsyncIOMotorClient(DATABASE_URL)
db = client.chat_db


class User(BaseModel):
    username: str


class Message(BaseModel):
    sender: str
    receiver: str
    content: str


class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username] = websocket

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]

    async def send_private_message(self, message: Message):
        if message.receiver in self.active_connections:
            await self.active_connections[message.receiver].send_json(message.dict())


manager = ConnectionManager()


@app.post("/users/")
async def create_user(user: User):
    existing_user = await db["users"].find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    await db["users"].insert_one(user.model_dump())
    return {"message": "User created successfully"}


@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(username, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = Message(**data)
            await manager.send_private_message(message)
            await db["messages"].insert_one(message.dict())
    except WebSocketDisconnect:
        manager.disconnect(username)


@app.get("/messages/{username}", response_model=List[Message])
async def get_messages(username: str):
    user = await db["users"].find_one({"username": username})
    if not user:
        raise HTTPException(status_code=400, detail="User does not exist")
    messages = (
        await db["messages"]
        .find({"$or": [{"sender": username}, {"receiver": username}]})
        .to_list(None)
    )
    return messages


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
