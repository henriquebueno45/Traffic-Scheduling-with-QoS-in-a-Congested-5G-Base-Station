#!/usr/bin/env bash
# One-command reproduction of the committed results.
#
#   scripts/reproduce.sh smoke   build, run the tests, and run one short simulation (about 1 min)
#   scripts/reproduce.sh full    regenerate every result in results/ (about 10 h on 6 CPUs)
#
# `full` overwrites results/exp/*. It needs native Linux with at least 6 CPUs (the Python driver is
# pinned to CPUs 0 and 4), and is only valid with real-time scheduling: run `ulimit -r 95` first
# and set the CPU governor to performance (see docs/SETUP.md). The run is resumable: repeat the
# command after an interruption.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-smoke}"
PY="${PYTHON:-python3}"
[ -x venv/bin/python ] && PY=venv/bin/python
[ -x .venv/bin/python ] && PY=.venv/bin/python

build_and_test() {
  make -C core
  "$PY" -m pytest -q tests
}

case "$mode" in
  smoke)
    build_and_test
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    core/build/gnb_sim --policy prio --load 1.5 --duration 3 --seed 1 --out "$tmp/run.csv" --quiet
    "$PY" -m analysis.analyze "$tmp/run.csv" --duration 3
    echo "smoke test OK"
    ;;
  full)
    ncpu="$(nproc)"
    [ "$ncpu" -ge 6 ] || { echo "full needs at least 6 CPUs (found $ncpu)"; exit 1; }
    mapfile -t cpus < <(seq 1 $((ncpu - 1)) | grep -vx 4)
    build_and_test
    run() { "$PY" -m analysis.experiments run "$@" --cpus "${cpus[@]}"; }

    run E1 --seeds 20 --e1-duration 10 --tag fine10 --e1-loads \
      0.6 0.7 0.8 0.9 0.95 1.0 1.1 1.2 1.3 1.4 1.5 1.55 1.6 1.65 1.7 1.75 1.8 1.85 1.9 1.95 \
      2.0 2.05 2.1 2.2 2.4
    run E2 E3 E4 E5 --seeds 40 --tag s40
    run E6 --seeds 30 --tag w30

    cp results/exp/E1_fine10_raw.csv results/exp/E1_raw.csv
    for e in E2 E3 E4 E5; do cp "results/exp/${e}_s40_raw.csv" "results/exp/${e}_raw.csv"; done
    cp results/exp/E6_w30_raw.csv results/exp/E6_raw.csv
    rm -f results/exp/E1_fine10_raw.csv results/exp/E[2-5]_s40_raw.csv results/exp/E6_w30_raw.csv

    "$PY" -m analysis.exp_report
    "$PY" -m analysis.validate_channel
    echo "full reproduction done; compare results/exp/verdict.csv with the committed version"
    ;;
  *)
    echo "usage: $0 [smoke|full]"; exit 2 ;;
esac
