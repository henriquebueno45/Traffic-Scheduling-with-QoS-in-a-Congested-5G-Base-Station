# Experimental Results Summary

Reproduction instructions are in README.md. Tests ran on Linux (Fedora), 8 cores, SCHED_FIFO, the performance governor, and CPU affinity on core 2. Slot duration was 1 ms and fixed-channel capacity was 50 PRB/slot.

## Traffic Model

- Voice: 100 packets, 2 PRB each, every 20 ms, 20-ms deadline.
- Video: 40 packets, 10 PRB each, every 33 ms, 50-ms deadline.
- Data: Poisson arrivals, 20 PRB per packet, 500-ms deadline.
- QoS = packets delivered on time / packets offered. Drops and unserved packets count against QoS.

## Key Results

### Saturation

Baseline utilization reaches saturation near a 1.56x load multiplier.

### Fixed Channel

- **prio:** Protected voice through 2.4x; video collapsed at 2.4x; data was sacrificed first.
- **fifo:** Voice QoS degraded as early as 1.6x.
- **edf:** Voice QoS showed a domino effect under overload.
- **dwrr:** Data starvation was eliminated, but voice QoS collapsed at 2.4x.

### Channel Diversity

One Rayleigh antenna branch degraded voice earlier than the fixed channel. Four MRC branches kept most QoS values near 1.0 through 2.4x load. Equal mean PRB was used for the L=1, L=2, and L=4 comparisons.

### Priority Inversion

The priority-inheritance scenario reduced scheduler mutex wait and voice deadline misses compared with the no-inheritance scenario.

### Producer Wake Latency

The available producer-latency data covers only the run without `mlockall`, so it cannot establish a comparison between the two memory-locking modes. In that run, wake latency remained far below the 20-ms voice deadline.

### Pre-registered Experiments

- Diversity increased SLA capacity for all policies with equal mean PRB.
- The minimum floor protected data but could reduce video QoS under Rayleigh fading.
- Staggered bursts did not change policy ordering.
- Faster fading improved voice QoS.
- Short executions without warm-up/tail trimming biased QoS results.

## Suggested Video Demonstration

1. Show voice, video, and data producers feeding queues and the scheduler.
2. Run prio at 1.0x load, then increase to 2.0x and show data starvation.
3. Compare FIFO, strict priority, EDF, and DWRR.
4. Demonstrate priority inversion with and without priority inheritance.
5. Compare Rayleigh 1-antenna and 4-antenna MRC channels.

## Limitations

- Synchronous bursts are the worst case.
- No fragmentation, HARQ, or discrete MCS.
- Shadowing is static per execution.
- Channel sweeps use one representative user.
- The fluid analytical model assumes average data rates.
