# Running the Pre-registered Experiments

- Protocol and hypotheses H1–H6: [../results/EXPERIMENTS.md](../results/EXPERIMENTS.md).
- Default run (10-20 seeds, about 2 hours on 3 cores; the 40-seed set took about 3.6 hours on 6 cores): `python3 -m analysis.experiments run E1 E2 E3 E4 E5 --cpus 1 2 3`.
- Options: `--seeds N` overrides the seed count, `--e1-loads L1 L2 ...` sets the E1 load grid, `--e1-duration S` sets the E1 run length in seconds, `--tag NAME` writes `E*_NAME_raw.csv`, and `--dry` only counts executions. Interrupted runs resume when the same command is repeated. Run time is proportional to total simulated seconds divided by the number of CPUs.
- The Python driver is pinned to CPUs 0 and 4. Use only other CPUs for `--cpus`, which one job uses per CPU. Use one hardware thread per physical core.
- Reducing variability: Rayleigh scenarios have high seed-to-seed variance because each seed is a different fading realization, while the fixed channel is deterministic. Use more seeds, a finer E1 load grid, and report quantiles and per-seed paired differences instead of only means.

Generic example (finer E1 grid, 10-s runs, all CPUs except 0 and 4, sleep inhibited):

```bash
source .venv/bin/activate   # or: source venv/bin/activate
systemd-inhibit --what=sleep:idle:handle-lid-switch --who=sim --why="experiments" \
  python3 -m analysis.experiments run E1 --seeds 20 --e1-duration 10 \
  --e1-loads 1.0 1.2 1.4 1.5 1.55 1.6 1.65 1.7 1.75 1.8 1.85 1.9 1.95 2.0 2.05 2.1 2.2 2.4 \
  --cpus $(seq 1 $(($(nproc)-1)) | grep -vx 4) --tag fine10
```

## Generating the Report

`python3 -m analysis.exp_report` reads the untagged `results/exp/E*_raw.csv` and writes `*_table.csv`, the `E*_*.png` plots, and `verdict.csv`. Copy a tagged file first, for example `cp results/exp/E1_fine10_raw.csv results/exp/E1_raw.csv`.

The committed `E1_raw.csv` is the `fine10` run (20 seeds, 10 s, 0.05 load grid); `E2-E5_raw.csv` are the 40-seed `s40` set. The `manifest_*.json` files record the machine, library versions, and binary hash. Compare results only when the machine and binary hash match.


## Command Reference

| Option | Meaning |
|---|---|
| `--cpus` | CPUs for parallel jobs (one job per CPU) |
| `--seeds N` | Override the seed count |
| `--e1-loads` | E1 load grid |
| `--e1-duration S` | E1 run length in seconds |
| `--tag NAME` | Write `E*_NAME_raw.csv` |
| `--dry` | Count executions only |

Run time is roughly (executions x run length) / number of CPUs. Reference: the 40-seed set was about 77,000 run-seconds.
