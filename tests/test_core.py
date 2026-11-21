import base64

import numpy as np
from fastapi.testclient import TestClient

from app.bb84 import QBER_THRESHOLD, run_bb84
from app.main import app, net


def test_bb84_sem_espiao_gera_chave():
    r = run_bb84(n_qubits=4096, eve=False, noise=0.02, rng=np.random.default_rng(1))
    assert not r.aborted
    assert r.qber < QBER_THRESHOLD
    assert r.key_bits > 0


def test_bb84_com_espiao_aborta():
    # intercept-resend introduz ~25% de erro: o protocolo deve detectar
    r = run_bb84(n_qubits=4096, eve=True, noise=0.02, rng=np.random.default_rng(2))
    assert r.aborted
    assert r.qber > 0.18


def _fill_keys():
    for link in net.links:
        link.eve = False
        for _ in range(3):
            net.generation_round(link)


def test_etsi_enc_e_dec_devolvem_a_mesma_chave():
    _fill_keys()
    c = TestClient(app)
    st = c.get("/api/v1/keys/salvador/status", headers={"X-SAE-ID": "feira"}).json()
    assert st["stored_key_count"] > 0 and st["key_size"] == 256

    enc = c.post("/api/v1/keys/salvador/enc_keys", json={"number": 2}, headers={"X-SAE-ID": "feira"}).json()
    ids = [{"key_ID": k["key_ID"]} for k in enc["keys"]]
    dec = c.post("/api/v1/keys/feira/dec_keys", json={"key_IDs": ids}, headers={"X-SAE-ID": "salvador"}).json()
    assert [k["key"] for k in enc["keys"]] == [k["key"] for k in dec["keys"]]
    assert len(base64.b64decode(enc["keys"][0]["key"])) == 32

    # chave já entregue não pode ser buscada de novo
    again = c.post("/api/v1/keys/feira/dec_keys", json={"key_IDs": ids}, headers={"X-SAE-ID": "salvador"})
    assert again.status_code == 404


def test_sem_enlace_direto_retorna_404():
    c = TestClient(app)
    r = c.get("/api/v1/keys/serrinha/status", headers={"X-SAE-ID": "salvador"})
    assert r.status_code == 404


def test_ocorrencia_cifrada_e_decifrada():
    _fill_keys()
    c = TestClient(app)
    texto = "Ocorrência teste: veículo suspeito na BR-116."
    r = c.post("/api/occurrences", json={"sender": "feira", "receiver": "serrinha", "text": texto}).json()
    assert r["plaintext"] == texto
    assert texto not in base64.b64decode(r["ciphertext"]).decode(errors="ignore")


def test_copiloto_offline_detecta_incidente(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    link = net.get_link("salvador-feira")
    link.eve = True
    net.generation_round(link)
    c = TestClient(app)
    r = c.post("/api/copilot", json={"question": "Algum problema?"}).json()
    assert r["mode"] == "offline"
    assert "salvador-feira" in r["answer"]
    link.eve = False
