# Final Project Plan: QoS Traffic Scheduling in a Congested 5G Base Station

This project is submitted as part of two courses:
- **Concurrency and Real-Time Systems (Professor Montez):** C/Pthreads application for a Linux system.
- **Wireless Communications (Professor Richard Demo Souza):** channel analysis and scientific report.

Author: Henrique Bueno de Morais (individual project).

## 1. Objective

A 5G gNodeB divides radio resources among voice, video, and data traffic. Voice requires low delay, video requires a reasonable rate, and data tolerates waiting. Under congestion, the scheduling policy determines which traffic classes are favored or harmed.

The project implements a multithreaded gNodeB scheduler, compares FIFO, strict-priority, WRR/DWRR, and EDF policies, and models slot capacity as a function of the wireless channel, including path loss, shadowing, fading, and antenna diversity.

Central question: How does each policy distribute performance across traffic classes under congestion, and how does channel quality change the result?

## 2. Architecture

**Real-time core (C/Pthreads):**
- One periodic thread per traffic class.
- Scheduler and monitor threads.
- Radio resource: PRBs per slot.
- Shared state protected by a mutex and/or semaphores.
- Linux SCHED_FIFO priorities and CPU affinity.
- Priority-inversion, starvation, deadline, and scheduling-latency experiments.

**Wireless channel layer (Python):**
- Log-distance path loss and log-normal shadowing.
- Rayleigh fading with temporal correlation; Nakagami as an optional extension.
- Shannon spectral efficiency converted to PRBs per slot.
- Maximum-ratio combining with 1, 2, and 4 antennas.
- NumPy, pandas, and Matplotlib analysis of core logs.

## 3. Project Phases

### Phase 0: Preparation
- Confirm course requirements and deadlines.
- Inform both instructors about shared work and report reuse.
- Configure Linux or WSL2, GCC, make, Pthreads, Python, NumPy, pandas, Matplotlib, SciPy, pytest, and Git.
- On Windows, WSL2 with Ubuntu must be enabled first by an administrator. Run `wsl --install -d Ubuntu`, then install build tools with `sudo apt update && sudo apt install -y build-essential python3 python3-venv python3-pip`.
- Create a Python virtual environment and install `numpy pandas matplotlib scipy pytest` with pip.
- Test SCHED_FIFO and CPU affinity.

### Phase 1: Concurrent Skeleton
- Implement packet structures, per-class circular queues, and PRB resources.
- Implement absolute-time periodic producers with clock_nanosleep.
- Implement the scheduler and monitor threads.
- Add mutex, condition-variable, or semaphore synchronization.
- Implement structured CSV packet logging.

### Phase 2: Real-Time Experiments
- Add FIFO, strict priority, EDF, DWRR, and minimum-floor policies.
- Measure priority inversion with and without PTHREAD_PRIO_INHERIT.
- Measure scheduling latency, deadline misses, and starvation.
- Increase load until saturation.

### Phase 3: Channel Model
- Implement log-distance path loss and log-normal shadowing.
- Implement correlated Rayleigh fading.
- Convert Shannon capacity to PRBs per slot.
- Implement MRC diversity for 1, 2, and 4 antennas.
- Generate and validate channel traces.
- Integrate traces with the C core.

### Phase 4: Experiments and Analysis
- Evaluate fixed channels and Rayleigh channels with diversity.
- Repeat each configuration and report confidence intervals.
- Compare delay, jitter, loss, throughput, starvation, deadline delivery, and Jain fairness.
- Generate comparative plots near the saturation point.

### Phase 5: Final Reports
- Complete the real-time systems report.
- Complete the scientific article: abstract, introduction, related work, model, methodology, results, conclusion, and references.

## 4. Metrics and Methodology

- Prefer on-time delivery and deadline-miss rates over mean latency, which can have survivor bias.
- QoS satisfaction is packets delivered on time divided by packets offered.
- Dropped and unserved packets remain in the denominator.
- Report P95/P99 delay, jitter, starvation, throughput, Jain fairness, and confidence intervals.
- Use paired seeds when comparing policies or channel scenarios.

## 5. Risks and Mitigation

- **Reproducibility:** Repeat executions and report confidence intervals.
- **Report overlap:** One report emphasizes concurrency; the other emphasizes channel and policy comparison.
- **Dependencies:** The channel model can be developed alongside the real-time core.
- **Scope:** Drop MRC diversity or the minimum floor if time is limited.

## 6. Assumptions

- Synchronous bursts are treated as the worst case.
- No video fragmentation, HARQ, or discrete MCS modeling.
- Shadowing is static per execution.
- Each channel scenario uses one representative user.
