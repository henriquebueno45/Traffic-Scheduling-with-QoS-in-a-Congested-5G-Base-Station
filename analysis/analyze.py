"""Métricas por classe a partir do CSV de pacotes do núcleo.

Convenções:
  - tempos em ns relativos ao início; -1 = nunca ocorreu.
  - "entregue"   = end_ns >= 0
  - "no prazo"   = entregue e end_ns <= deadline_ns
  - pacotes descartados/não atendidos CONTAM no denominador (evita viés de
    sobrevivência); o atraso médio/percentis usam só os entregues.
  - QoS satisfaction = taxa de entrega x (1 - descumprimento de prazo)
                     = no_prazo / ofertados.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

CLASSES = ["voice", "video", "data"]


def jain(x) -> float:
    """Índice de Jain: (soma x)^2 / (n * soma x^2); 1 = perfeitamente justo."""
    x = np.asarray(x, dtype=float)
    return float(x.sum() ** 2 / (len(x) * (x**2).sum())) if (x**2).sum() > 0 else 1.0


def summarize(pk: pd.DataFrame, duration_s: float, warmup_s: float = 0.0,
              tail_s: float = 0.0) -> pd.DataFrame:
    """Uma linha por classe com as métricas.

    warmup_s / tail_s: só contam pacotes que CHEGARAM em [warmup_s, duration_s - tail_s].
    O warm-up evita o transitório inicial (filas vazias); o tail (>= maior prazo, 0,5 s)
    garante que todo pacote contado teve tempo de ser atendido: se ainda está na fila
    no fim, é descumprimento real e não artefato de truncar a simulação.
    """
    if warmup_s or tail_s:
        pk = pk[(pk["arrival_ns"] >= warmup_s * 1e9)
                & (pk["arrival_ns"] <= (duration_s - tail_s) * 1e9)]
    window_s = duration_s - warmup_s - tail_s
    rows = []
    for cls in CLASSES:
        p = pk[pk["class"] == cls]
        offered = len(p)
        done = p[p["end_ns"] >= 0]
        delay_ms = (done["end_ns"] - done["arrival_ns"]) / 1e6
        on_time = int((done["end_ns"] <= done["deadline_ns"]).sum())
        rows.append(
            {
                "class": cls,
                "offered": offered,
                "delivered": len(done),
                "dropped": int(p["dropped"].sum()),
                "unserved": int(((p["end_ns"] < 0) & (p["dropped"] == 0)).sum()),
                "delivery_rate": len(done) / offered if offered else np.nan,
                "qos": on_time / offered if offered else np.nan,
                "delay_mean_ms": delay_ms.mean() if len(done) else np.nan,
                "delay_p95_ms": delay_ms.quantile(0.95) if len(done) else np.nan,
                "delay_p99_ms": delay_ms.quantile(0.99) if len(done) else np.nan,
                "delay_max_ms": delay_ms.max() if len(done) else np.nan,
                "jitter_ms": delay_ms.std() if len(done) > 1 else np.nan,
                "throughput_prb_s": done["prbs"].sum() / window_s,
            }
        )
    return pd.DataFrame(rows)


def jain_over_classes(summary: pd.DataFrame) -> float:
    """Justiça entre classes medida sobre a taxa de entrega."""
    return jain(summary["delivery_rate"].fillna(0))


def scheduling_latency_us(slots: pd.DataFrame) -> pd.Series:
    """Atraso do despertar da thread escalonadora (actual - ideal), em us."""
    return (slots["actual_ns"] - slots["ideal_ns"]) / 1e3


def load_starvation(csv_path: str) -> pd.DataFrame:
    """Lê <csv>.starvation.csv do núcleo.

    starved_frac  = slots em que a classe tinha fila e recebeu 0 PRB / slots com fila
    max_starve_ms = maior espera seguida sem receber nenhum PRB
    """
    st = pd.read_csv(csv_path + ".starvation.csv")
    st["starved_frac"] = st["starved_slots"] / st["backlog_slots"].where(st["backlog_slots"] > 0)
    return st[["class", "starved_frac", "max_starve_ms"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="Resumo de uma execução do núcleo")
    ap.add_argument("csv", help="CSV de pacotes (ex.: results/run.csv)")
    ap.add_argument("--duration", type=float, default=10.0, help="s (usado na vazão)")
    a = ap.parse_args()

    pd.set_option("display.width", 200)
    s = summarize(pd.read_csv(a.csv), a.duration)
    print(s.round(3).to_string(index=False))
    print(f"\nJain (taxa de entrega entre classes): {jain_over_classes(s):.3f}")
    print("\nStarvation:")
    print(load_starvation(a.csv).round(3).to_string(index=False))
    try:
        lat = scheduling_latency_us(pd.read_csv(a.csv + ".slots.csv"))
        print(f"Latência de escalonamento (us): média={lat.mean():.1f} "
              f"P99={lat.quantile(0.99):.1f} máx={lat.max():.1f}")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
