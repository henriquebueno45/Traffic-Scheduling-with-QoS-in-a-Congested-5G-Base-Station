"""Estatística, veredito das hipóteses (H1..H6) e figuras dos experimentos E1..E5.

Lê results/exp/E*_raw.csv (gerado por analysis.experiments) e escreve em results/exp/:
  *_tabela.csv, E*_*.png, veredito.csv  (uma linha por hipótese com a regra pré-registrada).

Todas as comparações são PAREADAS por semente; IC 95 % = bootstrap (2000) da média das diferenças.
Regras de decisão: results/EXPERIMENTOS.md.

Uso: python -m analysis.exp_report [E1 E2 ...]
"""
from __future__ import annotations

import os
import sys

import matplotlib
import numpy as np
import pandas as pd

from analysis.sweep import ROOT

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = ROOT / "results" / "exp"
SLA = 0.99
POLS = ["fifo", "prio", "edf", "dwrr", "prio_floor"]
SCENS = ["fixed", "L1", "L2", "L4"]
RNG = np.random.default_rng(0)


# ---------------------------------------------------------------- estatística
def boot_ci(x, n_boot: int = 2000) -> tuple[float, float, float]:
    """(média, lo, hi) com IC 95 % percentil por bootstrap da média."""
    v = np.asarray(x, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return (np.nan,) * 3
    m = RNG.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    return float(v.mean()), *map(float, np.percentile(m, [2.5, 97.5]))


def paired_ci(a: pd.Series, b: pd.Series) -> tuple[float, float, float]:
    """IC da média de (a - b) pareando pelo índice (semente)."""
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    return boot_ci((j.iloc[:, 0] - j.iloc[:, 1]).to_numpy())


def sla_capacity(loads: np.ndarray, m: np.ndarray, thr: float = SLA) -> tuple[float, str]:
    """Carga onde min(QoS voz, QoS vídeo) cruza `thr` (interpolação linear).

    Devolve (capacidade, status); status = 'ok' | 'left' (já viola na menor carga) |
    'right' (nunca viola: valor censurado na maior carga).
    """
    if m[0] < thr:
        return float(loads[0]), "left"
    for i in range(1, len(loads)):
        if m[i] < thr:
            x = loads[i - 1] + (m[i - 1] - thr) / (m[i - 1] - m[i]) * (loads[i] - loads[i - 1])
            return float(x), "ok"
    return float(loads[-1]), "right"


def load_raw(exp: str, trim: str = "trim") -> pd.DataFrame:
    df = pd.read_csv(OUT / f"{exp}_raw.csv")
    return df[df["trim"] == trim]


def verdict(rows: list, h: str, rule: str, supported: bool | None, detail: str) -> None:
    rows.append({"hipotese": h, "regra": rule,
                 "veredito": {True: "SUPORTADA", False: "REFUTADA", None: "INCONCLUSIVA"}[supported],
                 "detalhe": detail})


# ---------------------------------------------------------------- E1 (H1, H2)
def report_e1(ver: list) -> None:
    d = load_raw("E1")
    q = d.pivot_table(index=["scen", "policy", "seed", "load"], columns="class", values="qos")
    q["m"] = q[["voice", "video"]].min(axis=1)
    rows = []
    for (sc, pol, seed), g in q.groupby(level=[0, 1, 2]):
        g = g.reset_index().sort_values("load")
        cap, st = sla_capacity(g["load"].to_numpy(), g["m"].to_numpy())
        rows.append({"scen": sc, "policy": pol, "seed": seed, "cap": cap, "status": st})
    cap = pd.DataFrame(rows)
    cap.to_csv(OUT / "E1_capacidade_por_semente.csv", index=False)

    summ = []
    for (sc, pol), g in cap.groupby(["scen", "policy"]):
        m, lo, hi = boot_ci(g["cap"])
        summ.append({"scen": sc, "policy": pol, "C_SLA": m, "lo": lo, "hi": hi, "n": len(g),
                     "censurado_dir": int((g["status"] == "right").sum()),
                     "censurado_esq": int((g["status"] == "left").sum())})
    summ = pd.DataFrame(summ)
    summ.to_csv(OUT / "E1_capacidade_tabela.csv", index=False)
    print("\nE1: capacidade sob SLA (carga relativa)\n",
          summ.pivot(index="policy", columns="scen", values="C_SLA").round(2).to_string())
    print(summ[(summ.censurado_dir > 0) | (summ.censurado_esq > 0)].to_string(index=False))

    # H1: L4 - L1 por política, pareado por semente
    cs = cap.set_index(["policy", "scen", "seed"])["cap"]
    h1, det = [], []
    for pol in POLS:
        m, lo, hi = paired_ci(cs[pol]["L4"], cs[pol]["L1"])
        h1.append(lo > 0)
        det.append(f"{pol}: {m:+.2f} [{lo:+.2f}; {hi:+.2f}]")
    verdict(ver, "H1", "IC95% de C_SLA(L4)-C_SLA(L1) > 0 para toda política", all(h1), "; ".join(det))

    # H2: ganho de política (prio - fifo, L1) vs ganho de diversidade (fifo L4 - L1)
    pol_gain = cs["prio"]["L1"] - cs["fifo"]["L1"]
    div_gain = cs["fifo"]["L4"] - cs["fifo"]["L1"]
    mp, lp, hp = boot_ci(pol_gain)
    md, ld, hd = boot_ci(div_gain)
    mdd, ldd, hdd = paired_ci(pol_gain, div_gain)
    verdict(ver, "H2", "descritiva: ganho de política x ganho de diversidade (L=1)", None,
            f"política(prio-fifo)={mp:+.2f} [{lp:+.2f};{hp:+.2f}]; "
            f"diversidade(fifo L4-L1)={md:+.2f} [{ld:+.2f};{hd:+.2f}]; "
            f"diferença={mdd:+.2f} [{ldd:+.2f};{hdd:+.2f}]")

    fig, ax = plt.subplots(figsize=(7, 3.8))
    w = 0.2
    for i, sc in enumerate(SCENS):
        s = summ[summ.scen == sc].set_index("policy").reindex(POLS)
        ax.bar(np.arange(len(POLS)) + (i - 1.5) * w, s["C_SLA"], w,
               yerr=[s["C_SLA"] - s["lo"], s["hi"] - s["C_SLA"]], capsize=2, label=sc)
    ax.set_xticks(range(len(POLS)), POLS)
    ax.set_ylabel("capacidade sob SLA (carga relativa)")
    ax.set_ylim(1.0, 2.5)
    ax.axhline(1.56, color="gray", lw=0.7, ls="--")
    ax.legend(title="canal (média 50 PRB)", fontsize=7)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "E1_capacidade.png", dpi=150)

    fig, axes = plt.subplots(1, 4, figsize=(14, 3.4), sharey=True)
    for ax, sc in zip(axes, SCENS):
        for pol in POLS:
            g = q.xs((sc, pol), level=[0, 1]).reset_index().groupby("load")["m"]
            mm = g.mean()
            ci = g.apply(lambda x: boot_ci(x)[1:])
            ax.errorbar(mm.index, mm.values,
                        yerr=[mm.values - [c[0] for c in ci], [c[1] for c in ci] - mm.values],
                        marker="o", ms=3, capsize=2, label=pol)
        ax.axhline(SLA, color="k", lw=0.7, ls="--")
        ax.set_title(sc)
        ax.set_xlabel("carga relativa")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("min(QoS voz, QoS vídeo)")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "E1_qos_vs_carga.png", dpi=150)


