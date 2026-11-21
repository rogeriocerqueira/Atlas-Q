"""Experimento: QBER e tamanho da chave segura em função do ruído, com e sem espião.

Uso:  python -m scripts.experimento_qber
Gera docs/experimento_qber.csv e docs/experimento_qber.png
"""
import csv
from pathlib import Path

import numpy as np

from app.bb84 import QBER_THRESHOLD, run_bb84

OUT = Path(__file__).resolve().parent.parent / "docs"
rng = np.random.default_rng(42)
rows = []
for noise in np.linspace(0, 0.15, 16):
    for eve in (False, True):
        runs = [run_bb84(4096, eve=eve, noise=float(noise), rng=rng) for _ in range(10)]
        rows.append({
            "ruido": round(float(noise), 3),
            "espiao": eve,
            "qber_medio": round(float(np.mean([r.qber for r in runs])), 4),
            "bits_seguros_medio": int(np.mean([r.key_bits for r in runs])),
            "taxa_abortos": float(np.mean([r.aborted for r in runs])),
        })

OUT.mkdir(exist_ok=True)
with open(OUT / "experimento_qber.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)

try:
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    for eve, label, c in [(False, "sem espião", "#2fa37a"), (True, "com espião (intercept-resend)", "#e0475f")]:
        sub = [r for r in rows if r["espiao"] == eve]
        x = [r["ruido"] * 100 for r in sub]
        a1.plot(x, [r["qber_medio"] * 100 for r in sub], marker="o", label=label, color=c)
        a2.plot(x, [r["bits_seguros_medio"] for r in sub], marker="o", label=label, color=c)
    a1.axhline(QBER_THRESHOLD * 100, ls="--", color="gray", label="limite 11%")
    a1.set(xlabel="ruído do canal (%)", ylabel="QBER (%)", title="QBER medido")
    a2.set(xlabel="ruído do canal (%)", ylabel="bits", title="Chave segura por rodada (4096 qubits)")
    for a in (a1, a2):
        a.grid(alpha=.3); a.legend()
    fig.tight_layout(); fig.savefig(OUT / "experimento_qber.png", dpi=140)
    print("Gráfico salvo em docs/experimento_qber.png")
except ImportError:
    print("matplotlib não instalado: só o CSV foi gerado")
print("CSV salvo em docs/experimento_qber.csv")
