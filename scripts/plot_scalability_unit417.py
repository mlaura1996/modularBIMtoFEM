#!/usr/bin/env python3
"""Chapter 9 figures of the unit 417 scalability benchmark, in the thesis
figure style (graph_maker: Nimbus Roman, inward ticks, heavy axes).

    python scripts/plot_scalability_unit417.py <benchmark_dir or results csv> [out_dir]

Reads <benchmark_dir>/benchmark_results.csv (benchmark_unit417_post.py) or
any csv with the columns label, np, system, transient_s and peak_rss_MB
(or peak_rss_MB missing). Writes, as png and svg:

  scalability_speedup      speed-up against the number of processes (to
                           MUMPS on one process and to UmfPack on one
                           process), the ideal line and the Amdahl law
                           fitted to the measurements; parallel efficiency
                           beside it
  scalability_time         wall time per step of every configuration, with
                           the part due to the solver choice and the part
                           due to the partitioning
  scalability_memory       peak memory of one process and an upper bound
                           of the total, against the number of processes
  scalability_correctness  (only if benchmark_timehistories.csv is there)
                           roof displacement and base shear of every run
                           over the window, and their largest difference
                           from the sequential UmfPack run
"""
import csv
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams, font_manager

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "output/castelnuovo/plots/chapter9"
OUT.mkdir(parents=True, exist_ok=True)
CSV = SRC / "benchmark_results.csv" if SRC.is_dir() else SRC
HIST = SRC / "benchmark_timehistories.csv" if SRC.is_dir() else None

# The thesis font is News Gothic (URW n0150xxt): n015003t.ttf is the
# Regular the graph_maker figures are drawn in (installed in Windows, so
# matplotlib picks it for the family "NewsGotT"); n015006t.ttf, the file kept
# in the graph_maker folder, is the Bold of the same family. Both are
# registered and the family is asked for at normal weight.
FONT_DIRS = [Path(os.environ["THESIS_FONT_DIR"]) if os.environ.get("THESIS_FONT_DIR") else None,
             Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
             Path("C:/Windows/Fonts"),
             REPO_ROOT / "resources/fonts",
             Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker")]
font_name = "DejaVu Serif"
for name in ("n015003t.ttf", "n015006t.ttf"):
    path = next((d / name for d in FONT_DIRS if d and (d / name).exists()), None)
    if path:
        font_manager.fontManager.addfont(str(path))
        font_name = font_manager.FontProperties(fname=str(path)).get_name()
if not any(d and (d / "n015003t.ttf").exists() for d in FONT_DIRS):
    print("WARNING: News Gothic Regular (n015003t.ttf) not found - the text will not match the thesis figures")
rcParams.update({
    "font.family": font_name, "font.weight": "normal", "mathtext.fontset": "dejavuserif",
    "axes.linewidth": 1.6,
    "xtick.direction": "in", "ytick.direction": "in",
    "xtick.major.size": 6, "ytick.major.size": 6,
    "xtick.major.width": 1.4, "ytick.major.width": 1.4,
    "font.size": 15,
    "legend.frameon": True, "legend.framealpha": 1.0, "legend.edgecolor": "black",
    "legend.fancybox": True, "legend.fontsize": 14,
})
GRID = dict(ls=":", lw=0.6, alpha=0.5)
NAVY, RED, GREY = "#00204d", "#8b0000", "0.45"

rows = list(csv.DictReader(open(CSV)))
umf = next(r for r in rows if r["system"].lower() == "umfpack")
mumps = sorted((r for r in rows if r["system"].lower() == "mumps"), key=lambda r: int(r["np"]))
p = np.array([int(r["np"]) for r in mumps])
T = np.array([float(r["transient_s"]) for r in mumps])
T_umf = float(umf["transient_s"])
steps = int(umf.get("steps_done") or umf.get("iterations") or 425)
S = T[0] / T
S_umf = T_umf / T
E = S / p

# Amdahl's law, S(p) = 1 / (f + (1 - f) / p), least squares on S
fs = np.linspace(0.0, 0.6, 60001)
f = fs[np.argmin([((1 / (x + (1 - x) / p) - S) ** 2).sum() for x in fs])]
pp = np.linspace(1, p.max(), 200)
kf = [(1 / s - 1 / q) / (1 - 1 / q) for s, q in zip(S, p) if q > 1]
print(f"speed-up {np.round(S, 2)}, efficiency {np.round(E, 2)}, to UmfPack {np.round(S_umf, 2)}")
print(f"Amdahl serial fraction f = {f:.3f} (limit {1 / f:.1f}); Karp-Flatt {np.round(kf, 3)}")


def save(fig, name):
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"saved {OUT / name}.png/.svg")


