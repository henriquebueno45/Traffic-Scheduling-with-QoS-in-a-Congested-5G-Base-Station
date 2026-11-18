"""Per-class metrics derived from the core packet CSV.

Conventions:
  - Times are in ns relative to startup; -1 means the packet never occurred.
  - "delivered" means end_ns >= 0.
  - "on time" means delivered and end_ns <= deadline_ns.
  - Dropped or unserved packets count in the denominator to avoid
    survivor bias; mean delay and percentiles use delivered packets only.
  - QoS satisfaction = delivery rate x (1 - deadline-miss rate)
                     = on_time / offered.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

CLASSES = ["voice", "video", "data"]


def jain(x) -> float:
    """Jain index: (sum x)^2 / (n * sum x^2); 1 means perfectly fair."""
    x = np.asarray(x, dtype=float)
    return float(x.sum() ** 2 / (len(x) * (x**2).sum())) if (x**2).sum() > 0 else 1.0


def summarize(pk: pd.DataFrame, duration_s: float, warmup_s: float = 0.0,
              tail_s: float = 0.0) -> pd.DataFrame:
    """One row per class containing its metrics.

    warmup_s / tail_s: count only packets that arrived within
    [warmup_s, duration_s - tail_s]. Warm-up avoids the initial transient (empty queues);
    the tail (at least the largest deadline, 0.5 s) ensures every counted packet had
    time to be served. If it is still queued at the end, that is a real deadline miss,
    not an artifact of truncating the simulation.
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
    """Fairness between classes measured from their delivery rates."""
    return jain(summary["delivery_rate"].fillna(0))


def scheduling_latency_us(slots: pd.DataFrame) -> pd.Series:
    """Scheduler-thread wake delay (actual - ideal), in microseconds."""
    return (slots["actual_ns"] - slots["ideal_ns"]) / 1e3


def load_starvation(csv_path: str) -> pd.DataFrame:
    """Read <csv>.starvation.csv from the core.

    starved_frac  = slots where the class had backlog and received 0 PRB / slots with backlog
    max_starve_ms = longest consecutive wait without receiving any PRB
    """
    st = pd.read_csv(csv_path + ".starvation.csv")
    st["starved_frac"] = st["starved_slots"] / st["backlog_slots"].where(st["backlog_slots"] > 0)
    return st[["class", "starved_frac", "max_starve_ms"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="Summary of one core execution")
    ap.add_argument("csv", help="Packet CSV (for example, results/run.csv)")
    ap.add_argument("--duration", type=float, default=10.0, help="seconds (used for throughput)")
    a = ap.parse_args()

    pd.set_option("display.width", 200)
    s = summarize(pd.read_csv(a.csv), a.duration)
    print(s.round(3).to_string(index=False))
    print(f"\nJain (delivery-rate fairness across classes): {jain_over_classes(s):.3f}")
    print("\nStarvation:")
    print(load_starvation(a.csv).round(3).to_string(index=False))
    try:
        lat = scheduling_latency_us(pd.read_csv(a.csv + ".slots.csv"))
        print(f"Scheduler latency (us): mean={lat.mean():.1f} "
              f"P99={lat.quantile(0.99):.1f} max={lat.max():.1f}")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
