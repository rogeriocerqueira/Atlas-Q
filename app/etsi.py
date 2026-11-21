"""API de entrega de chaves no padrão ETSI GS QKD 014 (v1).

No padrão, a identidade do SAE (aplicação) vem do certificado TLS mútuo.
Nesta versão de estudo ela vem do cabeçalho `X-SAE-ID` (ver roadmap no README).
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .network import KEY_SIZE_BITS, MAX_KEYS_PER_LINK, QKDNetwork

MAX_KEYS_PER_REQUEST = 16


class KeyRequest(BaseModel):
    number: int = 1
    size: int = KEY_SIZE_BITS


class KeyIDItem(BaseModel):
    key_ID: str


class KeyIDsRequest(BaseModel):
    key_IDs: list[KeyIDItem]


def build_router(net: QKDNetwork) -> APIRouter:
    r = APIRouter(prefix="/api/v1/keys", tags=["ETSI GS QKD 014"])

    def _check(sae: str, other: str):
        if sae not in net.nodes or other not in net.nodes:
            raise HTTPException(404, "SAE desconhecido")
        link = net.link_between(sae, other)
        if link is None:
            raise HTTPException(404, "Não existe enlace QKD entre esses SAEs")
        return link

    @r.get("/{slave_SAE_ID}/status")
    def status(slave_SAE_ID: str, x_sae_id: str = Header(...)):
        link = _check(x_sae_id, slave_SAE_ID)
        return {
            "source_KME_ID": f"KME-{x_sae_id}",
            "target_KME_ID": f"KME-{slave_SAE_ID}",
            "master_SAE_ID": x_sae_id,
            "slave_SAE_ID": slave_SAE_ID,
            "key_size": KEY_SIZE_BITS,
            "stored_key_count": len(link.keys),
            "max_key_count": MAX_KEYS_PER_LINK,
            "max_key_per_request": MAX_KEYS_PER_REQUEST,
            "max_key_size": KEY_SIZE_BITS,
            "min_key_size": KEY_SIZE_BITS,
            "max_SAE_ID_count": 0,
        }

    @r.post("/{slave_SAE_ID}/enc_keys")
    def enc_keys(slave_SAE_ID: str, body: KeyRequest, x_sae_id: str = Header(...)):
        _check(x_sae_id, slave_SAE_ID)
        if body.size != KEY_SIZE_BITS:
            raise HTTPException(400, f"Tamanho suportado: {KEY_SIZE_BITS} bits")
        if not 1 <= body.number <= MAX_KEYS_PER_REQUEST:
            raise HTTPException(400, f"number deve estar entre 1 e {MAX_KEYS_PER_REQUEST}")
        try:
            return {"keys": net.take_keys(x_sae_id, slave_SAE_ID, body.number)}
        except RuntimeError as e:
            raise HTTPException(503, str(e))

    @r.post("/{master_SAE_ID}/dec_keys")
    def dec_keys(master_SAE_ID: str, body: KeyIDsRequest, x_sae_id: str = Header(...)):
        _check(x_sae_id, master_SAE_ID)
        try:
            return {"keys": net.fetch_keys(x_sae_id, master_SAE_ID, [k.key_ID for k in body.key_IDs])}
        except KeyError as e:
            raise HTTPException(404, f"key_ID não encontrado ou já usado: {e}")

    return r