# --- speed-up and efficiency -------------------------------------------------------
fig, (a1, a2) = plt.subplots(1, 2, figsize=(14.4, 5.4))
a1.plot([1, p.max()], [1, p.max()], color=GREY, lw=1.2, ls="--", label="Ideal")
a1.plot(pp, 1 / (f + (1 - f) / pp), color=NAVY, lw=1.0, ls=":",
        label=f"Amdahl's law, $f$ = {f:.2f}")
a1.plot(p, S, "o-", color=NAVY, lw=1.6, ms=7, label="MUMPS, relative to MUMPS on 1 process")
a1.plot(p, S_umf, "s-", color=RED, lw=1.6, ms=7, label="MUMPS, relative to UmfPack on 1 process")
for x, y in zip(p, S):
    a1.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(8, -14), fontsize=12, color=NAVY)
for x, y in zip(p, S_umf):
    a1.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(-14, 8), fontsize=12, color=RED)
a1.set_xlim(0.5, p.max() + 0.9)
a1.set_ylim(0, p.max() + 0.5)
a1.set_xticks(p)
a1.set_xlabel("Number of MPI processes")
a1.set_ylabel("Speed-up [-]")
a1.grid(True, **GRID)
a1.legend(loc="upper left", fontsize=13)

a2.axhline(1.0, color=GREY, lw=1.2, ls="--")
a2.plot(p, E, "o-", color=NAVY, lw=1.6, ms=7)
for x, y in zip(p, E):
    a2.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(6, 8), fontsize=12, color=NAVY)
a2.set_xlim(0.5, p.max() + 0.9)
a2.set_ylim(0, 1.1)
a2.set_xticks(p)
a2.set_xlabel("Number of MPI processes")
a2.set_ylabel("Parallel efficiency [-]")
a2.grid(True, **GRID)
save(fig, "scalability_speedup")

# --- wall time per step ------------------------------------------------------------
labels = ["UmfPack\n1"] + [f"MUMPS\n{q}" for q in p]
tps = np.concatenate(([T_umf], T)) / steps
fig, ax = plt.subplots(figsize=(8.4, 5.4))
cols = [RED] + [NAVY] * len(p)
bars = ax.bar(range(len(tps)), tps, color=cols, width=0.62, edgecolor="black", linewidth=0.8)
for b, v, tt in zip(bars, tps, np.concatenate(([T_umf], T))):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.12, f"{v:.2f} s\n({tt / 60:.0f} min)",
            ha="center", va="bottom", fontsize=11)
ax.set_xticks(range(len(tps)))
ax.set_xticklabels(labels, fontsize=13)
ax.set_xlabel("Solver and number of MPI processes")
ax.set_ylabel("Wall time per step [s]")
ax.set_ylim(0, tps.max() * 1.25)
ax.grid(True, axis="y", **GRID)
ax.set_axisbelow(True)
save(fig, "scalability_time")

