from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Cookie,
    WebSocketException,
    Query,
    status,
    Depends,
)
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List
import certifi
import requests
from pydantic import BaseModel, Field, ConfigDict, validator
from pydantic.functional_validators import BeforeValidator
from bson import ObjectId
from datetime import datetime
from typing import Annotated


ca = certifi.where()

app = FastAPI()

DATABASE_URL = "mongodb+srv://jaindu:hellojaindu@cluster-dev-metta.llkx8iq.mongodb.net/"
client = AsyncIOMotorClient(DATABASE_URL, tlsCAFile=ca)
db = client.chat_db
collection = client.messaging

# example doc

# {
#     "_id": {"$oid": "65c0da2f9a0c622050505667"},
#     "endpoint_1": "mongo_objectID 1",
#     "endpoint_2": "mongo_objectID 2",
#     "messages": [
#         {
#             "timestamp": {"$timestamp": {"t": 0, "i": 0}},
#             "message": "text message",
#             "from_user": "jaindu",
#             "delivered": true
#         },
#         {
#             "timestamp": {"$timestamp": {"t": 0, "i": 0}},
#             "message": "text message 2",
#             "from_user": "rusiru",
#             "delivered": false
#         },
#     ],
# }

class Message(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    message: str
    from_user: str
    delivered: bool = False


class Chat(BaseModel):
    id: ObjectId = Field(default_factory=ObjectId, alias="_id")
    endpoint_1: str
    endpoint_2: str
    messages: List[Message] = Field(default_factory=list)
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    @validator("messages")
    def ensure_timestamp_exists(cls, v):
        """All messages must have a timestamp"""
        for message in v:
            if not message.timestamp:
                raise ValueError("All messages must have a timestamp")
        return v


async def add_message(from_user: str, to_user: str, message_text: str):
    message = Message(message=message_text, from_user=from_user)
    query = {
        "$or": [
            {"endpoint_1": message.from_user, "endpoint_2": to_user},
            {"endpoint_1": to_user, "endpoint_2": message.from_user},
        ]
    }
    document = await collection.find_one(query)

    if not document:
        document = Chat(
            endpoint_1=message.from_user,
            endpoint_2=to_user,
            messages=[message],
        )
        await collection.insert_one(document.model_dump())
    else:
        document.messages.append(message)
        await collection.update_one(
            {"_id": document.id}, {"$set": {"messages": document.messages}}
        )

    return document


async def load_last_messages(username_one, username_two, x_messages = 5):
    query = {
        "$or": [
            {"endpoint_1": username_one, "endpoint_2": username_two},
            {"endpoint_1": username_two, "endpoint_2": username_one},
        ]
    }
    if x_messages is None:
        x_messages = 50

    projection = {
        "_id": 0,
        "endpoint_1": 1,
        "endpoint_2": 1,
        "messages": 1,
    }

    result = await collection.find_one(query, projection)
    return result


class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, user: str, reciever: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user] = websocket
        await self.send_previous_messages(user, reciever, websocket)

    async def send_previous_messages(
        self, username: str, reciever: str, websocket: WebSocket
    ):
        messages = await load_last_messages(username, reciever)
        await websocket.send_json(messages)

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]

    async def send_private_message(self, user: str, reciever: str, message: str):
        if message.receiver in self.active_connections:
            await self.active_connections[reciever].send_json(message)
        else:
            # If receiver not connected, save the message to the database
            await add_message(user, reciever, message)


manager = ConnectionManager()


async def get_cookie_or_token(
    websocket: WebSocket,
    session: Annotated[str | None, Cookie()] = None,
    token: Annotated[str | None, Query()] = None,
):
    if session is None and token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return session or token


@app.websocket("/ws/{username}")
async def websocket_endpoint(
    websocket: WebSocket,
    username: str,
    cookie_or_token: Annotated[str, Depends(get_cookie_or_token)],
):
    await manager.connect(username, websocket)
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {cookie_or_token}",
    }
    response = requests.get("http://localhost:8000/check", headers=headers).json()
    try:
        while True:
            from_user_id = response["user"]["_id"]
            data = await websocket.receive_json()
            message = Message(**data)
            print(manager.active_connections)
            await manager.send_private_message(message)
            await db["messages"].insert_one(message.model_dump())
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


@app.post("/users/")
async def create_user(user: User):
    existing_user = await db["users"].find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    await db["users"].insert_one(user.model_dump())
    return {"message": "User created successfully"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
