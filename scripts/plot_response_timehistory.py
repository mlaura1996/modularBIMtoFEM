#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Response time-history over the strong-motion window: roof displacement
(Rd) and interface opening (Id), in the thesis figure style (matching
Chapter 6's Figure 6.16: two panels side by side, 5-14 s window).

Rd comes from response_clean.csv (despiked + low-pass filtered - see
clean_hysteretic_response.py; Rd itself needed no cleaning, it was smooth
in the raw recording throughout, but reading it from the same file keeps
one source of truth). Id comes straight from interface_opening.csv - a
relative displacement between two node pairs, not a reaction/contact
force, and checked before use: its peak (4.52e-2 m) lands at t = 12.445 s,
essentially at the record's 12.345 s PGA, its largest step-to-step jump is
27x the median rather than the 1000x+ seen in the base shear, and its five
largest values sit together in time and decrease smoothly away from the
peak - the signature of a real recorded event, not noise. Not despiked.

    python scripts/plot_response_timehistory.py [results_dir] [out_stem]
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
    REPO_ROOT / "output/castelnuovo/plots/response_timehistory")

T_START, T_END = 5.0, 14.0   # Chapter 6's own strong-motion window

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

with open(RESULTS_DIR / "response_clean.csv") as fh:
    resp = list(csv.DictReader(fh))
t_rd = np.array([float(r["time_s"]) for r in resp])
rd_mm = np.array([float(r["Rd_m"]) for r in resp]) * 1000.0

id_path = RESULTS_DIR / "interface_opening.csv"
t_id = op_mm = None
if id_path.is_file():
    with open(id_path) as fh:
        iface = list(csv.DictReader(fh))
    t_id = np.array([float(r["time_s"]) for r in iface])
    op_mm = np.array([float(r["max_opening_m"]) for r in iface]) * 1000.0

panels = [("Rd", t_rd, rd_mm, "Roof displacement, $R_d$ [mm]", "#00204d")]
if t_id is not None:
    panels.append(("Id", t_id, op_mm, "Interface opening, $I_d$ [mm]", "#8b0000"))

fig, axes = plt.subplots(1, len(panels), figsize=(7.2 * len(panels), 5.4))
if len(panels) == 1:
    axes = [axes]

for ax, (key, t, y, ylabel, color) in zip(axes, panels):
    m = (t >= T_START) & (t <= T_END)
    ax.plot(t[m], y[m], color=color, lw=1.1)
    ax.axhline(0, color="0.7", lw=0.6, zorder=0)
    ax.set_xlim(T_START, T_END)
    ax.set_xlabel("Time [s]")
    ax.set_ylabel(ylabel)
    peak_i = np.argmax(np.abs(y[m]))
    peak_t = t[m][peak_i]
    ax.axvline(peak_t, color="0.5", lw=0.8, ls=":", zorder=1)
    print(f"{key}: peak {y[m][peak_i]:.4f} mm at t = {peak_t:.3f} s "
          f"(window {T_START}-{T_END} s)")

fig.tight_layout()
for ext in ("png", "svg"):
    out = f"{OUT_STEM}.{ext}"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    print(f"Saved: {out}")
print(f"Font used: {font_name}")
