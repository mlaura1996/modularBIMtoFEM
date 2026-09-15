#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hysteretic loop (base shear coefficient vs global drift) for the
Castelnuovo nonlinear time-history, in the thesis figure style.

Reads response_clean.csv (scripts/clean_hysteretic_response.py's output),
NOT the raw response.csv - the raw base shear carries numerical spikes up
to 157x the structure's own weight that have nothing to do with the real
seismic response (see that script's module docstring for the full
diagnosis and the three checks that justified despiking rather than
discarding this run). Plotting the raw column would put a spurious
±150-scale loop on the same axes as a real ~1-2-scale response and make
the real loop invisible.

Styling matches graph_maker/plot_paper_style.py exactly - the same script
that already produced this chapter's other hysteresis figures - so this
one sits consistently beside them: URW Nimbus Roman, square-ish figure,
primary axes in drift% / base-shear-coefficient with secondary axes in
mm / kN, symmetric limits with margin, light axhline/axvline at zero.

    python scripts/plot_hysteresis_castelnuovo.py [results_dir] [out_stem]
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
RESULTS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    REPO_ROOT / "output/castelnuovo/results_timehistory")
OUT_STEM = Path(sys.argv[2]) if len(sys.argv) > 2 else (
    REPO_ROOT / "output/castelnuovo/plots/hysteresis_castelnuovo")

HEIGHT_M = 15.175876266060005   # model_height_m, from summary_postprocess.json
WEIGHT_N = 8_862_669.0          # self_weight_N - same value every run agrees on

# Same font search as plot_modal_participation_paper.py.
FONT_CANDIDATES = [
    Path(os.environ["THESIS_FONT"]) if os.environ.get("THESIS_FONT") else None,
    REPO_ROOT / "resources/fonts/n015006t.ttf",
    Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker/n015006t.ttf"),
    Path.home() / "Documents/aggregate_tests/graph_maker/n015006t.ttf",
]
FONT_PATH = next((p for p in FONT_CANDIDATES if p and p.exists()), FONT_CANDIDATES[-1])
if FONT_PATH.exists():
    font_manager.fontManager.addfont(str(FONT_PATH))
    font_name = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
else:
    font_name = "DejaVu Serif"
    print(f"WARNING: {FONT_PATH} not found - falling back to {font_name}.")

rcParams.update({
    "font.family": font_name,
    "mathtext.fontset": "dejavuserif",
    "axes.linewidth": 1.6,
    "xtick.direction": "in", "ytick.direction": "in",
    "xtick.major.size": 6, "ytick.major.size": 6,
    "xtick.major.width": 1.4, "ytick.major.width": 1.4,
    "font.size": 15,
})

in_path = RESULTS_DIR / "response_clean.csv"
if not in_path.is_file():
    sys.exit(f"Missing {in_path} - run scripts/clean_hysteretic_response.py first.")
with open(in_path) as fh:
    rows = list(csv.DictReader(fh))

drift_pct = np.array([float(r["drift_ratio"]) for r in rows]) * 100.0
coeff = np.array([float(r["BS_clean_over_W"]) for r in rows])
n_spikes = sum(int(r["spike_flag"]) for r in rows)

fig, ax = plt.subplots(figsize=(7.2, 5.4))
ax.axhline(0, color="0.7", lw=0.6, zorder=0)
ax.axvline(0, color="0.7", lw=0.6, zorder=0)
ax.plot(drift_pct, coeff, color="#00204d", lw=1.2, zorder=3,
        label="Castelnuovo (Run 2.1, despiked)")

ax.set_xlabel("Global drift ratio [%]")
ax.set_ylabel("Base shear coefficient")

xmax = np.abs(drift_pct).max()
ymax = np.abs(coeff).max()
ax.set_xlim(-xmax * 1.12, xmax * 1.12)
ax.set_ylim(-ymax * 1.12, ymax * 1.12)

sx = ax.secondary_xaxis(
    "top", functions=(lambda d: d / 100 * HEIGHT_M * 1000,
                      lambda mm: mm / (HEIGHT_M * 1000) * 100))
sx.set_xlabel("Displacement [mm]")
sy = ax.secondary_yaxis(
    "right", functions=(lambda c: c * WEIGHT_N / 1000.0,
                        lambda kN: kN * 1000.0 / WEIGHT_N))
sy.set_ylabel("Base shear [kN]")

ax.legend(loc="lower right", frameon=True, framealpha=1.0,
          edgecolor="black", fontsize=13)

note = (f"{n_spikes}/{len(rows)} steps ({100*n_spikes/len(rows):.0f}%) despiked - "
        f"see clean_hysteretic_response.py")
fig.text(0.5, -0.01, note, ha="center", va="top", fontsize=8, color="0.4")

fig.tight_layout()
for ext in ("png", "svg"):
    out = f"{OUT_STEM}.{ext}"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    print(f"Saved: {out}")
print(f"Font used: {font_name}")
print(f"peak drift = {xmax:.4f}%, peak coefficient = {ymax:.4f}")
print(f"{n_spikes}/{len(rows)} steps despiked ({100*n_spikes/len(rows):.1f}%)")
