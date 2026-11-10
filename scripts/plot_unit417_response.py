#!/usr/bin/env python3
"""Chapter 9: response of unit 417 on its own to the de-scaled Montenegro
record (the results run of the scalability benchmark), in the graph_maker
style: roof displacement Rd and base shear coefficient Vb/W over the whole
record, the peak of each marked.

    python scripts/plot_unit417_response.py <results_unit417 dir> [out_stem]
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
OUT_STEM = Path(sys.argv[2]) if len(sys.argv) > 2 else (
    REPO_ROOT / "output/castelnuovo/plots/chapter9/unit417_response/unit417_response_timehistory")
OUT_STEM.parent.mkdir(parents=True, exist_ok=True)

FONT_DIRS = [Path.home() / "AppData/Local/Microsoft/Windows/Fonts", Path("C:/Windows/Fonts"),
             REPO_ROOT / "resources/fonts", Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker")]
font_name = "DejaVu Serif"
for name in ("n015003t.ttf", "n015006t.ttf"):     # News Gothic Regular, then Bold
    path = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
    if path:
        font_manager.fontManager.addfont(str(path))
        font_name = font_manager.FontProperties(fname=str(path)).get_name()
rcParams.update({
    "font.family": font_name, "font.weight": "normal", "mathtext.fontset": "dejavuserif",
    "axes.linewidth": 1.6, "xtick.direction": "in", "ytick.direction": "in",
    "xtick.major.size": 6, "ytick.major.size": 6,
    "xtick.major.width": 1.4, "ytick.major.width": 1.4, "font.size": 15,
})
GRID = dict(ls=":", lw=0.6, alpha=0.5)

rows = list(csv.DictReader(open(SRC / "response.csv")))
t = np.array([float(r["time_s"]) for r in rows])
rd = np.array([float(r["Rd_mm"]) for r in rows])
vb = np.array([float(r["Vb_over_W"]) for r in rows])

fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.3))
for ax, y, ylab, color, unit in ((axes[0], rd, "Roof displacement, $R_d$ [mm]", "#00204d", "mm"),
                                 (axes[1], vb, "Base shear coefficient, $V_b/W$ [-]", "#8b0000", "")):
    ax.plot(t, y, color=color, lw=1.1)
    ax.axhline(0, color="0.7", lw=0.6, zorder=0)
    k = int(np.argmax(np.abs(y)))
    ax.axvline(t[k], color="0.5", lw=0.8, ls=":", zorder=1)
    lim = np.abs(y).max() * 1.22
    ax.set_ylim(-lim, lim)
    label = f"{y[k]:.2f}".replace("-", "−") + (f" {unit}" if unit else "") + f" at {t[k]:.2f} s"
    ax.annotate(label, (t[k], y[k]), textcoords="offset points", xytext=(8, -6 if y[k] < 0 else 6),
                va="top" if y[k] < 0 else "bottom", fontsize=13)
    ax.set_xlim(0, t[-1])
    ax.set_xlabel("Time [s]")
    ax.set_ylabel(ylab)
    ax.grid(True, **GRID)
    print(f"{ylab}: peak {y[k]:.4f} at t = {t[k]:.3f} s")
fig.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(f"{OUT_STEM}.{ext}", dpi=220, bbox_inches="tight")
    print(f"saved {OUT_STEM}.{ext}")
