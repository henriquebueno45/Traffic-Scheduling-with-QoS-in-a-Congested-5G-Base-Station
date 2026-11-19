# gNB QoS Scheduler – Multithread Emulator (C/Pthreads) + Channel and Analysis (Python)

The complete project plan is available in `Final_Work_Plan.md`.

## Repository Structure

```text
core/                         Real-time core (C, Pthreads, Linux)
  Makefile                    make | make debug | make clean
  src/sim.h                   Shared types and state (read first)
  src/threads.c               Producers (voice/video/data), scheduler, and monitor
  src/  policy.c                Policies: FIFO, strict priority, EDF, DWRR, and priority floor
  src/channel.c               Fixed slot capacity or capacity from a CSV trace
  src/main.c                  CLI, SCHED_FIFO, CPU affinity, and log output
channel/channel_model.py      Path loss + shadowing + Rayleigh (Jakes) + MRC -> PRB trace
analysis/analyze.py           Per-class metrics for one execution
analysis/sweep.py             Policy × load × seed sweep, bootstrap CI, and plots
analysis/inversion.py         Priority-inversion experiment
tests/test_python.py          Numerical tests (pytest)
results/                      Outputs (CSV and PNG)
```

## How It Works

- At each 1-ms slot, the scheduler thread receives a PRB budget and divides it among three queues—voice, video, and data—according to the selected policy. A packet uses a fixed number of PRBs and may require multiple slots.
- Producers generate voice traffic every 20 ms, video traffic every 33 ms (periodic bursts using absolute `clock_nanosleep`), and data traffic with exponentially distributed inter-arrival times. `--load` scales the offered load: `1.0` is the baseline load, approximately 64% of the 50-PRB/slot capacity.
- `SCHED_FIFO` priorities (RM): scheduler 90 > voice 80 > video 70 > data 60 > monitor 10.
- A single mutex protects the queues, packets, and policy state.
- Logs remain in memory and are written only at the end, with no I/O inside the real-time threads.

## Results at a Glance

- Strict priority protects voice and video best: SLA capacity 2.20x on the fixed channel versus 1.50x for FIFO; data is sacrificed first.
- Four MRC antenna branches raise SLA capacity and reduce seed-to-seed variance (prio: 1.47x with L=1, 1.98x with L=4).
- Fixed-channel results are deterministic; variability under Rayleigh fading comes from the fading realization of each seed.
- Short runs (< 10 s, untrimmed) are biased; use 1.0 s warm-up and 0.5 s tail trimming.

Full results, hypothesis verdicts, what the simulator is and is not good for, and limitations: **[results/RESULTS_SUMMARY.md](results/RESULTS_SUMMARY.md)**. Protocol: [results/EXPERIMENTS.md](results/EXPERIMENTS.md).

![SLA capacity by policy and channel](results/exp/E1_capacity.png)

## Prerequisites

- **Linux/WSL2:** The C core uses Linux/Pthreads APIs and must be built and run inside WSL2 or a native Linux environment. To install WSL2, run `wsl --install -d Ubuntu` from an administrator PowerShell, restart Windows if prompted, and then open Ubuntu.
- **Build tools:** In Ubuntu/WSL, install GCC, `make`, and Python tooling:

  ```bash
  sudo apt update
  sudo apt install -y build-essential python3 python3-venv python3-pip
  ```

- **Python packages:** From the repository root in Ubuntu/WSL, create a Linux virtual environment and install the analysis and test dependencies:

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install numpy pandas matplotlib scipy pytest
  ```

  Required packages are `numpy`, `pandas`, `matplotlib`, `scipy`, and `pytest`. A Windows virtual environment cannot be used from WSL; create the environment inside Ubuntu/WSL.

- **Real-time permissions:** Windows WSL does not provide the same `SCHED_FIFO`/`RLIMIT_MEMLOCK` guarantees as a native Linux host. Native Linux is recommended for timing and priority-inversion measurements.

## Quick Start

**Run these commands from the repository root in Ubuntu/WSL or native Linux.**

```bash
# 1) Build
make -C core

# 2) Run once (10 s, fixed 50-PRB channel, pinned to CPU 2)
core/build/gnb_sim --policy prio --load 1.5 --duration 10 --seed 1 --cpu 2 --out results/run.csv

# 3) Calculate metrics
python3 -m analysis.analyze results/run.csv --duration 10

