import json
import os
import socket
import threading
import time
import webbrowser

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from rich.console import Console

from cloudlens.bedrock import chat_reply

console = Console()

REPORT_PORT = 8000


class PortInUseError(Exception):
    """Raised when the local report server's port is already occupied by
    something else, so the CLI can say so clearly instead of the browser
    tab silently failing to connect."""
    pass


def _check_port_available(port: int, host: str = "0.0.0.0"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as e:
        raise PortInUseError(
            f"Port {port} is already in use by something else on this machine."
        ) from e
    finally:
        sock.close()

# global variable — this is a single-user local process, so plain module
# state is enough; the chat has no memory beyond this one report/process.
diagnosis_data = {}
report_metadata = {}
report_log_text = ""
report_service = "generic"
chat_history = []
last_activity = 0.0

# Sliding session window: each chat message renews it. A reload while the
# session is still "in use" keeps the conversation; once it's been idle past
# this, the next load starts a genuinely fresh session.
SESSION_TIMEOUT_SECONDS = 15 * 60

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

app = FastAPI()


class ChatMessage(BaseModel):
    message: str


@app.get("/favicon.ico")
def favicon():
    """Avoid 404 when the browser requests a tab icon."""
    return Response(status_code=204)


def start_server(diagnosis: dict, metadata: dict, log_text: str = "", service: str = "generic"):
    global diagnosis_data, report_metadata, report_log_text, report_service

    _check_port_available(REPORT_PORT)

    diagnosis_data = diagnosis
    report_metadata = metadata
    report_log_text = log_text
    report_service = service

    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{REPORT_PORT}/report")).start()
    uvicorn.run(app, host="0.0.0.0", port=REPORT_PORT)


def _history_as_messages() -> list:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "text": m}
        for i, m in enumerate(chat_history)
    ]


@app.get("/report")
def get_report(request: Request):
    global chat_history

    if chat_history and (time.time() - last_activity) > SESSION_TIMEOUT_SECONDS:
        chat_history = []

    # Escape "</" so log/AI content can never prematurely close the <script>
    # tag this gets embedded in.
    chat_history_json = json.dumps(_history_as_messages()).replace("</", "<\\/")

    return templates.TemplateResponse(request, "report.html", {
        "data": diagnosis_data,
        "metadata": report_metadata,
        "chat_history_json": chat_history_json,
    })


@app.post("/chat")
def post_chat(body: ChatMessage):
    global chat_history, last_activity

    result = chat_reply(
        report_service, report_metadata, report_log_text, diagnosis_data, chat_history, body.message
    )

    if result["reply"] is None:
        return {"reply": result["warning"], "warning": result["warning"], "blocked": True}

    chat_history.append(body.message)
    chat_history.append(result["reply"])
    last_activity = time.time()

    return {"reply": result["reply"], "warning": result["warning"], "blocked": False}