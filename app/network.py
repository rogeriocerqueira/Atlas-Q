"""Rede QKD simulada: nós, enlaces, KMS e geração contínua de chaves.

Cada enlace (par de nós) roda BB84 periodicamente. As chaves aprovadas
vão para o estoque do KMS daquele enlace e são entregues às aplicações
pela API ETSI GS QKD 014 (ver etsi.py).
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from .bb84 import QBER_THRESHOLD, run_bb84

KEY_SIZE_BITS = 256
MAX_KEYS_PER_LINK = 200


@dataclass
class Node:
    id: str
    name: str
    city: str
    x: float  # posição no mapa (0-100)
    y: float


@dataclass
class Link:
    a: str
    b: str
    km: float
    noise: float = 0.02
    eve: bool = False
    keys: deque = field(default_factory=lambda: deque(maxlen=MAX_KEYS_PER_LINK))
    delivered: dict = field(default_factory=dict)  # key_ID -> key (aguardando dec_keys)
    qber_history: deque = field(default_factory=lambda: deque(maxlen=60))
    status: str = "ok"  # ok | alerta | abortado
    generated_total: int = 0
    consumed_total: int = 0
    _pool: bytes = b""

    @property
    def id(self) -> str:
        return f"{self.a}-{self.b}"

    def connects(self, x: str, y: str) -> bool:
        return {x, y} == {self.a, self.b}


class QKDNetwork:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {
            n.id: n
            for n in [
                Node("salvador", "Central de Operações", "Salvador", 74, 72),
                Node("feira", "Batalhão Regional", "Feira de Santana", 40, 44),
                Node("serrinha", "Delegacia Regional", "Serrinha", 22, 14),
                Node("alagoinhas", "Base Regional", "Alagoinhas", 82, 30),
            ]
        }
        self.links: list[Link] = [
            Link("salvador", "feira", 108, noise=0.025),
            Link("feira", "serrinha", 72, noise=0.02),
            Link("feira", "alagoinhas", 80, noise=0.02),
            Link("salvador", "alagoinhas", 110, noise=0.03),
        ]
        self.events: deque = deque(maxlen=200)
        self.messages: deque = deque(maxlen=50)
        self._task: asyncio.Task | None = None
        self.log("info", "Rede iniciada com %d nós e %d enlaces." % (len(self.nodes), len(self.links)))

    # ---------- utilidades ----------
    def log(self, level: str, text: str, link: str | None = None) -> None:
        self.events.appendleft({"t": time.time(), "level": level, "text": text, "link": link})

    def link_between(self, x: str, y: str) -> Link | None:
        return next((l for l in self.links if l.connects(x, y)), None)

    def get_link(self, link_id: str) -> Link | None:
        return next((l for l in self.links if l.id == link_id), None)

    # ---------- geração de chaves ----------
    def generation_round(self, link: Link) -> None:
        # Distância maior => mais perda/ruído (modelo simplificado)
        noise = link.noise + link.km * 0.00005
        res = run_bb84(n_qubits=4096, eve=link.eve, noise=noise)
        link.qber_history.append({"t": time.time(), "qber": round(res.qber, 4)})

        if res.aborted:
            if link.status != "abortado":
                self.log(
                    "critico",
                    f"QBER {res.qber:.1%} acima do limite de {QBER_THRESHOLD:.0%} no enlace "
                    f"{self.nodes[link.a].city} ↔ {self.nodes[link.b].city}. Chave descartada: possível interceptação.",
                    link.id,
                )
            link.status = "abortado"
            return

        if res.qber > QBER_THRESHOLD * 0.7:
            link.status = "alerta"
        else:
            if link.status == "abortado":
                self.log("info", f"Enlace {link.id} voltou a gerar chaves (QBER {res.qber:.1%}).", link.id)
            link.status = "ok"

        link._pool += res.key
        size = KEY_SIZE_BITS // 8
        while len(link._pool) >= size:
            chunk, link._pool = link._pool[:size], link._pool[size:]
            link.keys.append((str(uuid.uuid4()), chunk))
            link.generated_total += 1

    async def run_forever(self, interval: float = 1.5) -> None:
        while True:
            for link in self.links:
                self.generation_round(link)
            await asyncio.sleep(interval)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever())

    # ---------- KMS (usado pela API ETSI) ----------
    def take_keys(self, master: str, slave: str, number: int) -> list[dict]:
        link = self.link_between(master, slave)
        if link is None:
            raise LookupError("Não existe enlace QKD entre esses nós.")
        if len(link.keys) < number:
            raise RuntimeError("Estoque de chaves insuficiente.")
        out = []
        for _ in range(number):
            key_id, key = link.keys.popleft()
            link.delivered[key_id] = key
            link.consumed_total += 1
            out.append({"key_ID": key_id, "key": base64.b64encode(key).decode()})
        return out

    def fetch_keys(self, slave: str, master: str, key_ids: list[str]) -> list[dict]:
        link = self.link_between(master, slave)
        if link is None:
            raise LookupError("Não existe enlace QKD entre esses nós.")
        out = []
        for kid in key_ids:
            key = link.delivered.pop(kid, None)
            if key is None:
                raise KeyError(kid)
            out.append({"key_ID": kid, "key": base64.b64encode(key).decode()})
        return out

    # ---------- visão geral (dashboard e copiloto) ----------
    def snapshot(self) -> dict:
        return {
            "nodes": [n.__dict__ for n in self.nodes.values()],
            "links": [
                {
                    "id": l.id,
                    "a": l.a,
                    "b": l.b,
                    "km": l.km,
                    "noise": l.noise,
                    "eve": l.eve,
                    "status": l.status,
                    "stored_keys": len(l.keys),
                    "generated_total": l.generated_total,
                    "consumed_total": l.consumed_total,
                    "qber": l.qber_history[-1]["qber"] if l.qber_history else None,
                    "qber_history": list(l.qber_history),
                }
                for l in self.links
            ],
            "events": list(self.events)[:30],
            "messages": list(self.messages)[:15],
            "threshold": QBER_THRESHOLD,
        }
