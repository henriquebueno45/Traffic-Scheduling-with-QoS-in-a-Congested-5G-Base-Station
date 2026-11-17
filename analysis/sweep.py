"""Varredura automática: políticas x cargas x sementes -> CSV + gráfico.

Roda o núcleo em sequência (NÃO em paralelo: mediria uma CPU disputada),
resume cada execução e agrega média e IC 95% (bootstrap) entre sementes.

Exemplo:
    python -m analysis.sweep --loads 0.5 1 1.5 2 2.5 --seeds 5 --duration 5
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from analysis.analyze import CLASSES, jain_over_classes, load_starvation, summarize

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "core" / "build" / "gnb_sim"
METRICS = ["qos", "delivery_rate", "delay_p95_ms", "delay_mean_ms", "max_starve_ms"]


def make_trace(tag: str, seed: int, duration: float, distance: float, antennas: int,
               shadow_sigma_db: float = 0.0) -> str:
    """Gera um traço Rayleigh novo por semente (realizações independentes).

    shadow_sigma_db=0 isola o efeito do desvanecimento rápido; com sigma > 0 o
    sombreamento (1 sorteio por traço) domina a variância entre sementes.
    """
    from channel.channel_model import ChannelConfig, generate_prbs

    cfg = ChannelConfig(distance_m=distance, antennas=antennas, shadow_sigma_db=shadow_sigma_db)
    prbs = generate_prbs(int(duration * 1000), cfg, seed)
    path = ROOT / "results" / f"tmp_trace_{tag}.csv"
    path.write_text("slot,prbs\n" + "".join(f"{i},{p}\n" for i, p in enumerate(prbs)))
    return str(path)


def run_once(policy: str, load: float, seed: int, duration: float, trace, cpu) -> pd.DataFrame:
    out = ROOT / "results" / "tmp_run.csv"
    cmd = [str(BIN), "--policy", policy, "--load", str(load), "--seed", str(seed),
           "--duration", str(duration), "--out", str(out), "--quiet"]
    if trace:
        cmd += ["--trace", trace]
    if cpu is not None:
        cmd += ["--cpu", str(cpu)]
    subprocess.run(cmd, check=True)
    s = summarize(pd.read_csv(out), duration)
    s = s.merge(load_starvation(str(out)), on="class")
    s["jain"] = jain_over_classes(s)
    return s


def bootstrap_ci(x: pd.Series, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """IC 95% percentil por bootstrap da média (respeita limites como [0, 1])."""
    v = x.to_numpy(dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return (float(v.mean()), float(v.mean())) if len(v) else (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def aggregate(raw: pd.DataFrame) -> pd.DataFrame:
    """Média e IC 95% (bootstrap) entre sementes por (política, carga, classe)."""
    rows = []
    for (pol, load, cls), g in raw.groupby(["policy", "load", "class"]):
        row = {"policy": pol, "load": load, "class": cls, "n": len(g)}
        for m in METRICS:
            row[f"{m}_mean"] = g[m].mean()
            row[f"{m}_lo"], row[f"{m}_hi"] = bootstrap_ci(g[m])
        rows.append(row)
    return pd.DataFrame(rows)


def plot(agg: pd.DataFrame, path: Path, metric: str = "qos") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(12, 3.5), sharey=(metric == "qos"))
    for ax, cls in zip(axes, CLASSES):
        for pol, g in agg[agg["class"] == cls].groupby("policy"):
            m = g[f"{metric}_mean"]
            ax.errorbar(g["load"], m, yerr=[m - g[f"{metric}_lo"], g[f"{metric}_hi"] - m],
                        marker="o", capsize=3, label=pol)
        ax.set_title(cls)
        ax.set_xlabel("carga (x carga base)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel(metric)
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--policies", nargs="+", default=["fifo", "prio", "edf", "dwrr"])
    ap.add_argument("--loads", nargs="+", type=float, default=[0.5, 1, 1.5, 2, 2.5])
    ap.add_argument("--seeds", type=int, default=5, help="repetições por ponto")
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--trace", default=None, help="traço de canal fixo (CSV)")
    ap.add_argument("--rayleigh", action="store_true",
                    help="gera um traço Rayleigh por semente (usa --distance/--antennas)")
    ap.add_argument("--distance", type=float, default=160.0, help="m (com --rayleigh)")
    ap.add_argument("--shadow-sigma", type=float, default=0.0, help="dB (com --rayleigh)")
    ap.add_argument("--antennas", type=int, default=1, help="MRC (com --rayleigh)")
    ap.add_argument("--cpu", type=int, default=None)
    ap.add_argument("--tag", default="sweep", help="prefixo dos arquivos de saída")
    a = ap.parse_args()

    rows = []
    for pol in a.policies:
        for load in a.loads:
            for seed in range(1, a.seeds + 1):
                print(f"{pol} load={load} seed={seed}", flush=True)
                trace = a.trace
                if a.rayleigh:
                    trace = make_trace(a.tag, seed, a.duration, a.distance, a.antennas,
                                       a.shadow_sigma)
                s = run_once(pol, load, seed, a.duration, trace, a.cpu)
                s["policy"], s["load"], s["seed"] = pol, load, seed
                rows.append(s)
    raw = pd.concat(rows, ignore_index=True)

    agg = aggregate(raw)

    res = ROOT / "results"
    raw.to_csv(res / f"{a.tag}_raw.csv", index=False)
    agg.to_csv(res / f"{a.tag}_agg.csv", index=False)
    plot(agg, res / f"{a.tag}_qos.png", "qos")
    print(f"salvo em results/{a.tag}_*.csv e results/{a.tag}_qos.png")


if __name__ == "__main__":
    main()
