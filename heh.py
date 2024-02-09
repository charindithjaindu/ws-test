from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict
import certifi
from datetime import datetime

ca = certifi.where()

app = FastAPI()

DATABASE_URL = "mongodb+srv://jaindu:hellojaindu@cluster-dev-metta.llkx8iq.mongodb.net/"
client = AsyncIOMotorClient(DATABASE_URL, tlsCAFile=ca)
db = client.chat_db


class User(BaseModel):
    username: str


class Message(BaseModel):
    sender: str
    receiver: str
    content: str
    timestamp: str = str(datetime.utcnow())  # Added timestamp with default value
    receive_status: bool = True


class UserMessageStats(BaseModel):
    username: str
    chats: List[Dict[str, int]]

# {
#     "_id": "some_id",
#     "username": "user1",
#     "chats": [
#         {"chat_username": "user2", "messages_sent": 5, "messages_received": 0},
#         {"chat_username": "user3", "messages_sent": 2, "messages_received": 4},
#     ],
# }


class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username] = websocket
        await self.ensure_user_message_stats_entry(username)
        await self.send_previous_messages(username, websocket)

    async def ensure_user_message_stats_entry(self, username: str):
        # Check if entry exists for the user, if not, create one
        if not await db["user_message_stats"].find_one({"username": username}):
            await db["user_message_stats"].insert_one(
                {"username": username, "chats": []}
            )

    async def send_previous_messages(self, username: str, websocket: WebSocket):
        messages = (
            await db["messages"]
            .find({"$or": [{"sender": username}, {"receiver": username}]})
            .to_list(None)
        )
        for message in messages:
            message_data = Message(**message).model_dump()
            message_data["receive_status"] = True  # Set receive_status to True
            await websocket.send_json(message_data)

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]

    async def send_private_message(self, message: Message):
        message.receive_status = message.receiver in self.active_connections
        if message.receiver in self.active_connections:
            await self.active_connections[message.receiver].send_json(
                message.model_dump()
            )
        else:
            # If receiver not connected, save the message to the database
            await db["messages"].insert_one(message.model_dump())

        await self.update_user_message_stats(message.sender, message.receiver)

    async def is_chat_username_available(self, username, chat_username):
        document = await db["user_message_stats"].find_one(
            {"username": username}
            )
        try:
            for chat in document["chats"]:
                if chat["chat_username"] == chat_username:
                    return True
            return False
        except:
            return False

    async def update_user_message_stats(self, username: str, other_user: str):
        # Update messages_sent for the sender
        if await self.is_chat_username_available(username, other_user):
            await db["user_message_stats"].update_one(
                {"username": username, "chats.chat_username": other_user},
                {"$inc": {"chats.$.messages_sent": 1}},
                upsert=True,
            )
        else:
            await db["user_message_stats"].update_one(
                {"username": username},
                {"$addToSet": {"chats": {"chat_username": other_user, "messages_sent": 1}}},
                upsert=True,
            )

        # Update messages_received for the receiver
        if await self.is_chat_username_available(other_user, username):
            await db["user_message_stats"].update_one(
                {"username": other_user, "chats.chat_username": username},
                {"$inc": {"chats.$.messages_received": 1}},
                upsert=True,
            )
        else:
            await db["user_message_stats"].update_one(
                {"username": other_user},
                {"$addToSet": {"chats": {"chat_username": username, "messages_received": 1}}},
                upsert=True,
            )


manager = ConnectionManager()


@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(username, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = Message(**data)
            message.timestamp = str(datetime.utcnow())  # Update timestamp before saving
            await manager.send_private_message(message)
            await db["messages"].insert_one(message.model_dump())
    except WebSocketDisconnect:
        manager.disconnect(username)


@app.post("/users/")
async def create_user(user: User):
    existing_user = await db["users"].find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    await db["users"].insert_one(user.model_dump())
    return {"message": "User created successfully"}


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


@app.get("/user_message_stats/{username}", response_model=UserMessageStats)
async def get_user_message_stats(username: str):
    user_message_stats = await db["user_message_stats"].find_one({"username": username})
    if not user_message_stats:
        raise HTTPException(status_code=404, detail="User not found in message stats")
    return user_message_stats


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