# 4) Use a Rayleigh channel with MRC on two antennas at 200 m
python3 -m channel.channel_model --distance 200 --antennas 2 --slots 10000 --out results/trace.csv
core/build/gnb_sim --policy dwrr --load 1.5 --trace results/trace.csv --out results/run.csv

# 5) Run the complete sweep
python3 -m analysis.sweep --loads 0.5 1 1.5 2 2.5 --seeds 5 --duration 5 --cpu 2

# Run tests
python3 -m pytest -q tests
```

## Native Linux Setup for Real-Time Measurements

Do this once per machine (Debian/Ubuntu shown; use `dnf` on Fedora):

```bash
sudo apt install -y build-essential python3-venv tmux linux-tools-generic   # cpupower
printf '%s\n' "$USER - rtprio 95" "$USER - memlock unlimited" | sudo tee /etc/security/limits.d/99-rt.conf
# log out and back in so the limits apply
```

Before every measurement session, in the same terminal (or `tmux` session) that runs the experiments:

```bash
ulimit -r                                   # must print 95 or higher
ulimit -l                                   # must print unlimited
sudo cpupower frequency-set -g performance
make -C core
core/build/gnb_sim --policy prio --load 1.5 --duration 3 --seed 1 --cpu 2 --out /tmp/run.csv | tail -1
```

The last line must end with `rt=1` and there must be no `memlock` warning. Without real-time permissions, the core warns and runs without `SCHED_FIFO` (`rt=0`); those runs are not valid real-time measurements. WSL may not provide the same guarantees.

While measurements run: keep the machine on AC power and prevent sleep, close browsers, IDEs, VMs, Docker, and sync or update tools, do not use the computer, and keep it cool. Do not mix results from different machines or binary hashes (`results/exp/manifest_*.json` records the hash).

## Logs

- `results/run.csv`: one packet per line with `id,class,arrival_ns,start_ns,end_ns,deadline_ns,prbs,dropped`. `-1` means that the packet was never served; `dropped=1` means that it was discarded because the queue was full.
- `results/run.csv.slots.csv`: one slot per line with `slot,ideal_ns,actual_ns,lock_wait_ns,budget,used`. Scheduling latency is `actual_ns - ideal_ns`; `lock_wait_ns` is the time the scheduler waits for the mutex.

## Extending the Project

- **New policy:** Implement `on_slot_start`, `pick`, and `on_served` in `core/src/policy.c`, then register it in that file's policy table.
- **New channel:** Generate a `slot,prbs` CSV and pass it with `--trace`.
- **Debugging:** Run `make -C core debug` for the ThreadSanitizer build and use `gdb core/build/gnb_sim`. Use `--no-rt` when the process lacks real-time scheduling permission.

## Policies, Semaphore, and Starvation

- The policies share the `on_slot_start/pick/on_served` interface:
  - `fifo`: oldest packet first
  - `prio`: voice > video > data
  - `edf`: smallest absolute deadline among queue heads
  - `dwrr`: proportional quanta
  - `prio_floor`: strict priority with configurable minimum video and data allocations
- The scheduler calls `sem_post` once per simulated second. The monitor waits with `sem_wait`, prints the queue state, and exits when `monitor_stop = 1` after the final `sem_post`.
- A slot is considered starved for a class if the class has backlog and receives zero PRBs.
- `<out>.starvation.csv` contains `class,backlog_slots,starved_slots,max_starve_ms`. `max_starve_ms` is the longest starvation run multiplied by the slot duration.
- `analysis/analyze.py` reports `starved_frac` and `max_starve_ms`; `analysis/sweep.py` aggregates `max_starve_ms`.
- For example, at load 2.0 on a fixed channel, `prio` leaves data without PRBs in roughly 89% of non-empty slots. `edf` distributes the losses, while voice can wait 47 ms—more than its 20-ms deadline.

## Priority-Inversion Experiment

Three threads run on one CPU with `SCHED_FIFO`: the scheduler (priority 90) needs the mutex; the accounting thread (priority 20) holds it for `--cs-us` (2 ms of CPU) every 100 ms; and the hog thread (priority 50) consumes `--hog-ms` (20 ms) immediately afterward.

Without priority inheritance, the hog preempts accounting and the scheduler waits approximately 20 ms, which can exceed the voice deadline. With `PTHREAD_PRIO_INHERIT`, accounting inherits priority 90 and releases the mutex in approximately 2 ms.

```bash
# Automated: baseline x no inheritance x inheritance
python3 -m analysis.inversion --seeds 5 --duration 10 --cpu 2

