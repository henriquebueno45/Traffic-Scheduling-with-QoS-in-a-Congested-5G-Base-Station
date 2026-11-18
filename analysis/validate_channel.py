"""Channel validation: mean PRBs versus distance (simulation versus theory) for 1/2/4 antennas.

Theory: for MRC with L Rayleigh branches, g ~ Gamma(L, 1), the sum of L unit-exponential variables.
    E[PRBs] = N_NOMINAL/SE_REF * E[min(log2(1 + mean_snr * g), SE_MAX)]
where mean_snr = Ptx_prb - PL(d) - noise (shadowing = 0). The integral is numerical.
The fixed channel (no fading) is also shown as a reference.

Usage: python -m analysis.validate_channel
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from analysis.sweep import ROOT
from channel.channel_model import ChannelConfig, generate_prbs, noise_dbm, path_loss_db


def theory_prbs(d: float, antennas: int) -> float:
    cfg = ChannelConfig(distance_m=d)
    snr_db = cfg.ptx_prb_dbm - path_loss_db(d, cfg) - noise_dbm(cfg)
    snr = 10 ** (snr_db / 10)
    g = np.linspace(1e-4, 40 + 10 * antennas, 200000)
    pdf = stats.gamma.pdf(g, a=antennas)
    se = np.minimum(np.log2(1 + snr * g), cfg.se_max)
    return float(np.trapezoid(se * pdf, g) * cfg.n_nominal_prbs / cfg.se_ref)


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dists = np.arange(40, 321, 20)
    fig, ax = plt.subplots(figsize=(6, 4))
    rows = ["antennas,distance_m,sim_prbs,theory_prbs"]
    for L in (1, 2, 4):
        sim = []
        for d in dists:
            cfg = ChannelConfig(distance_m=float(d), antennas=L, shadow_sigma_db=0.0)
            sim.append(generate_prbs(60000, cfg, seed=1).mean())
        th = [theory_prbs(float(d), L) for d in dists]
        ax.plot(dists, sim, "o", ms=4, label=f"simulated L={L}")
        ax.plot(dists, th, "-", label=f"theory L={L}")
        rows += [f"{L},{d},{s:.3f},{t:.3f}" for d, s, t in zip(dists, sim, th)]
        err = np.max(np.abs(np.array(sim) - np.array(th)))
        print(f"L={L}: maximum |simulation-theory| error = {err:.2f} PRB")
    fixed = [min(np.log2(1 + 10 ** ((23 - path_loss_db(float(d), ChannelConfig()) - noise_dbm(
        ChannelConfig())) / 10)), 7.4) * 50 / 4 for d in dists]
    ax.plot(dists, fixed, "k--", label="no fading (AWGN)")
    ax.axhline(50, color="gray", lw=0.8)
    ax.set_xlabel("distance (m)")
    ax.set_ylabel("mean PRBs per slot")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(ROOT / "results" / "channel_validation.png", dpi=150)
    (ROOT / "results" / "channel_validation.csv").write_text("\n".join(rows) + "\n")
    print("saved to results/channel_validation.png and .csv")


if __name__ == "__main__":
    main()
