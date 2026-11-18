# Experimental Protocol (Pre-registration)

This protocol was written before observing the experimental data. Hypotheses, metrics, and decision rules were not changed after running the experiments.

## Common Scenario

The C/Pthreads core uses 1-ms slots and a baseline capacity of 50 PRB/slot. Voice, video, and data classes and deadlines match README.md. Paired seeds generate identical data arrivals and channel traces across policies.

Uncertainty is reported with 95% bootstrap confidence intervals using 2,000 resamples across seeds. Core executions last 6 seconds unless otherwise noted. The measurement window is 1.0–5.5 seconds: 1-second warm-up and 0.5-second tail.

## Metrics

- QoS = packets delivered on time / packets offered.
- max_starve_ms = longest consecutive interval with backlog and no PRBs.
- SLA = voice QoS >= 0.99 and video QoS >= 0.99.
- SLA capacity is the greatest relative load still satisfying the SLA.

## Hypotheses

- **H1 — Diversity:** Holding mean PRBs fixed at 50, SLA capacity increases as MRC branches increase from 1 to 4.
- **H2 — Policy versus diversity:** Compare the policy gain from strict priority over FIFO with the diversity gain from four versus one antenna branch.
- **H3 — Minimum floor:** A 1–2 PRB/slot floor should prevent data starvation without reducing voice or video QoS by more than 0.01.
- **H4 — Staggered bursts:** Policy ordering for voice QoS must remain unchanged as bursts are divided into more sub-bursts.
- **H5 — Fading versus deadline:** Voice QoS improves with mobile speed under Rayleigh fading when channel coherence is shorter than the voice deadline.
- **H6 — Truncation bias:** Short executions without warm-up/tail trimming should not materially differ from 20-second trimmed reference executions.

## Final Verdicts

| Hypothesis | Verdict | Result |
|---|---|---|
| H1 | Supported | Equal mean PRB, L=4 increased SLA capacity for every policy. |
| H2 | Inconclusive | Strict priority was more influential than diversity descriptively. |
| H3 | Refuted | The floor eliminated fixed-channel starvation, but Rayleigh fading retained small starvation and harmed video QoS. |
| H4 | Supported | Staggering did not change voice-policy ordering. |
| H5 | Supported | Faster fading improved voice QoS by 0.029 from 0.3 to 30 m/s. |
| H6 | Supported | Short executions biased QoS in several overload scenarios. |

Data: `results/exp/E*_raw.csv`; manifest: `results/exp/manifest_*.json`; verdict: `results/exp/verdict.csv`; plots: `results/exp/E*.png`.
