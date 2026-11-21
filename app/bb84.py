"""Simulação do protocolo BB84 (Bennett & Brassard, 1984).

A parte física (fótons, polarização) é simulada com números aleatórios.
O que o módulo reproduz fielmente é o fluxo do protocolo:

1. Alice gera bits e bases aleatórias e "envia" os qubits.
2. Eve (opcional) intercepta, mede numa base aleatória e reenvia.
3. O canal adiciona ruído (erros físicos da fibra/detector).
4. Bob mede cada qubit numa base aleatória.
5. Sifting: Alice e Bob revelam as bases e ficam só com as posições iguais.
6. Estimativa de QBER: sacrificam uma amostra para medir a taxa de erro.
7. Se QBER > limite (~11%), abortam: há espião ou ruído demais.
8. Correção de erros + amplificação de privacidade geram a chave final.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

QBER_THRESHOLD = 0.11  # limite teórico de segurança do BB84


@dataclass
class BB84Result:
    n_qubits: int
    sifted_len: int
    qber: float
    aborted: bool
    key: bytes = b""
    eavesdropper: bool = False
    stats: dict = field(default_factory=dict)

    @property
    def key_bits(self) -> int:
        return len(self.key) * 8


def _binary_entropy(p: float) -> float:
    if p <= 0 or p >= 1:
        return 0.0
    return float(-p * np.log2(p) - (1 - p) * np.log2(1 - p))


def _privacy_amplification(bits: np.ndarray, out_len_bits: int, seed: bytes) -> bytes:
    """Comprime a chave reconciliada com hashing (SHAKE-256 como extrator).

    Em sistemas reais usa-se hashing universal (ex.: matriz de Toeplitz).
    Aqui o SHAKE-256 cumpre o papel didático: o espião que conhece
    parte dos bits passa a não saber nada da chave comprimida.
    """
    out_len_bytes = max(out_len_bits // 8, 0)
    if out_len_bytes == 0:
        return b""
    packed = np.packbits(bits).tobytes()
    return hashlib.shake_256(seed + packed).digest(out_len_bytes)


def run_bb84(
    n_qubits: int = 4096,
    eve: bool = False,
    noise: float = 0.02,
    sample_fraction: float = 0.2,
    rng: np.random.Generator | None = None,
) -> BB84Result:
    rng = rng or np.random.default_rng()

    # 1. Alice
    alice_bits = rng.integers(0, 2, n_qubits)
    alice_bases = rng.integers(0, 2, n_qubits)  # 0 = retilínea (+), 1 = diagonal (x)

    # 2. Eve: intercepta e reenvia (ataque intercept-resend)
    channel_bits = alice_bits.copy()
    channel_bases = alice_bases.copy()
    if eve:
        eve_bases = rng.integers(0, 2, n_qubits)
        wrong = eve_bases != alice_bases
        # base errada => resultado aleatório; ela reenvia na base dela
        channel_bits = np.where(wrong, rng.integers(0, 2, n_qubits), alice_bits)
        channel_bases = eve_bases

    # 3. Ruído do canal
    flips = rng.random(n_qubits) < noise
    channel_bits = channel_bits ^ flips

    # 4. Bob mede
    bob_bases = rng.integers(0, 2, n_qubits)
    mismatch = bob_bases != channel_bases
    bob_bits = np.where(mismatch, rng.integers(0, 2, n_qubits), channel_bits)

    # 5. Sifting
    keep = alice_bases == bob_bases
    a_sift, b_sift = alice_bits[keep], bob_bits[keep]
    sifted_len = int(keep.sum())

    # 6. Estimativa de QBER numa amostra pública
    n_sample = max(int(sifted_len * sample_fraction), 1)
    idx = rng.permutation(sifted_len)
    sample, rest = idx[:n_sample], idx[n_sample:]
    qber = float(np.mean(a_sift[sample] != b_sift[sample])) if sifted_len else 1.0

    stats = {
        "sample_size": n_sample,
        "noise": noise,
        "threshold": QBER_THRESHOLD,
    }

    # 7. Aborta se QBER alto
    if qber > QBER_THRESHOLD or len(rest) == 0:
        return BB84Result(n_qubits, sifted_len, qber, True, b"", eve, stats)

    # 8a. Correção de erros (simulada): Alice e Bob reconciliam a chave.
    # Custo realista ≈ 1.2 * h(QBER) bits vazados por bit (eficiência do Cascade/LDPC).
    reconciled = a_sift[rest]
    leaked = int(np.ceil(1.2 * _binary_entropy(qber) * len(rest)))

    # 8b. Amplificação de privacidade: descarta o que Eve pode saber.
    secure_len = int(len(rest) * (1 - _binary_entropy(qber))) - leaked - 64
    seed = rng.bytes(16)
    key = _privacy_amplification(reconciled, max(secure_len, 0), seed)
    stats.update({"reconciled_bits": len(rest), "leaked_bits": leaked, "secure_bits": max(secure_len, 0)})

    return BB84Result(n_qubits, sifted_len, qber, False, key, eve, stats)
