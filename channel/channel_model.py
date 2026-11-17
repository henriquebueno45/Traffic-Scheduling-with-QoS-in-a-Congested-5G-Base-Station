"""Modelo de canal -> traço de PRBs por slot (CSV "slot,prbs").

Cadeia de cálculo (tudo em dB, exceto onde indicado):
    PL(d)   = PL(d0) + 10 n log10(d/d0)            [log-distância]
    X       ~ N(0, sigma^2)                         [shadowing log-normal, 1 sorteio por traço]
    g(t)    = soma de L fadings Rayleigh |h_l(t)|^2 [Jakes; L = nº de antenas, MRC]
    SNR(t)  = Ptx_prb - PL - X - ruído + 10 log10 g(t)
    SE(t)   = min(log2(1 + SNR_lin), SE_MAX)        [Shannon, bit/s/Hz]
    PRBs(t) = round(N_NOMINAL * SE(t) / SE_REF)     [conversão para o orçamento do slot]

N_NOMINAL PRBs por slot correspondem a SE_REF bit/s/Hz (referência do canal fixo).
Refs.: Goldsmith, "Wireless Communications" (path loss, shadowing, Jakes);
Tse & Viswanath, cap. 3 (Rayleigh, MRC).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np

C = 3e8


@dataclass(frozen=True)
class ChannelConfig:
    distance_m: float = 100.0
    fc_hz: float = 3.5e9
    path_loss_exp: float = 3.5
    shadow_sigma_db: float = 6.0
    ptx_prb_dbm: float = 23.0  # potência por PRB
    prb_bw_hz: float = 360e3  # 12 subportadoras x 30 kHz
    noise_figure_db: float = 7.0
    speed_mps: float = 1.5  # ~ pedestre
    antennas: int = 1  # MRC
    fading: bool = True
    slot_s: float = 1e-3
    n_nominal_prbs: int = 50
    se_ref: float = 4.0  # bit/s/Hz <-> n_nominal_prbs
    se_max: float = 7.4  # limite do MCS (256QAM)


def path_loss_db(d_m: float, cfg: ChannelConfig, d0_m: float = 1.0) -> float:
    """Log-distância com PL(d0) de espaço livre."""
    pl0 = 20 * np.log10(4 * np.pi * d0_m * cfg.fc_hz / C)
    return float(pl0 + 10 * cfg.path_loss_exp * np.log10(d_m / d0_m))


def noise_dbm(cfg: ChannelConfig) -> float:
    return -174.0 + 10 * np.log10(cfg.prb_bw_hz) + cfg.noise_figure_db


def rayleigh_power_gain(
    n_slots: int, cfg: ChannelConfig, rng: np.random.Generator, n_paths: int = 32
) -> np.ndarray:
    """|h|^2 com correlação temporal (Jakes/Clarke, soma de senoides).

    Média 1 por antena; com MRC de L antenas independentes soma L ganhos
    (média L). Doppler máximo fd = v fc / c.
    """
    fd = cfg.speed_mps * cfg.fc_hz / C
    t = np.arange(n_slots) * cfg.slot_s
    gain = np.zeros(n_slots)
    for _ in range(cfg.antennas):
        alpha = rng.uniform(0, 2 * np.pi, n_paths)
        phi = rng.uniform(0, 2 * np.pi, n_paths)
        arg = 2 * np.pi * fd * np.outer(t, np.cos(alpha)) + phi
        h = np.exp(1j * arg).sum(axis=1) / np.sqrt(n_paths)
        gain += np.abs(h) ** 2
    return gain


def generate_prbs(n_slots: int, cfg: ChannelConfig, seed: int = 1) -> np.ndarray:
    """Devolve o nº de PRBs disponíveis em cada slot (inteiros >= 0)."""
    rng = np.random.default_rng(seed)
    shadow = rng.normal(0.0, cfg.shadow_sigma_db)
    snr_db = (
        cfg.ptx_prb_dbm - path_loss_db(cfg.distance_m, cfg) - shadow - noise_dbm(cfg)
    )
    snr_db = np.full(n_slots, snr_db)
    if cfg.fading:
        snr_db = snr_db + 10 * np.log10(rayleigh_power_gain(n_slots, cfg, rng))
    se = np.minimum(np.log2(1 + 10 ** (snr_db / 10)), cfg.se_max)
    return np.rint(cfg.n_nominal_prbs * se / cfg.se_ref).astype(int)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--distance", type=float, default=100.0, help="metros")
    ap.add_argument("--antennas", type=int, default=1, help="MRC: 1, 2 ou 4")
    ap.add_argument("--no-fading", action="store_true", help="só path loss + shadowing")
    ap.add_argument("--speed", type=float, default=1.5, help="m/s")
    ap.add_argument("--slots", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="results/trace.csv")
    a = ap.parse_args()

    cfg = ChannelConfig(
        distance_m=a.distance, antennas=a.antennas, fading=not a.no_fading,
        speed_mps=a.speed,
    )
    prbs = generate_prbs(a.slots, cfg, a.seed)
    import os

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write("slot,prbs\n")
        f.writelines(f"{i},{p}\n" for i, p in enumerate(prbs))
    print(f"{a.out}: {a.slots} slots, PRBs média={prbs.mean():.1f} "
          f"min={prbs.min()} max={prbs.max()}")


if __name__ == "__main__":
    main()
