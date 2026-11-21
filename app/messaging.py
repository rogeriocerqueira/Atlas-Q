"""Aplicação de demonstração: envio de ocorrências cifradas entre unidades.

O remetente pede uma chave ao KMS (enc_keys), cifra com AES-256-GCM e envia
só o texto cifrado + o key_ID. O destinatário recupera a mesma chave pelo
key_ID (dec_keys) e decifra. A chave nunca trafega junto com a mensagem.
"""

from __future__ import annotations

import base64
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .network import QKDNetwork


def send_occurrence(net: QKDNetwork, sender: str, receiver: str, text: str) -> dict:
    [key] = net.take_keys(sender, receiver, 1)
    nonce = os.urandom(12)
    ct = AESGCM(base64.b64decode(key["key"])).encrypt(nonce, text.encode(), None)

    # lado do destinatário: busca a chave pelo ID e decifra
    [same] = net.fetch_keys(receiver, sender, [key["key_ID"]])
    plain = AESGCM(base64.b64decode(same["key"])).decrypt(nonce, ct, None).decode()

    msg = {
        "t": time.time(),
        "from": sender,
        "to": receiver,
        "key_ID": key["key_ID"],
        "ciphertext": base64.b64encode(nonce + ct).decode(),
        "plaintext": plain,
    }
    net.messages.appendleft(msg)
    net.log(
        "info",
        f"Ocorrência cifrada enviada de {net.nodes[sender].city} para {net.nodes[receiver].city} "
        f"(chave {key['key_ID'][:8]}…).",
        net.link_between(sender, receiver).id,
    )
    return msg
