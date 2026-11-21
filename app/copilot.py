"""Copiloto de operações com LLM (Claude) e uso de ferramentas.

O operador pergunta em português ("por que o enlace de Salvador parou?") e o
modelo consulta o estado real da rede por meio de ferramentas antes de responder.
Sem ANTHROPIC_API_KEY, entra um modo offline baseado em regras, para o
projeto rodar em qualquer máquina.
"""

from __future__ import annotations

import json
import os

from .network import QKDNetwork

MODEL = os.getenv("COPILOT_MODEL", "claude-haiku-5-5")

SYSTEM = """Você é o copiloto do centro de operações de uma rede QKD (distribuição quântica de chaves)
que protege a troca de ocorrências entre unidades de segurança pública na Bahia.
Responda em português do Brasil, de forma curta e objetiva, como num painel de operações.
Sempre consulte as ferramentas antes de afirmar algo sobre o estado da rede.
Explique termos técnicos (QBER, BB84, KMS) em uma frase quando forem relevantes.
QBER acima do limite indica possível interceptação (ataque intercept-resend) ou ruído excessivo.
Quando houver incidente, sugira ações concretas: rotear por outro enlace, isolar o enlace, acionar a equipe técnica."""

TOOLS = [
    {
        "name": "get_network_overview",
        "description": "Estado atual de todos os nós e enlaces: status, QBER mais recente, estoque de chaves e últimos eventos.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_link_details",
        "description": "Histórico de QBER e contadores de um enlace específico.",
        "input_schema": {
            "type": "object",
            "properties": {"link_id": {"type": "string", "description": "Ex.: salvador-feira"}},
            "required": ["link_id"],
        },
    },
    {
        "name": "set_eavesdropper",
        "description": "Ambiente de simulação: liga ou desliga um espião (Eve) num enlace, para testes e treinamento.",
        "input_schema": {
            "type": "object",
            "properties": {"link_id": {"type": "string"}, "enabled": {"type": "boolean"}},
            "required": ["link_id", "enabled"],
        },
    },
]


def _run_tool(net: QKDNetwork, name: str, args: dict) -> dict:
    if name == "get_network_overview":
        snap = net.snapshot()
        for l in snap["links"]:
            l.pop("qber_history")
        snap.pop("messages")
        snap["events"] = snap["events"][:10]
        return snap
    if name == "get_link_details":
        link = net.get_link(args["link_id"])
        if not link:
            return {"erro": "enlace não encontrado", "enlaces": [l.id for l in net.links]}
        return {
            "id": link.id,
            "status": link.status,
            "km": link.km,
            "qber_recente": [h["qber"] for h in list(link.qber_history)[-15:]],
            "chaves_em_estoque": len(link.keys),
            "geradas": link.generated_total,
            "consumidas": link.consumed_total,
        }
    if name == "set_eavesdropper":
        link = net.get_link(args["link_id"])
        if not link:
            return {"erro": "enlace não encontrado"}
        link.eve = bool(args["enabled"])
        net.log("alerta" if link.eve else "info", f"[Simulação] Espião {'ligado' if link.eve else 'desligado'} em {link.id}.", link.id)
        return {"ok": True, "link": link.id, "eve": link.eve}
    return {"erro": f"ferramenta desconhecida: {name}"}


def _offline_answer(net: QKDNetwork, question: str) -> str:
    snap = net.snapshot()
    bad = [l for l in snap["links"] if l["status"] == "abortado"]
    warn = [l for l in snap["links"] if l["status"] == "alerta"]
    lines = []
    if bad:
        for l in bad:
            lines.append(
                f"⚠️ Enlace {l['id']} está abortando: QBER {l['qber']:.1%}, acima do limite de "
                f"{snap['threshold']:.0%}. Isso indica possível interceptação. Sugestão: rotear as "
                f"ocorrências por outro caminho e acionar a equipe técnica."
            )
    if warn:
        lines.append("Enlaces em alerta (QBER subindo): " + ", ".join(l["id"] for l in warn) + ".")
    if not bad and not warn:
        total = sum(l["stored_keys"] for l in snap["links"])
        lines.append(f"✅ Todos os enlaces operando normalmente. {total} chaves em estoque na rede.")
    return "\n".join(lines)


def ask(net: QKDNetwork, question: str, history: list[dict] | None = None) -> dict:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return {"answer": _offline_answer(net, question), "tools_used": [], "mode": "offline"}

    import anthropic

    client = anthropic.Anthropic()
    messages = list(history or []) + [{"role": "user", "content": question}]
    tools_used: list[str] = []

    for _ in range(6):  # limite de rodadas de ferramenta
        resp = client.messages.create(
            model=MODEL, max_tokens=800, system=SYSTEM, tools=TOOLS, messages=messages
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"answer": text, "tools_used": tools_used, "mode": "llm"}

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                tools_used.append(block.name)
                out = _run_tool(net, block.name, block.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, ensure_ascii=False)}
                )
        messages.append({"role": "user", "content": results})

    return {"answer": "Não consegui concluir a análise. Tente reformular.", "tools_used": tools_used, "mode": "llm"}
