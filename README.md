# gNB QoS Scheduler

A multithreaded 5G base-station (gNB) scheduler emulator in C/Pthreads, with a wireless channel model and statistical analysis in Python. It compares FIFO, strict-priority, EDF, and DWRR scheduling of voice, video, and data traffic under congestion, and measures how channel quality (path loss, fading, MRC antenna diversity) changes the outcome.

Course project for Concurrency and Real-Time Systems and Wireless Communications (UFSC). The project plan is in [docs/Final_Work_Plan.md](docs/Final_Work_Plan.md).

## Results at a Glance

- Strict priority protects voice and video best: SLA capacity 2.20x on the fixed channel versus 1.50x for FIFO; data is sacrificed first.
- Four MRC antenna branches raise SLA capacity and reduce seed-to-seed variance (prio: 1.47x with L=1, 1.98x with L=4).
- The fixed channel is deterministic; variability under Rayleigh fading comes from each seed's fading realization.
- Short runs (< 10 s, untrimmed) are biased; use 1.0 s warm-up and 0.5 s tail trimming.

![SLA capacity by policy and channel](results/exp/E1_capacity.png)

Full results, hypothesis verdicts, strengths, and limitations: **[results/RESULTS_SUMMARY.md](results/RESULTS_SUMMARY.md)**. Protocol: [results/EXPERIMENTS.md](results/EXPERIMENTS.md).

## Quick Start

On Linux (see [docs/SETUP.md](docs/SETUP.md) for dependencies and real-time setup):

```bash
make -C core                                                    # build
python3 -m venv .venv && source .venv/bin/activate
pip install numpy pandas matplotlib scipy pytest

core/build/gnb_sim --policy prio --load 1.5 --duration 10 --seed 1 --cpu 2 --out results/run.csv
python3 -m analysis.analyze results/run.csv --duration 10      # per-class metrics

python3 -m pytest -q tests                                      # tests
```

The last line of the simulator output ends with `rt=1` when real-time scheduling is active. `rt=0` runs are not valid real-time measurements.

## Documentation

| Document | Contents |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Dependencies, real-time Linux setup, installation check |
| [docs/RUNNING_EXPERIMENTS.md](docs/RUNNING_EXPERIMENTS.md) | Running E1-E5, options, generic multi-CPU command, report generation |
| [docs/DESIGN.md](docs/DESIGN.md) | Threads, policies, logs, priority inversion, schedulability, extending the project |
| [results/RESULTS_SUMMARY.md](results/RESULTS_SUMMARY.md) | Results, strengths, limitations |
| [results/EXPERIMENTS.md](results/EXPERIMENTS.md) | Pre-registered protocol and verdicts |
| [docs/Final_Work_Plan.md](docs/Final_Work_Plan.md) | Project plan |

## Repository Structure

```text
core/                         Real-time core (C, Pthreads, Linux)
  Makefile                    make | make debug | make clean
  src/sim.h                   Shared types and state (read first)
  src/threads.c               Producers (voice/video/data), scheduler, and monitor
  src/policy.c                Policies: FIFO, strict priority, EDF, DWRR, and priority floor
  src/channel.c               Fixed slot capacity or capacity from a CSV trace
  src/main.c                  CLI, SCHED_FIFO, CPU affinity, and log output
channel/channel_model.py      Path loss + shadowing + Rayleigh (Jakes) + MRC -> PRB trace
analysis/analyze.py           Per-class metrics for one execution
analysis/sweep.py             Policy × load × seed sweep, bootstrap CI, and plots
analysis/experiments.py       Pre-registered experiments E1-E5 (parallel, resumable)
analysis/exp_report.py        Tables, plots, and verdicts for E1-E5
analysis/schedulability.py    Analytical schedulability tests
analysis/producers.py         Producer wake-up latency
analysis/validate_channel.py  Channel model versus theory
analysis/inversion.py         Priority-inversion experiment
tests/test_python.py          Numerical tests (pytest)
results/                      Outputs: exp/ (E1-E5), summaries, legacy/ (superseded sweeps)
docs/                         Setup, experiments, design notes, project plan
```


## License

MIT, see [LICENSE](LICENSE).
