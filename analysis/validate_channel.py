"""Channel validation: mean PRBs versus distance (simulation versus theory) for 1/2/4 antennas.

Theory: for MRC with L Rayleigh branches, g ~ Gamma(L, 1), the sum of L unit-exponential variables.
    E[PRBs] = N_NOMINAL/SE_REF * E[min(log2(1 + mean_snr * g), SE_MAX)]
where mean_snr = Ptx_prb - PL(d) - noise (shadowing = 0). The integral is numerical.
The fixed channel (no fading) is also shown as a reference.

Outage validation (validate_outage): the empirical CDF of the MRC power gain g (sum of L unit-mean
branch gains) against the Gamma(L, 1) CDF, the fitted diversity order (slope of log P_out versus
log threshold; theory: L), and the Rayleigh level-crossing rate N(rho) = sqrt(2 pi) fd rho
exp(-rho^2) for L=1, where rho = sqrt(threshold).

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


def validate_outage(n_traces: int = 40, n_slots: int = 50000, speed: float = 15.0) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from channel.channel_model import C, rayleigh_power_gain

    th_db = np.arange(-30, 1.0, 2.0)
    th = 10 ** (th_db / 10)
    rows = ["antennas,threshold_db,sim_outage,theory_outage"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 3.8))
    for L in (1, 2, 4):
        cfg = ChannelConfig(antennas=L, speed_mps=speed)
        g = np.concatenate([rayleigh_power_gain(n_slots, cfg, np.random.default_rng(100 + k))
                            for k in range(n_traces)])
        sim = np.array([(g < t * L).mean() for t in th])
        thy = stats.gamma.cdf(th * L, a=L)
        # Threshold is relative to the mean combined gain L, so curves of different L are comparable
        ax.semilogy(th_db, sim, "o", ms=4, label=f"simulated L={L}")
        ax.semilogy(th_db, thy, "-", label=f"theory L={L}")
        rows += [f"{L},{x},{a:.6g},{b:.6g}" for x, a, b in zip(th_db, sim, thy)]
        # Local slope of log P_out versus log threshold over the same range for simulation and
        # theory (the asymptotic slope L needs probabilities too small to be sampled)
        t_branch = np.logspace(-1.5, -0.3, 10) * L
        emp = np.array([(g < t).mean() for t in t_branch])
        thy_b = stats.gamma.cdf(t_branch, a=L)
        ok = emp > 0
        o_sim = np.polyfit(np.log10(t_branch[ok]), np.log10(emp[ok]), 1)[0]
        o_thy = np.polyfit(np.log10(t_branch), np.log10(thy_b), 1)[0]
        n_ok = (thy > 1e-3) & (sim > 0)
        print(f"L={L}: log-log slope simulated {o_sim:.2f}, theory {o_thy:.2f} over the same range "
              f"(asymptotic diversity order {L}); max |log10 sim/theory| over P>1e-3 = "
              f"{np.max(np.abs(np.log10(sim[n_ok] / thy[n_ok]))):.2f}")
    ax.set_xlabel("outage threshold relative to mean SNR (dB)")
    ax.set_ylabel("outage probability P(SNR < threshold)")
    ax.set_ylim(1e-4, 1)
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7)

    # Fine time resolution: at the 1-ms slot rate, deep fades shorter than a slot would be missed
    speed_lcr, lcr_slots = 5.0, 200000
    cfg = ChannelConfig(antennas=1, speed_mps=speed_lcr, slot_s=5e-5)
    fd = speed_lcr * cfg.fc_hz / C
    rho = np.array([0.1, 0.2, 0.3, 0.5, 0.7, 1.0])
    g = np.array([rayleigh_power_gain(lcr_slots, cfg, np.random.default_rng(500 + k))
                  for k in range(20)])
    dur = lcr_slots * cfg.slot_s
    sim_lcr = np.array([np.mean([((x[:-1] >= r**2) & (x[1:] < r**2)).sum() / dur for x in g])
                        for r in rho])
    thy_lcr = np.sqrt(2 * np.pi) * fd * rho * np.exp(-rho**2)
    ax2.plot(rho, thy_lcr, "-", label="theory")
    ax2.plot(rho, sim_lcr, "o", ms=4, label="simulated")
    ax2.set_xlabel("normalized level rho (amplitude / rms)")
    ax2.set_ylabel("level-crossing rate (crossings/s)")
    ax2.set_title(f"Rayleigh L=1, fd = {fd:.0f} Hz", fontsize=9)
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7)
    rows += ["", "rho,sim_lcr,theory_lcr"] + [f"{r},{a:.4f},{b:.4f}"
                                              for r, a, b in zip(rho, sim_lcr, thy_lcr)]
    print("LCR sim/theory:", np.round(sim_lcr / thy_lcr, 2))
    fig.tight_layout()
    fig.savefig(ROOT / "results" / "outage_validation.png", dpi=150)
    (ROOT / "results" / "outage_validation.csv").write_text("\n".join(rows) + "\n")
    print("saved to results/outage_validation.png and .csv")


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
    validate_outage()


if __name__ == "__main__":
    main()
