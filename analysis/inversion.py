"""Priority-inversion experiment (Montez): no hog, no inheritance, and inheritance.

Pin everything to one CPU with SCHED_FIFO; the scheduler (priority 90) competes for the mutex
with an accounting thread (priority 20) that holds it for --cs-us, while a hog thread
(priority 50) consumes CPU. See the comments in core/src/threads.c.

Example:
    python -m analysis.inversion --seeds 5 --duration 10 --cpu 2
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "core" / "build" / "gnb_sim"

SCENARIOS = {
    "baseline (no hog)": ["--hog-ms", "0"],
    "inversion (no inheritance)": [],
    "priority inheritance": ["--prio-inherit"],
}


def run(extra: list[str], seed: int, a: argparse.Namespace) -> dict:
    out = ROOT / "results" / "tmp_inv.csv"
    cmd = [str(BIN), "--policy", a.policy, "--load", str(a.load), "--seed", str(seed),
           "--duration", str(a.duration), "--cpu", str(a.cpu), "--inversion",
           "--cs-us", str(a.cs_us), "--hog-ms", str(a.hog_ms), "--quiet",
           "--out", str(out), *extra]
    if "--hog-ms" in extra: # The baseline scenario overrides the default hog value
        cmd = cmd[: cmd.index("--hog-ms")] + cmd[cmd.index("--hog-ms") + 2 :]
    subprocess.run(cmd, check=True)

    pk = pd.read_csv(out)
    sl = pd.read_csv(str(out) + ".slots.csv")
    v = pk[(pk["class"] == "voice") & (pk["end_ns"] >= 0)]
    delay = (v["end_ns"] - v["arrival_ns"]) / 1e6
    return {
        "lock_wait_max_ms": sl["lock_wait_ns"].max() / 1e6,
        "lock_wait_p99_ms": sl["lock_wait_ns"].quantile(0.99) / 1e6,
        "voice_delay_p99_ms": delay.quantile(0.99),
        "voice_delay_max_ms": delay.max(),
        "voice_deadline_miss": float((v["end_ns"] > v["deadline_ns"]).mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--cpu", type=int, default=2)
    ap.add_argument("--policy", default="prio")
    ap.add_argument("--load", type=float, default=1.0)
    ap.add_argument("--cs-us", type=int, default=2000)
    ap.add_argument("--hog-ms", type=float, default=20.0)
    ap.add_argument("--tag", default="priority_inversion")
    a = ap.parse_args()

    rows = []
    for name, extra in SCENARIOS.items():
        for seed in range(1, a.seeds + 1):
            print(f"{name} seed={seed}", flush=True)
            rows.append({"scenario": name, "seed": seed, **run(extra, seed, a)})
    raw = pd.DataFrame(rows)
    res = ROOT / "results"
    raw.to_csv(res / f"{a.tag}_raw.csv", index=False)

    summary = raw.drop(columns="seed").groupby("scenario", sort=False).agg(["mean", "std"])
    summary.to_csv(res / f"{a.tag}_summary.csv")
    pd.set_option("display.width", 200)
    print(raw.drop(columns="seed").groupby("scenario", sort=False).mean().round(3).to_string())

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(12, 3.5))
    for ax, col, title in zip(
        axes,
        ["lock_wait_max_ms", "voice_delay_p99_ms", "voice_deadline_miss"],
        ["Maximum scheduler mutex wait (ms)", "Voice: P99 delay (ms)",
         "Voice: fraction missing deadline"],
    ):
        m = raw.groupby("scenario", sort=False)[col]
        ax.bar(range(3), m.mean(), yerr=m.std(), capsize=4, color=["#999", "#d62728", "#2ca02c"])
        ax.set_xticks(range(3), ["baseline", "no\ninheritance", "with\ninheritance"])
        ax.set_title(title, fontsize=9)
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(res / f"{a.tag}.png", dpi=150)
    print(f"saved to results/{a.tag}_*.csv and results/{a.tag}.png")


if __name__ == "__main__":
    main()
