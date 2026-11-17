
"""Testes numéricos do módulo de canal e das métricas."""
import numpy as np
import pandas as pd

from analysis.analyze import jain, summarize
from channel.channel_model import ChannelConfig, generate_prbs, path_loss_db, rayleigh_power_gain


def test_path_loss_slope_matches_exponent():
    cfg = ChannelConfig(path_loss_exp=3.5)
    # +10 n dB por década de distância
    assert np.isclose(path_loss_db(1000, cfg) - path_loss_db(100, cfg), 35.0)


def test_rayleigh_gain_mean_is_antenna_count():
    rng = np.random.default_rng(0)
    for L in (1, 2, 4):
        cfg = ChannelConfig(antennas=L, speed_mps=30.0)
        g = rayleigh_power_gain(200_000, cfg, rng)
        assert abs(g.mean() - L) < 0.1 * L  # E[sum |h|^2] = L


def test_rayleigh_outage_matches_theory():
    # P(|h|^2 < x) = 1 - exp(-x) para 1 antena
    rng = np.random.default_rng(1)
    g = rayleigh_power_gain(200_000, ChannelConfig(speed_mps=30.0), rng)
    assert abs((g < 0.1).mean() - (1 - np.exp(-0.1))) < 0.02


def test_capacity_decreases_with_distance():
    near = generate_prbs(2000, ChannelConfig(distance_m=50, fading=False), seed=3).mean()
    far = generate_prbs(2000, ChannelConfig(distance_m=400, fading=False), seed=3).mean()
    assert near > far


def test_diversity_reduces_deep_fades():
    cfg1 = ChannelConfig(distance_m=300, antennas=1, speed_mps=30.0)
    cfg4 = ChannelConfig(distance_m=300, antennas=4, speed_mps=30.0)
    p1 = generate_prbs(20_000, cfg1, seed=5)
    p4 = generate_prbs(20_000, cfg4, seed=5)
    assert p4.mean() > p1.mean()


def test_jain_bounds():
    assert np.isclose(jain([1, 1, 1]), 1.0)
    assert np.isclose(jain([1, 0, 0]), 1 / 3)


def test_summarize_counts_drops_and_deadlines():
    pk = pd.DataFrame(
        {
            "class": ["voice"] * 4,
            "arrival_ns": [0, 0, 0, 0],
            "start_ns": [0, 0, -1, -1],
            "end_ns": [10e6, 30e6, -1, -1],  # 1 no prazo, 1 atrasado, 2 perdidos
            "deadline_ns": [20e6] * 4,
            "prbs": [2] * 4,
            "dropped": [0, 0, 0, 1],
        }
    )
    v = summarize(pk, 1.0).set_index("class").loc["voice"]
    assert v["offered"] == 4 and v["delivered"] == 2
    assert v["dropped"] == 1 and v["unserved"] == 1
    assert np.isclose(v["qos"], 0.25)


def test_schedulability_saturation_and_prio_limit():
    from analysis.schedulability import analyze, build_tasks, utilization

    # U(1.0) = 0.2 + 0.2424 + 0.2 => saturação em ~1.56x
    assert np.isclose(1 / utilization(build_tasks(1.0)), 1.56, atol=0.01)
    df = analyze([1.5, 1.6, 2.4]).set_index("load")
    assert df.loc[1.5, "edf_all_ok"] and not df.loc[1.6, "edf_all_ok"]
    assert df.loc[2.0 if 2.0 in df.index else 1.6, "prio_voice_video_ok"]
    assert not df.loc[2.4, "prio_voice_video_ok"]  # voz+vídeo passam de U=1


def test_sla_capacity_interpolation_and_censoring():
    from analysis.exp_report import sla_capacity

    loads = np.array([1.0, 2.0, 3.0])
    # cruza 0,99 entre 2 (1,00) e 3 (0,90): 2 + 0,01/0,10 = 2,1
    cap, st = sla_capacity(loads, np.array([1.0, 1.0, 0.90]))
    assert st == "ok" and np.isclose(cap, 2.1)
    assert sla_capacity(loads, np.array([1.0, 1.0, 1.0])) == (3.0, "right")
    assert sla_capacity(loads, np.array([0.5, 0.4, 0.3])) == (1.0, "left")


def test_equal_mean_distance_and_paired_ci():
    from analysis.exp_report import paired_ci
    from analysis.experiments import equal_mean_distance
    from analysis.validate_channel import theory_prbs

    d = [equal_mean_distance(L) for L in (1, 2, 4)]
    assert d[0] < d[1] < d[2]  # mais ramos MRC => mesma média a distância maior
    assert np.isclose(theory_prbs(d[1], 2), 50.0, atol=0.01)
    a = pd.Series([1.0, 1.1, 0.9, 1.2], index=[1, 2, 3, 4])
    m, lo, hi = paired_ci(a + 0.5, a)  # diferença constante => IC colapsa em 0,5
    assert np.isclose([m, lo, hi], 0.5).all()
