import os
import threading
import webbrowser

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

# global variable
diagnosis_data = {}
report_metadata = {}

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

app = FastAPI()


@app.get("/favicon.ico")
def favicon():
    """Avoid 404 when the browser requests a tab icon."""
    return Response(status_code=204)


def start_server(diagnosis: dict, metadata: dict):
    global diagnosis_data, report_metadata
    diagnosis_data = diagnosis
    report_metadata = metadata

    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000/report")).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.get("/report")
def get_report(request: Request):
    return templates.TemplateResponse(request, "report.html", {
        "data": diagnosis_data,
        "metadata": report_metadata
    })