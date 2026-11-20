"""Run experiments E1 through E6 from the protocol (results/EXPERIMENTS.md).

    E1  SLA capacity: fixed/Rayleigh L=1/2/4 channels with equal mean x policy x load  (H1, H2)
    E2  minimum floor (prio_floor) under overload                                   (H3)
    E3  staggered bursts (--stagger K)                                              (H4)
    E4  truncation bias: 4 s without trim x 20 s with warm-up/tail                 (H6)
    E5  coherence-time speed x deadline, Rayleigh L=1                              (H5)
    E6  exploratory (not pre-registered): log-normal shadowing sigma 0 versus 6 dB, L=1/4

Each core execution is independent and runs on a separate CPU. Choose CPUs from distinct
physical cores (`lscpu -e`). Output is incremental and resumable.

Example:
    python -m analysis.experiments run E1 E2 E3 E4 E5 --cpus 1 2 3
    python -m analysis.experiments run E1 --seeds 2 --cpus 1 2 3 --tag pilot  # quick test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from analysis.analyze import load_starvation, summarize
from analysis.sweep import BIN, ROOT
from analysis.validate_channel import theory_prbs
from channel.channel_model import ChannelConfig, generate_prbs

OUT = ROOT / "results" / "exp"
WARMUP_S, TAIL_S = 1.0, 0.5
TARGET_MEAN_PRBS = 50.0
POLICIES = ["fifo", "prio", "edf", "dwrr", "prio_floor"]
# Wide grid: with 6 dB shadowing the per-seed capacity spans roughly 0.3x to 3x nominal
E6_LOADS = [0.3, 0.5, 0.7, 0.9, 1.0, 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.2, 2.4, 2.8, 3.2, 4.0]
FLOOR_DATA_DEFAULT = 2  # Floor used when prio_floor appears in E1


def equal_mean_distance(antennas: int, target: float = TARGET_MEAN_PRBS) -> float:
    """Return the distance (m) where theoretical mean PRBs with MRC and `antennas` branches equals `target`."""
    return float(brentq(lambda d: theory_prbs(d, antennas) - target, 20.0, 2000.0))


@dataclass(frozen=True)
class Job:
    exp: str
    chan: str  # "fixed" | "ray"
    antennas: int
    distance: float
    speed: float
    policy: str
    load: float
    seed: int
    duration: float
    stagger: int = 1
    floor_video: int = 0
    floor_data: int = 0
    shadow_db: float = 0.0

    def key(self) -> str:
        # shadow_db is omitted at 0 so keys of E1-E5 stay unchanged
        d = asdict(self)
        if not d["shadow_db"]:
            del d["shadow_db"]
        return "|".join(str(v) for v in d.values())

    @property
    def scen(self) -> str:
        return "fixed" if self.chan == "fixed" else f"L{self.antennas}"


def _jobs(exp, scens, policies, loads, seeds, duration, **kw) -> list[Job]:
    return [Job(exp, c, a, d, v, p, ld, s, duration, **kw)
            for (c, a, d, v) in scens for p in policies for ld in loads for s in seeds]


def build_jobs(exp: str, n_seeds: int | None, e1_loads: list[float] | None = None,
               e1_duration: float = 6.0) -> list[Job]:
    d1 = {L: equal_mean_distance(L) for L in (1, 2, 4)}
    fixed = ("fixed", 1, 0.0, 1.5)
    ray = lambda L, v=1.5: ("ray", L, d1[L], v)  # noqa: E731
    seeds = lambda n: range(1, (n_seeds or n) + 1)  # noqa: E731

    if exp == "E1":
        loads = e1_loads or [1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0, 2.2, 2.3, 2.4]
        jobs = []
        for pol in POLICIES:
            jobs += _jobs("E1", [fixed, ray(1), ray(2), ray(4)], [pol], loads, seeds(10), e1_duration,
                          floor_data=FLOOR_DATA_DEFAULT if pol == "prio_floor" else 0)
        return jobs
    if exp == "E2":
        jobs = []
        for fv, fd in [(0, 0), (0, 1), (0, 2), (0, 4), (0, 8), (5, 2)]:
            jobs += _jobs("E2", [fixed, ray(1)], ["prio_floor"], [1.6, 2.0], seeds(20), 6.0,
                          floor_video=fv, floor_data=fd)
        return jobs
    if exp == "E3":
        jobs = []
        for k in (1, 2, 5, 10, 20):
            jobs += _jobs("E3", [fixed], ["fifo", "prio", "edf", "dwrr"], [1.5, 1.8], seeds(10),
                          6.0, stagger=k)
        return jobs
    if exp == "E4":
        return (_jobs("E4", [fixed], ["fifo", "prio", "edf"], [1.8, 2.0], seeds(10), 4.0)
                + _jobs("E4", [fixed], ["fifo", "prio", "edf"], [1.8, 2.0], seeds(10), 20.0))
    if exp == "E5":
        return _jobs("E5", [ray(1, v) for v in (0.3, 1.5, 5.0, 15.0, 30.0)], ["fifo", "prio"],
                     [1.3, 1.5], seeds(20), 10.0)
    if exp == "E6":
        jobs = []
        for sigma in (0.0, 6.0):
            for pol in ("fifo", "prio"):
                jobs += _jobs("E6", [ray(1), ray(4)], [pol], E6_LOADS, seeds(30), 6.0,
                              shadow_db=sigma)
        return jobs
    raise SystemExit(f"unknown experiment: {exp}")


def run_job(job: Job, cpu: int, workdir: Path) -> pd.DataFrame:
    """Run the core once and return per-class metrics with and without trimming."""
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "run.csv"
    cmd = [str(BIN), "--policy", job.policy, "--load", str(job.load), "--seed", str(job.seed),
           "--duration", str(job.duration), "--out", str(out), "--cpu", str(cpu), "--quiet",
           "--stagger", str(job.stagger), "--floor-video", str(job.floor_video),
           "--floor-data", str(job.floor_data)]
    if job.chan == "ray":
        cfg = ChannelConfig(distance_m=job.distance, antennas=job.antennas,
                            speed_mps=job.speed, shadow_sigma_db=job.shadow_db)
        prbs = generate_prbs(int(job.duration * 1000) + 16, cfg, job.seed)
        trace = workdir / "trace.csv"
        trace.write_text("slot,prbs\n" + "".join(f"{i},{p}\n" for i, p in enumerate(prbs)))
        cmd += ["--trace", str(trace)]
    subprocess.run(cmd, check=True)
    pk = pd.read_csv(out)
    st = load_starvation(str(out))
    frames = []
    for trim, (w, t) in {"none": (0.0, 0.0), "trim": (WARMUP_S, TAIL_S)}.items():
        s = summarize(pk, job.duration, w, t).merge(st, on="class")
        s["trim"] = trim
        frames.append(s)
    df = pd.concat(frames, ignore_index=True)
    for k, v in asdict(job).items():
        df[k] = v
    df["scen"] = job.scen
    df["job_key"] = job.key()
    cols = ["job_key", "exp", "scen", "chan", "antennas", "distance", "speed", "policy", "load",
               "seed", "duration", "stagger", "floor_video", "floor_data", "trim", "class",
               "offered", "delivered", "qos", "delivery_rate", "delay_mean_ms", "delay_p95_ms",
               "throughput_prb_s", "starved_frac", "max_starve_ms"]
    return df[cols + (["shadow_db"] if job.exp == "E6" else [])]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(tag: str, exps: list[str], cpus: list[int]) -> None:
    """Record everything needed to reproduce and verify an execution."""
    means = {}
    for L in (1, 2, 4):
        d = equal_mean_distance(L)
        sim = [generate_prbs(10000, ChannelConfig(distance_m=d, antennas=L, shadow_sigma_db=0.0),
                             s).mean() for s in range(1, 11)]
        means[f"L{L}"] = {"distance_m": round(d, 2), "theory_mean_prbs": TARGET_MEAN_PRBS,
                          "sim_mean_prbs": round(float(np.mean(sim)), 2)}
    manifest = {
        "tag": tag, "experiments": exps, "cpus": cpus, "argv": sys.argv,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"), "warmup_s": WARMUP_S, "tail_s": TAIL_S,
        "machine": platform.platform(), "python": platform.python_version(),
        "numpy": np.__version__, "pandas": pd.__version__,
        "binary_sha256": sha256(BIN),
        "sources_sha256": {p.name: sha256(p) for p in sorted((ROOT / "core" / "src").glob("*"))},
        "equal_mean_channels": means,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"manifest_{tag}.json").write_text(json.dumps(manifest, indent=2))


def cmd_run(a: argparse.Namespace) -> None:
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {0, 4})  # Keep the Python process away from measurement CPUs
    tag = a.tag or "_".join(a.exps)
    write_manifest(tag, a.exps, a.cpus)
    for exp in a.exps:
        jobs = build_jobs(exp, a.seeds, a.e1_loads, a.e1_duration)
        csv = OUT / f"{exp}{'_' + a.tag if a.tag else ''}_raw.csv"
        done = set(pd.read_csv(csv, usecols=["job_key"])["job_key"]) if csv.exists() else set()
        todo = [j for j in jobs if j.key() not in done]
        print(f"{exp}: {len(jobs)} executions, {len(todo)} pending", flush=True)
        if a.dry:
            continue
        cpus: queue.Queue[int] = queue.Queue()
        for c in a.cpus:
            cpus.put(c)

        def work(job: Job) -> pd.DataFrame:
            cpu = cpus.get()
            try:
                return run_job(job, cpu, OUT / "tmp" / f"cpu{cpu}")
            finally:
                cpus.put(cpu)

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=len(a.cpus)) as ex:
            futs = [ex.submit(work, j) for j in todo]
            for i, f in enumerate(as_completed(futs), 1):
                f.result().to_csv(csv, mode="a", header=not csv.exists(), index=False)
                if i % 25 == 0 or i == len(futs):
                    el = time.time() - t0
                    print(f"  {exp} {i}/{len(futs)}  {el / 60:.1f} min, "
                          f"remaining ~{el / i * (len(futs) - i) / 60:.1f} min", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("exps", nargs="+", choices=["E1", "E2", "E3", "E4", "E5", "E6"])
    r.add_argument("--cpus", nargs="+", type=int, default=[1, 2, 3])
    r.add_argument("--seeds", type=int, default=None, help="override seed count (pilot)")
    r.add_argument("--e1-loads", nargs="+", type=float, default=None, help="E1 load grid")
    r.add_argument("--e1-duration", type=float, default=6.0, help="E1 run length in seconds")
    r.add_argument("--tag", default="", help="output filename suffix (for example: pilot)")
    r.add_argument("--dry", action="store_true", help="count executions only")
    r.set_defaults(fn=cmd_run)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
