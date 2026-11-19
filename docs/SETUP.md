# Setup

The C core uses Linux/Pthreads APIs. Use native Linux for timing measurements; WSL2 works for development and functional tests only.

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

## Real-Time Setup (Native Linux)

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

## Verify the Installation

Run these commands from the repository root.

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