# --- memory --------------------------------------------------------------------------
if all(r.get("peak_rss_MB") for r in mumps):
    m1 = np.array([float(r["peak_rss_MB"]) for r in mumps]) / 1024
    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    ax.plot(p, m1, "o-", color=NAVY, lw=1.6, ms=7, label="One process (largest)")
    ax.plot(p, m1 * p, "s--", color=RED, lw=1.4, ms=6, label="All processes (upper bound)")
    ax.plot(pp, m1[0] / pp, color=GREY, lw=1.0, ls=":", label="Ideal, $M_1/p$")
    for x, y in zip(p, m1):
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(6, 8), fontsize=12, color=NAVY)
    ax.set_xticks(p)
    ax.set_xlim(0.5, p.max() + 0.9)
    ax.set_ylim(0, max((m1 * p).max(), m1.max()) * 1.15)
    ax.set_xlabel("Number of MPI processes")
    ax.set_ylabel("Peak memory [GB]")
    ax.grid(True, **GRID)
    ax.legend(loc="upper right", fontsize=13)
    save(fig, "scalability_memory")

# --- correctness -----------------------------------------------------------------------
if HIST is not None and HIST.is_file():
    h = list(csv.DictReader(open(HIST)))
    t = np.array([float(r["time_s"]) for r in h])
    # the timed runs start at the beginning of the record window: shift to
    # the time of the de-scaled record, as in the Chapter 8 figures
    bs_path = SRC / "build_summary.json"
    if bs_path.is_file():
        import json
        t = t + float(json.load(open(bs_path))["window_s"][0])
    runs = [k[:-6] for k in h[0] if k.endswith("_Rd_mm")]
    ref = "np1_umfpack" if "np1_umfpack" in runs else runs[0]
    rd = {k: np.array([float(r[f"{k}_Rd_mm"]) for r in h]) for k in runs}
    vb = {k: np.array([float(r[f"{k}_Vb_over_W"]) for r in h]) for k in runs}
    # The largest relative differences are taken from benchmark_results.csv,
    # computed by benchmark_unit417_post.py on the recorder files at full
    # precision: the time-history csv keeps 6 decimals, so differences taken
    # from it would only show its rounding (about 1e-6 of the peak).
    worst = {"Rd": max(float(r.get("Rd_diff_rel") or 0) for r in rows),
             "Vb": max(float(r.get("Vb_diff_rel") or 0) for r in rows)}

    def sci(x):
        if x == 0:
            return "0 (identical)"
        e = int(np.floor(np.log10(x)))
        return f"{x / 10 ** e:.1f}" + r"$\times$10$^{" + str(e) + "}$"

    fig, axes = plt.subplots(1, 2, figsize=(14.4, 5.6))
    shades = plt.cm.Blues(np.linspace(0.45, 0.95, len(runs) - 1))
    for col, (key, data, ylab) in enumerate((("Rd", rd, "Roof displacement, $R_d$ [mm]"),
                                             ("Vb", vb, "Base shear coefficient, $V_b/W$ [-]"))):
        ax = axes[col]
        k_m = 0
        for k in runs:
            if k == ref:
                ax.plot(t, data[k], color=RED, lw=2.6, label="UmfPack, 1 process", zorder=1)
                continue
            q = k.split("_")[0][2:]
            ax.plot(t, data[k], color=shades[k_m], lw=1.0, ls="--",
                    label=f"MUMPS, {q} process{'es' if q != '1' else ''}", zorder=2)
            k_m += 1
        ax.axhline(0, color="0.7", lw=0.6, zorder=0)
        ax.set_xlabel("Time [s]")
        ax.set_ylabel(ylab)
        ax.set_xlim(t[0], t[-1])
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo - 0.22 * (hi - lo), hi + 0.42 * (hi - lo))
        ax.set_xticks(np.arange(np.round(t[0] * 2) / 2, t[-1] + 1e-9, 0.5))
        ax.set_xlim(np.round(t[0] * 2) / 2, t[-1])
        ax.grid(True, **GRID)
        ax.text(0.98, 0.04, "largest relative difference from\nUmfPack, 1 process: " + sci(worst[key]),
                transform=ax.transAxes, ha="right", va="bottom", fontsize=13)
        if col == 0:
            ax.legend(loc="upper left", fontsize=12, ncol=3, columnspacing=1.0, handlelength=1.6)
    save(fig, "scalability_correctness")
print(f"font: {font_name}")
