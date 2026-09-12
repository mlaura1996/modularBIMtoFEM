#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modal participating-mass chart in the thesis figure style.

This is the central panel of the composite modal figure: per-mode PRM as
stems with hollow markers, cumulative curves on a twin axis. The mode-shape
renders that surround it in the final figure are added outside this script.

Styling (font, stems, hollow markers, boxed legend, inward ticks) follows
C:/Users/mlaur/Documents/aggregate_tests/graph_maker/plot_modal_clean.py so
this figure matches the others in the thesis. It differs in where it reads
from: that script parses a modal_properties-style text dump, this one reads
the CSV written by scripts/export_modal_data.py, so the figure and the
tables in the results document come from the same file.

    python scripts/plot_modal_participation_paper.py [in.csv] [out_stem]

Needs an environment whose matplotlib works: the castelnuovo_viewer env
hard-crashes the interpreter (exit 127, no traceback) on a bare axhline and
on twin-axis plotting. Known good:

    C:/Users/mlaur/Anaconda3/envs/plotting/python.exe
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
from matplotlib.ticker import MultipleLocator

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    REPO_ROOT / "output/castelnuovo/plots/modal_data_tied_100modes.csv")
OUT_STEM = Path(sys.argv[2]) if len(sys.argv) > 2 else (
    REPO_ROOT / "output/castelnuovo/plots/modal_participation_paper")

# The same face the other thesis figures use. Not copied into this repo
# (it is not ours to redistribute), so it is looked for in several places
# and the location can be given explicitly - a single hard-coded Windows
# path would break this script on any other machine, which matters now
# that the analysis is moving to a second computer.
FONT_CANDIDATES = [
    Path(os.environ["THESIS_FONT"]) if os.environ.get("THESIS_FONT") else None,
    REPO_ROOT / "resources/fonts/n015006t.ttf",
    Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker/n015006t.ttf"),
    Path.home() / "Documents/aggregate_tests/graph_maker/n015006t.ttf",
]
FONT_PATH = next((p for p in FONT_CANDIDATES if p and p.exists()),
                 FONT_CANDIDATES[-1])

if FONT_PATH.exists():
    font_manager.fontManager.addfont(str(FONT_PATH))
    font_name = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
else:
    font_name = "DejaVu Serif"
    print(f"WARNING: {FONT_PATH} not found - falling back to {font_name}, so "
          f"this figure will NOT match the other thesis figures.")

rcParams.update({
    "font.family": font_name,
    "mathtext.fontset": "dejavuserif",
    "axes.linewidth": 1.6,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.major.size": 6,
    "ytick.major.size": 6,
    "xtick.major.width": 1.4,
    "ytick.major.width": 1.4,
    "font.size": 18,
})

with open(IN_CSV) as f:
    rows = list(csv.DictReader(f))
if not rows:
    sys.exit(f"{IN_CSV} has no data rows")

freq = np.array([float(r["f_Hz"]) for r in rows])
prm_x = np.array([float(r["PRMx"]) for r in rows])
prm_y = np.array([float(r["PRMy"]) for r in rows])
cum_x = np.array([float(r["PRMx_cum"]) for r in rows])
cum_y = np.array([float(r["PRMy_cum"]) for r in rows])

# Axis limits from the data. The reference script hard-codes 10-125 Hz and
# 0-65% for its own model; this aggregate's modes sit between about 6 and
# 37 Hz with no mode above ~21%, so reusing those numbers would leave the
# plot almost empty.
#
# Starting at the first mode rather than at 0 Hz is deliberate: anchoring
# the axis at zero leaves a long empty strip that the cumulative curves can
# only cross as a straight interpolated ramp, which reads as mass building
# up gradually where in fact nothing participates until the first mode.
XMIN = float(np.floor(freq.min() / 5.0) * 5)
XMAX = float(np.ceil(freq.max() / 5.0) * 5)
YMAX = float(np.ceil(max(prm_x.max(), prm_y.max()) / 5.0) * 5 + 5)

fig, ax = plt.subplots(figsize=(7.5, 6))

for f_, p_ in zip(freq, prm_x):
    ax.plot([f_, f_], [0, p_], color="tab:blue", lw=0.8, alpha=0.4, zorder=2)
for f_, p_ in zip(freq, prm_y):
    ax.plot([f_, f_], [0, p_], color="darkred", lw=0.8, alpha=0.4, zorder=2)

ax.scatter(freq, prm_x, marker="^", s=32, facecolors="white",
           edgecolors="tab:blue", linewidths=1.1,
           label="PRM$_x$ (per mode)", zorder=4)
ax.scatter(freq, prm_y, marker="o", s=32, facecolors="white",
           edgecolors="darkred", linewidths=1.1,
           label="PRM$_y$ (per mode)", zorder=4)

ax.set_xlabel("Frequency [Hz]")
ax.set_ylabel("Participating mass ratio [%]")
ax.set_xlim(XMIN, XMAX)
ax.set_ylim(0, YMAX)
ax.xaxis.set_major_locator(MultipleLocator(5))
ax.yaxis.set_major_locator(MultipleLocator(5))

ax2 = ax.twinx()
ax2.plot(freq, cum_x, color="tab:blue", lw=2.0, label="cumulative $x$", zorder=3)
ax2.plot(freq, cum_y, color="darkred", lw=2.0, label="cumulative $y$", zorder=3)
ax2.set_ylabel("Cumulative participating mass [%]")
ax2.set_ylim(0, 100)
ax2.yaxis.set_major_locator(MultipleLocator(20))

h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
# Dropped below mid-height: at "center right" (the reference script's
# placement, which suits its own data) the box's top edge runs into the
# cumulative curves, which on this model plateau around 85% across the
# whole right-hand half of the plot.
ax.legend(h1 + h2, l1 + l2, loc="center right", bbox_to_anchor=(1.0, 0.38),
          frameon=True, framealpha=1.0, edgecolor="black", fontsize=16)

fig.subplots_adjust(left=0.14, right=0.86, bottom=0.13, top=0.97)
for ext in ("png", "svg"):
    out = f"{OUT_STEM}.{ext}"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    print(f"Saved: {out}")
print(f"Font used: {font_name}")
print(f"{len(rows)} modes, {freq.min():.2f}-{freq.max():.2f} Hz, "
      f"final cumulative x = {cum_x[-1]:.2f}%, y = {cum_y[-1]:.2f}%")