# Manual
core/build/gnb_sim --inversion --cpu 2 --policy prio                  # no inheritance
core/build/gnb_sim --inversion --cpu 2 --policy prio --prio-inherit   # with inheritance
core/build/gnb_sim --inversion --cpu 2 --hog-ms 0                     # baseline
```

`--inversion` requires `--cpu` and `SCHED_FIFO`. Otherwise, the hog can run on another core and no priority inversion occurs.

## Schedulability Test and EDF Results

`analysis/schedulability.py` calculates utilization, the Liu-Layland bound for voice plus video, fixed-priority response time, and EDF demand tests for each load. It predicts saturation at 1.56x and that `prio` protects voice and video until voice-plus-video utilization reaches 1 (approximately 2.26x load). This agrees with a 20-seed, fixed-channel, 4-second sweep: `prio` keeps voice QoS at 1.0 through 2.4x, while video collapses only at 2.4x.

```bash
python3 -m analysis.schedulability --loads 1.5 1.6 2.0 2.4
python3 -m analysis.sweep --loads 1.2 1.6 2.0 2.4 --seeds 20 --duration 4 --cpu 2 --tag edf
```

Outputs: `results/edf_{raw,agg}.csv`, `edf_qos.png`, `edf_starvation.png`, and `results/schedulability.csv`.

## Producer Latency, mlockall, and Channel Validation

- Each producer records `wakeup - ideal` for every `clock_nanosleep` call in `<out>.producers.csv`, which contains `class,ideal_ns,latency_ns`. `python -m analysis.producers` generates `results/producers_*.csv/png`.
- `mlockall(MCL_CURRENT|MCL_FUTURE)` is enabled by default. `--no-mlock` disables it. The core requires sufficient `RLIMIT_MEMLOCK` for thread stacks and logs.
- `python -m analysis.validate_channel` compares mean PRBs by distance with the Gamma/MRC theory.
- The results summary and suggested video outline are available in `results/RESULTS_SUMMARY.md`.

## Pre-registered Experiments

- Protocol and hypotheses H1–H6: `results/EXPERIMENTS.md`.
- Default run (10-20 seeds, approximately two hours on 3 cores): `python3 -m analysis.experiments run E1 E2 E3 E4 E5 --cpus 1 2 3`.
- Options: `--seeds N` overrides the seed count, `--e1-loads L1 L2 ...` sets the E1 load grid, `--e1-duration S` sets the E1 run length in seconds, `--tag NAME` writes `E*_NAME_raw.csv`, and `--dry` only counts executions. Interrupted runs resume when the same command is repeated. Run time is proportional to total simulated seconds divided by the number of CPUs.
- The Python driver is pinned to CPUs 0 and 4. Use only other CPUs for `--cpus`, which one job uses per CPU. Use one hardware thread per physical core.
- Reducing variability: Rayleigh scenarios have high seed-to-seed variance because each seed is a different fading realization, while the fixed channel is deterministic. Use more seeds, a finer E1 load grid, and report quantiles and per-seed paired differences instead of only means.

Generic example (finer E1 grid, 10-s runs, all CPUs except 0 and 4, sleep inhibited):

```bash
source .venv/bin/activate
CPUS=$(seq 1 $(($(nproc)-1)) | grep -vx 4 | tr '\n' ' ')
systemd-inhibit --what=sleep:idle:handle-lid-switch --who=sim --why="experiments" \
  python3 -m analysis.experiments run E1 --seeds 20 --e1-duration 10 \
  --e1-loads 1.0 1.2 1.4 1.5 1.55 1.6 1.65 1.7 1.75 1.8 1.85 1.9 1.95 2.0 2.05 2.1 2.2 2.4 \
  --cpus $CPUS --tag fine10
```

- Generate the report and plots: `python3 -m analysis.exp_report`. It reads the untagged `results/exp/E*_raw.csv`, so copy the tagged file first (for example `cp results/exp/E1_fine10_raw.csv results/exp/E1_raw.csv`).

## Assumed Simplifications

Synchronous bursts represent the worst case. The model does not include fragmentation, HARQ, or discrete MCS values. Shadowing is fixed per trace, and a representative user is modeled in the channel. Channel capacity is `PRBs = 50 × SE/4` unless a trace supplies a different capacity.
