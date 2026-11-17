"""Latência de despertar das produtoras, com e sem mlockall.

Latência = (instante em que a thread acordou) - (instante ideal de clock_nanosleep).
Compara `--no-mlock` x padrão (mlockall) e conta page faults (getrusage dos filhos).
Gera results/produtoras_summary.csv, results/produtoras_raw.csv e results/produtoras.png.

Exemplo:
    python -m analysis.producers --seeds 5 --duration 10 --load 1.5 --cpu 2
"""
from __future__ import annotations

import argparse
import resource
import subprocess

import numpy as np
import pandas as pd

from analysis.analyze import CLASSES
from analysis.sweep import BIN, ROOT

VARIANTS = {"sem mlockall": ["--no-mlock"], "com mlockall": []}


def run(variant: str, args: list[str], seed: int, duration: float, load: float, cpu: int):
    out = ROOT / "results" / "tmp_prod.csv"
    cmd = [str(BIN), "--policy", "prio", "--load", str(load), "--seed", str(seed),
           "--duration", str(duration), "--cpu", str(cpu), "--out", str(out), "--quiet", *args]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    df = pd.read_csv(str(out) + ".producers.csv")
    df["latency_us"] = df["latency_ns"] / 1e3
    df["variant"], df["seed"] = variant, seed
    locked = "memlock baixo" not in res.stderr and "mlockall" not in res.stderr
    faults = {"minflt": after.ru_minflt - before.ru_minflt,
              "majflt": after.ru_majflt - before.ru_majflt}
    return df, faults, locked


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--load", type=float, default=1.5)
    ap.add_argument("--cpu", type=int, default=2)
    a = ap.parse_args()

    dfs, fl = [], []
    soft, _ = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    can_lock = soft == resource.RLIM_INFINITY or soft >= 512 << 20
    for variant, extra in VARIANTS.items():
        if variant == "com mlockall" and not can_lock:
            print("AVISO: memlock baixo (ulimit -l); pulando a variante com mlockall")
            continue
        for seed in range(1, a.seeds + 1):
            print(variant, seed, flush=True)
            df, faults, locked = run(variant, extra, seed, a.duration, a.load, a.cpu)
            if variant == "com mlockall" and not locked:
                print("AVISO: mlockall não ficou ativo (veja memlock em limits.d)")
            dfs.append(df)
            fl.append({"variant": variant, "seed": seed, **faults})
    raw = pd.concat(dfs, ignore_index=True)

    rows = []
    for (variant, cls), g in raw.groupby(["variant", "class"]):
        v = g["latency_us"].to_numpy()
        rows.append({"variant": variant, "class": cls, "n": len(v), "mean_us": v.mean(),
                     "p50_us": np.percentile(v, 50), "p99_us": np.percentile(v, 99),
                     "p999_us": np.percentile(v, 99.9), "max_us": v.max()})
    summ = pd.DataFrame(rows)
    faults = pd.DataFrame(fl).groupby("variant")[["minflt", "majflt"]].mean().round(0)

    res = ROOT / "results"
    summ.to_csv(res / "produtoras_summary.csv", index=False)
    faults.to_csv(res / "produtoras_pagefaults.csv")
    raw.to_csv(res / "produtoras_raw.csv", index=False)
    pd.set_option("display.width", 200)
    print(summ.round(1).to_string(index=False))
    print("\nPage faults médios por execução:\n", faults.to_string())

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(12, 3.5), sharey=True)
    for ax, cls in zip(axes, CLASSES):
        for variant, g in raw[raw["class"] == cls].groupby("variant"):
            x = np.sort(g["latency_us"].to_numpy())
            ax.plot(x, 1 - np.arange(1, len(x) + 1) / len(x) + 1e-9, label=variant)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(cls)
        ax.set_xlabel("latência de despertar (µs)")
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel("P(latência > x)")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(res / "produtoras.png", dpi=150)
    (res / "tmp_prod.csv").unlink(missing_ok=True)
    print("salvo em results/produtoras_*.csv e results/produtoras.png")


if __name__ == "__main__":
    main()
