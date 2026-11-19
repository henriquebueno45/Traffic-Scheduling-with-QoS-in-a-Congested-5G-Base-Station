# Design and Implementation Notes

Internals of the C core, the scheduling policies, and the supporting experiments. For setup see [SETUP.md](SETUP.md); for the pre-registered experiments see [RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md).

## How It Works

- At each 1-ms slot, the scheduler thread receives a PRB budget and divides it among three queues—voice, video, and data—according to the selected policy. A packet uses a fixed number of PRBs and may require multiple slots.
- Producers generate voice traffic every 20 ms, video traffic every 33 ms (periodic bursts using absolute `clock_nanosleep`), and data traffic with exponentially distributed inter-arrival times. `--load` scales the offered load: `1.0` is the baseline load, approximately 64% of the 50-PRB/slot capacity.
- `SCHED_FIFO` priorities (RM): scheduler 90 > voice 80 > video 70 > data 60 > monitor 10.
- A single mutex protects the queues, packets, and policy state.
- Logs remain in memory and are written only at the end, with no I/O inside the real-time threads.

## Logs

- `results/run.csv`: one packet per line with `id,class,arrival_ns,start_ns,end_ns,deadline_ns,prbs,dropped`. `-1` means that the packet was never served; `dropped=1` means that it was discarded because the queue was full.
- `results/run.csv.slots.csv`: one slot per line with `slot,ideal_ns,actual_ns,lock_wait_ns,budget,used`. Scheduling latency is `actual_ns - ideal_ns`; `lock_wait_ns` is the time the scheduler waits for the mutex.

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
- Results are summarized in [../results/RESULTS_SUMMARY.md](../results/RESULTS_SUMMARY.md).

## Extending the Project

- **New policy:** Implement `on_slot_start`, `pick`, and `on_served` in `core/src/policy.c`, then register it in that file's policy table.
- **New channel:** Generate a `slot,prbs` CSV and pass it with `--trace`.
- **Debugging:** Run `make -C core debug` for the ThreadSanitizer build and use `gdb core/build/gnb_sim`. Use `--no-rt` when the process lacks real-time scheduling permission.

## Assumed Simplifications

Synchronous bursts represent the worst case. The model does not include fragmentation, HARQ, or discrete MCS values. Shadowing is fixed per trace, and a representative user is modeled in the channel. Channel capacity is `PRBs = 50 × SE/4` unless a trace supplies a different capacity.
