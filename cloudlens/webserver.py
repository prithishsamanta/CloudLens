from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
import webbrowser
import threading
import uvicorn

# global variable
diagnosis_data = {}
report_metadata = {}

templates = Jinja2Templates(directory="server/templates")

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
    return templates.TemplateResponse("report.html", {
        "request": request,
        "data": diagnosis_data,
        "metadata": report_metadata
    })