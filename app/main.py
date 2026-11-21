"""Atlas-Q: rede quanticamente segura com copiloto de IA."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import copilot
from .etsi import build_router
from .messaging import send_occurrence
from .network import QKDNetwork

net = QKDNetwork()
STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    net.start()
    yield


app = FastAPI(title="Atlas-Q", version="0.1.0", lifespan=lifespan)
app.include_router(build_router(net))
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state", tags=["Painel"])
def state():
    return net.snapshot()


class EveToggle(BaseModel):
    enabled: bool


@app.post("/api/links/{link_id}/eve", tags=["Simulação"])
def toggle_eve(link_id: str, body: EveToggle):
    link = net.get_link(link_id)
    if not link:
        raise HTTPException(404, "Enlace não encontrado")
    link.eve = body.enabled
    net.log("alerta" if link.eve else "info", f"[Simulação] Espião {'ligado' if link.eve else 'desligado'} em {link_id}.", link_id)
    return {"ok": True}


class Occurrence(BaseModel):
    sender: str
    receiver: str
    text: str


@app.post("/api/occurrences", tags=["Aplicação"])
def occurrence(body: Occurrence):
    try:
        return send_occurrence(net, body.sender, body.receiver, body.text)
    except LookupError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


class Question(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/copilot", tags=["Copiloto IA"])
def ask_copilot(body: Question):
    return copilot.ask(net, body.question, body.history)
