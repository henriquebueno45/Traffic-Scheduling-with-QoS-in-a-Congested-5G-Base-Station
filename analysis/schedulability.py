"""Teste de escalonabilidade analítico (Liu-Layland, tempo de resposta, EDF).

Modelo (mesmos parâmetros do núcleo, ver core/src/threads.c e sim.h):
    tarefa  rajada            período   deadline  PRBs/pacote
    voz     100*L pacotes     20 ms     20 ms     2
    vídeo    40*L pacotes     33 ms     50 ms     10
    dados   (esporádica, taxa média; tratada como tarefa de fundo)
Tempo de execução C = PRBs da rajada / capacidade (PRB/ms): é o tempo de "serviço" no canal.
L = carga relativa; capacidade padrão 50 PRB/ms.

Testes:
  1) Utilização U = soma(C_i/T_i); U >= 1 => sobrecarga (nenhuma política entrega tudo).
  2) Liu-Layland (RM, só voz+vídeo): U <= n(2^(1/n) - 1)  (suficiente, não necessário).
  3) Tempo de resposta de prioridade fixa: R_i = C_i + sum_{j de prio maior} ceil(R_i/T_j) C_j.
     Escalonável se R_i <= D_i.
  4) EDF: demanda de processador h(t) = sum( (floor((t - D_i)/T_i) + 1) * C_i ) <= t, para todo t.

Simplificações: modelo fluido (preempção a cada slot de 1 ms), rajadas síncronas (pior caso),
dados contados apenas na utilização/demanda com C = 20 PRB e período médio 2 ms / L.

Uso:
    python -m analysis.schedulability --loads 1.0 1.2 1.4 1.6 1.8 2.0
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Task:
    name: str
    c_ms: float  # tempo de serviço da rajada
    t_ms: float  # período (ou intervalo médio)
    d_ms: float  # deadline relativo


def build_tasks(load: float, capacity: float = 50.0) -> list[Task]:
    """Tarefas em ordem de prioridade (voz > vídeo > dados) para a carga `load`."""
    return [
        Task("voice", 100 * load * 2 / capacity, 20.0, 20.0),
        Task("video", 40 * load * 10 / capacity, 33.0, 50.0),
        Task("data", 20 / capacity, 2.0 / load, 500.0),
    ]


def utilization(tasks: list[Task]) -> float:
    return sum(t.c_ms / t.t_ms for t in tasks)


def liu_layland_bound(n: int) -> float:
    return n * (2 ** (1 / n) - 1)


def response_time(tasks: list[Task], i: int, limit_ms: float = 1e4) -> float:
    """Ponto fixo de R_i = C_i + sum_{j<i} ceil(R_i/T_j) C_j. Retorna inf se divergir.

    Se a utilização de i e das tarefas mais prioritárias passa de 1, o período ocupado nunca
    termina e os jobs seguintes acumulam atraso: o R do primeiro job não vale (inf).
    """
    if sum(t.c_ms / t.t_ms for t in tasks[:i + 1]) > 1:
        return math.inf
    r = tasks[i].c_ms
    while r <= limit_ms:
        nxt = tasks[i].c_ms + sum(math.ceil(r / t.t_ms) * t.c_ms for t in tasks[:i])
        if abs(nxt - r) < 1e-9:
            return r
        r = nxt
    return math.inf


def edf_feasible(tasks: list[Task], horizon_ms: float = 2000.0) -> bool:
    """Teste de demanda de processador em todos os instantes de deadline até `horizon_ms`."""
    if utilization(tasks) > 1:
        return False
    points = sorted({t.d_ms + k * t.t_ms for t in tasks
                     for k in range(int(horizon_ms / t.t_ms) + 1)
                     if t.d_ms + k * t.t_ms <= horizon_ms})
    for p in points:
        demand = sum((math.floor((p - t.d_ms) / t.t_ms) + 1) * t.c_ms
                     for t in tasks if p >= t.d_ms)
        if demand > p + 1e-9:
            return False
    return True


def analyze(loads: list[float], capacity: float = 50.0) -> pd.DataFrame:
    rows = []
    for load in loads:
        ts = build_tasks(load, capacity)
        rt = [response_time(ts, i) for i in range(3)]
        rows.append({
            "load": load,
            "U": round(utilization(ts), 3),
            "LL_bound_voice_video": round(liu_layland_bound(2), 3),
            "U_voice_video": round(sum(t.c_ms / t.t_ms for t in ts[:2]), 3),
            "R_voice_ms": round(rt[0], 2),
            "R_video_ms": round(rt[1], 2),
            # prio protege voz e vídeo mesmo com U > 1 (dados é quem sofre)
            "prio_voice_video_ok": rt[0] <= ts[0].d_ms and rt[1] <= ts[1].d_ms,
            # todas as classes: exige também U <= 1 (fila de dados estável)
            "prio_all_ok": utilization(ts) <= 1 and rt[2] <= ts[2].d_ms
            and rt[0] <= ts[0].d_ms and rt[1] <= ts[1].d_ms,
            "edf_all_ok": edf_feasible(ts),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--loads", nargs="+", type=float, default=[1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0])
    ap.add_argument("--capacity", type=float, default=50.0, help="PRB/ms")
    ap.add_argument("--out", default=None, help="CSV de saída (opcional)")
    a = ap.parse_args()
    df = analyze(a.loads, a.capacity)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    sat = 1.0 / utilization(build_tasks(1.0, a.capacity))
    print(f"\nCarga de saturação prevista (U = 1): {sat:.2f}x")
    if a.out:
        df.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
