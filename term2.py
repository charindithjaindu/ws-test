from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Serve static files (e.g., HTML, JS, CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def get_home():
    # Serve the HTML page
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket with Cookies</title>
        <script>
            const socket = new WebSocket("ws://localhost:8000/ws",
            headers: {
                    'Cookie': `session_id=hellp`
                }
);
            socket.onmessage = (event) => {
                console.log("Message from server:", event.data);
            };

            // Send a message to the server on button click
            document.getElementById("sendButton").addEventListener("click", () => {
                const message = document.getElementById("messageInput").value;
                socket.send(message);
            });
        </script>
    </head>
    <body>
        <h1>WebSocket with Cookies</h1>
        <input type="text" id="messageInput" placeholder="Type a message">
        <button id="sendButton">Send</button>
    </body>
    </html>
    """


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message received: {data}")
