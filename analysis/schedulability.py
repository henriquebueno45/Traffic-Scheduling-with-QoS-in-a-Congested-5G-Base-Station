"""Analytical schedulability tests (Liu-Layland, response time, EDF).

Model (same parameters as the core; see core/src/threads.c and sim.h):
    task    burst            period    deadline  PRBs/packet
    voice   100*L packets    20 ms     20 ms     2
    video   40*L packets     33 ms     50 ms     10
    data    (sporadic, mean rate; treated as a background task)
Execution time C = burst PRBs / capacity (PRB/ms): the channel-service time.
L is relative load; default capacity is 50 PRB/ms.

Tests:
  1) Utilization U = sum(C_i/T_i); U >= 1 means overload (no policy delivers everything).
  2) Liu-Layland (RM, voice+video only): U <= n(2^(1/n) - 1), sufficient but not necessary.
  3) Fixed-priority response time: R_i = C_i + sum_{j higher priority} ceil(R_i/T_j) C_j.
     Schedulable if R_i <= D_i.
  4) EDF: processor demand h(t) = sum((floor((t-D_i)/T_i)+1)*C_i) <= t for every t.

Simplifications: fluid model (preemption every 1-ms slot), synchronous bursts (worst case),
and data included only in utilization/demand with C=20 PRB and mean period 2 ms/L.

Usage:
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
    c_ms: float  # Burst service time
    t_ms: float  # Period (or mean interval)
    d_ms: float  # Relative deadline


def build_tasks(load: float, capacity: float = 50.0) -> list[Task]:
    """Tasks in priority order (voice > video > data) for load `load`."""
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
    """Fixed point of R_i = C_i + sum_{j<i} ceil(R_i/T_j) C_j. Returns inf on divergence.

    If utilization by task i and all higher-priority tasks exceeds 1, the busy period
    never ends and later jobs accumulate delay, so the first-job result is invalid (inf).
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
    """Processor-demand test at every deadline instant through `horizon_ms`."""
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
            # prio protects voice and video even when U > 1 (data is the victim)
            "prio_voice_video_ok": rt[0] <= ts[0].d_ms and rt[1] <= ts[1].d_ms,
            # all classes require U <= 1 (data queue remains stable)
            "prio_all_ok": utilization(ts) <= 1 and rt[2] <= ts[2].d_ms
            and rt[0] <= ts[0].d_ms and rt[1] <= ts[1].d_ms,
            "edf_all_ok": edf_feasible(ts),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--loads", nargs="+", type=float, default=[1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0])
    ap.add_argument("--capacity", type=float, default=50.0, help="PRB/ms")
    ap.add_argument("--out", default=None, help="Output CSV (optional)")
    a = ap.parse_args()
    df = analyze(a.loads, a.capacity)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    sat = 1.0 / utilization(build_tasks(1.0, a.capacity))
    print(f"\nPredicted saturation load (U = 1): {sat:.2f}x")
    if a.out:
        df.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