# ---------------------------------------------------------------- E2 (H3)
def report_e2(ver: list) -> None:
    d = load_raw("E2")
    d["cfg"] = d["floor_video"].astype(str) + "/" + d["floor_data"].astype(str)
    key = ["scen", "load", "cfg"]
    rows = []
    for k, g in d.groupby(key):
        r = dict(zip(key, k))
        for c in ("voice", "video", "data"):
            gc = g[g["class"] == c]
            r[f"qos_{c}"] = gc["qos"].mean()
        gd = g[g["class"] == "data"]
        r["data_thr_prb_s"] = gd["throughput_prb_s"].mean()
        r["data_starve_max_ms"] = gd["max_starve_ms"].max()
        r["data_starve_med_ms"] = gd["max_starve_ms"].median()
        rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "E2_tabela.csv", index=False)
    pd.set_option("display.width", 220)
    print("\nE2: piso mínimo\n", t.round(3).to_string(index=False))

    ok, det = [], []
    for (sc, ld), g in d.groupby(["scen", "load"]):
        base = g[g["cfg"] == "0/0"]
        for fd in (1, 2):
            cur = g[g["cfg"] == f"0/{fd}"]
            starve_ok = cur[cur["class"] == "data"]["max_starve_ms"].max() <= 1.0
            costs = []
            for c in ("voice", "video"):
                a = cur[cur["class"] == c].set_index("seed")["qos"]
                b = base[base["class"] == c].set_index("seed")["qos"]
                m, lo, hi = paired_ci(a, b)
                costs.append((c, m, lo, hi))
            cost_ok = all(lo >= -0.01 and hi <= 0.01 for _, _, lo, hi in costs)
            ok.append(starve_ok and cost_ok)
            det.append(f"{sc} {ld}x piso={fd}: starve<=1ms={starve_ok}; "
                       + ", ".join(f"Δ{c}={m:+.3f}[{lo:+.3f};{hi:+.3f}]" for c, m, lo, hi in costs))
    verdict(ver, "H3", "piso 1-2 PRB/slot: starve dados <=1 ms (todas sementes) e |ΔQoS voz/vídeo|<=0,01",
            all(ok), " | ".join(det))

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    for ax, ld in zip(axes, (1.6, 2.0)):
        for sc, mk in (("fixed", "o"), ("L1", "s")):
            g = t[(t.scen == sc) & (t.load == ld) & t.cfg.str.startswith("0/")]
            g = g.sort_values("cfg", key=lambda s: s.str.split("/").str[1].astype(int))
            fd = g["cfg"].str.split("/").str[1].astype(int)
            ax.plot(fd, g["qos_video"], mk + "-", label=f"vídeo {sc}")
            ax.plot(fd, g["qos_voice"], mk + "--", label=f"voz {sc}")
        ax.set_title(f"carga {ld}x")
        ax.set_xlabel("piso de dados (PRB/slot)")
        ax.set_ylabel("QoS")
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "E2_piso.png", dpi=150)


# ---------------------------------------------------------------- E3 (H4)
def report_e3(ver: list) -> None:
    d = load_raw("E3")
    v = d[d["class"] == "voice"]
    t = v.groupby(["load", "stagger", "policy"])["qos"].mean().unstack("policy")
    t.to_csv(OUT / "E3_tabela.csv")
    print("\nE3: QoS da voz por K (sub-rajadas)\n", t.round(3).to_string())
    flips = []
    for ld, g in v.groupby("load"):
        pq = g.pivot_table(index=["stagger", "seed"], columns="policy", values="qos")
        pols = list(pq.columns)
        for i, a in enumerate(pols):
            for b in pols[i + 1:]:
                s1 = np.sign(paired_ci(pq.loc[1][a], pq.loc[1][b])[0])
                for k in sorted(pq.index.get_level_values(0).unique()):
                    m, lo, hi = paired_ci(pq.loc[k][a], pq.loc[k][b])
                    if s1 != 0 and np.sign(m) == -s1 and (lo > 0 or hi < 0):
                        flips.append(f"{ld}x K={k}: {a}-{b}={m:+.3f}[{lo:+.3f};{hi:+.3f}]")
    verdict(ver, "H4", "ordem das políticas (QoS voz) igual à de K=1 p/ todo K; troca c/ IC>0 refuta",
            not flips, "sem trocas significativas" if not flips else "; ".join(flips))

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), sharey=True)
    for ax, ld in zip(axes, (1.5, 1.8)):
        for pol in ("fifo", "prio", "edf", "dwrr"):
            g = v[(v.load == ld) & (v.policy == pol)].groupby("stagger")["qos"]
            m = g.mean()
            ci = np.array([boot_ci(x)[1:] for _, x in g])
            ax.errorbar(m.index, m.values, yerr=[m.values - ci[:, 0], ci[:, 1] - m.values],
                        marker="o", capsize=2, label=pol)
        ax.set_xscale("log")
        ax.set_title(f"carga {ld}x")
        ax.set_xlabel("K (sub-rajadas por período)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("QoS da voz")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "E3_rajadas.png", dpi=150)


# ---------------------------------------------------------------- E4 (H6)
def report_e4(ver: list) -> None:
    d = pd.read_csv(OUT / "E4_raw.csv")
    d["variante"] = d["duration"].astype(int).astype(str) + "s/" + d["trim"]
    t = d.pivot_table(index=["policy", "load", "class"], columns="variante", values="qos")
    t.to_csv(OUT / "E4_tabela.csv")
    print("\nE4: QoS por variante de medição\n", t.round(3).to_string())
    ref = "20s/trim"
    hit, det = [], []
    for (pol, ld, c), _ in t.iterrows():
        g = d[(d.policy == pol) & (d.load == ld) & (d["class"] == c)]
        a = g[g.variante == "4s/none"].set_index("seed")["qos"]
        b = g[g.variante == ref].set_index("seed")["qos"]
        m, lo, hi = paired_ci(a, b)
        if abs(m) > 0.01 and (lo > 0 or hi < 0):
            hit.append(True)
            det.append(f"{pol} {ld}x {c}: {m:+.3f}[{lo:+.3f};{hi:+.3f}]")
    ordens = []
    for var in ("4s/none", ref):
        for ld in (1.8, 2.0):
            s = t.xs(ld, level="load").xs("voice", level="class")[var]
            ordens.append(f"{var} {ld}x voz: " + ">".join(s.sort_values(ascending=False).index))
    verdict(ver, "H6", "|QoS(4s sem trim)-QoS(20s trim)|>0,01 com IC≠0 em ao menos 1 (política,carga,classe)",
            bool(hit), ("; ".join(det[:8]) or "nenhuma diferença relevante") + " || " + "; ".join(ordens))


# ---------------------------------------------------------------- E5 (H5)
def report_e5(ver: list) -> None:
    d = load_raw("E5")
    v = d[d["class"] == "voice"]
    t = v.groupby(["policy", "load", "speed"])["qos"].mean().unstack("speed")
    t.to_csv(OUT / "E5_tabela.csv")
    print("\nE5: QoS da voz x velocidade (m/s)\n", t.round(3).to_string())
    g = v[(v.policy == "prio") & (v.load == 1.5)].pivot_table(index="seed", columns="speed", values="qos")
    m, lo, hi = paired_ci(g[30.0], g[0.3])
    verdict(ver, "H5", "IC95% de QoS_voz(30 m/s)-QoS_voz(0,3 m/s) > 0 (prio, 1,5x, L=1)", lo > 0,
            f"{m:+.3f} [{lo:+.3f}; {hi:+.3f}]")

    fig, ax = plt.subplots(figsize=(6, 3.6))
    for (pol, ld), grp in v.groupby(["policy", "load"]):
        s = grp.groupby("speed")["qos"]
        mm = s.mean()
        ci = np.array([boot_ci(x)[1:] for _, x in s])
        ax.errorbar(mm.index, mm.values, yerr=[mm.values - ci[:, 0], ci[:, 1] - mm.values],
                    marker="o", capsize=2, label=f"{pol} {ld}x")
    ax.set_xscale("log")
    ax.set_xlabel("velocidade (m/s)  [T_c ≈ 0,42/f_D; f_D = v·fc/c]")
    ax.set_ylabel("QoS da voz (Rayleigh L=1, média 50 PRB)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "E5_velocidade.png", dpi=150)


def main() -> None:
    os.sched_setaffinity(0, {0, 4})
    exps = sys.argv[1:] or ["E1", "E2", "E3", "E4", "E5"]
    fns = {"E1": report_e1, "E2": report_e2, "E3": report_e3, "E4": report_e4, "E5": report_e5}
    ver: list = []
    for e in exps:
        if (OUT / f"{e}_raw.csv").exists():
            fns[e](ver)
        else:
            print(f"{e}: sem dados")
    v = pd.DataFrame(ver)
    v.to_csv(OUT / "veredito.csv", index=False)
    pd.set_option("display.max_colwidth", 400)
    print("\n=== VEREDITOS ===")
    for r in ver:
        print(f"{r['hipotese']}: {r['veredito']}  ({r['regra']})\n    {r['detalhe']}")


if __name__ == "__main__":
    main()
