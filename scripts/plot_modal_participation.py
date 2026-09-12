"""Modal participating-mass chart: PRM per mode vs frequency, plus the
cumulative curves, on a twin axis.

This is the chart that answers "how many modes do I need", i.e. where the
cumulative curve crosses the 85% that NTC2018 7.3.3.1 and EC8 require
before a response-spectrum verification is admissible. With 10 modes the
tied Castelnuovo model reaches only ~52% MX / 55% MY, so the chart exists
partly to make that shortfall visible rather than to hide it in a table.

Reads modal_properties.txt as written by the eigen scripts (sections 9 and
10 - the per-mode and cumulative participation mass RATIOS in %) and
eigenvalues.txt for the frequencies.

Runs locally, no Docker needed:

    conda activate castelnuovo_viewer
    python scripts/plot_modal_participation.py \
        output/castelnuovo/recorders_castelnuovo_tied
"""
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DATA_DIR = (sys.argv[1] if len(sys.argv) > 1
            else "output/castelnuovo/recorders_castelnuovo_tied")
OUT_PNG = (sys.argv[2] if len(sys.argv) > 2
           else "output/castelnuovo/plots/modal_participation.png")
TARGET = 85.0  # % - NTC2018 7.3.3.1 / EC8 threshold


def _ratio_section(text, heading):
    """Rows of one '* N. ...' section of modal_properties.txt as
    (mode, mx, my, mz)."""
    body = text.split(heading)[1].split("\n*")[0]
    rows = []
    for line in body.splitlines():
        p = line.split()
        if len(p) == 7 and p[0].isdigit():
            rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3])))
    return np.array(rows)


with open(os.path.join(DATA_DIR, "modal_properties.txt")) as f:
    props = f.read()
per_mode = _ratio_section(props, "* 9. MODAL PARTICIPATION MASS RATIOS (%):")
cumul = _ratio_section(props, "* 10. MODAL PARTICIPATION MASS RATIOS (%) (cumulative):")

with open(os.path.join(DATA_DIR, "eigenvalues.txt")) as f:
    eigenvalues = np.array([float(x) for x in f.read().split()])
freq = np.sqrt(eigenvalues) / (2 * math.pi)

n = len(freq)
assert len(per_mode) == n, f"{len(per_mode)} PRM rows vs {n} eigenvalues"

fig, ax = plt.subplots(figsize=(7.2, 4.6))
ax2 = ax.twinx()

# Per-mode participation as markers, not bars: on a masonry aggregate the
# modes cluster tightly in frequency and bars would overlap into a solid
# block that says nothing about which mode is which.
ax.plot(freq, per_mode[:, 1], "^", ms=6, mfc="none", mec="#1f4e79",
        mew=1.3, label=r"$M_X$", zorder=3)
ax.plot(freq, per_mode[:, 2], "o", ms=6, mfc="none", mec="#c00000",
        mew=1.3, label=r"$M_Y$", zorder=3)

# Cumulative curves step at each mode - drawing them as smooth lines would
# imply participation accrues between modes, which it does not.
ax2.step(freq, cumul[:, 1], where="post", color="#1f4e79", lw=1.8,
         label=r"$M_X$ cum")
ax2.step(freq, cumul[:, 2], where="post", color="#c00000", lw=1.8,
         label=r"$M_Y$ cum")

ax.set_xlabel("Frequency (Hz)")
ax.set_ylabel("PRM (%)")
ax2.set_ylabel("Cumulative PRM (%)")
ax.set_ylim(0, max(per_mode[:, 1:3].max() * 1.15, 10))
ax2.set_ylim(0, 100)
ax.set_xlim(freq.min() - 0.3, freq.max() + 0.3)
ax.grid(True, ls=":", lw=0.6, color="0.8", zorder=0)
ax.set_axisbelow(True)

# Drawn with plot() rather than axhline(): axhline hard-crashes the
# interpreter in the castelnuovo_viewer env (exit 127, no traceback, not
# even a partial stdout flush). An env defect, not a usage error - a bare
# ax.axhline(85.0) on a fresh figure reproduces it - so it is avoided here
# rather than worked around at the call site.
x0, x1 = ax.get_xlim()
ax2.plot([x0, x1], [TARGET, TARGET], color="0.45", ls="--", lw=1.0, zorder=1)
ax.set_xlim(x0, x1)
ax2.annotate(f"{TARGET:g}% (NTC2018 7.3.3.1 / EC8)",
             xy=(x1, TARGET), xytext=(-4, 4), textcoords="offset points",
             ha="right", va="bottom", fontsize=7.5, color="0.35")

h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, framealpha=0.9)

fx, fy = cumul[-1, 1], cumul[-1, 2]
ax.set_title(f"{n} modes - cumulative $M_X$ = {fx:.1f}%, $M_Y$ = {fy:.1f}%"
             + ("" if min(fx, fy) >= TARGET else "  (below the 85% threshold)"),
             fontsize=9.5)

os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=220)
print(f"Wrote {OUT_PNG}")

# The number the chart is really for: the first mode at which each
# direction crosses the threshold, or that it never does.
for lbl, col in (("MX", 1), ("MY", 2)):
    hit = np.flatnonzero(cumul[:, col] >= TARGET)
    if len(hit):
        m = int(cumul[hit[0], 0])
        print(f"{lbl}: reaches {TARGET:g}% at mode {m} (f = {freq[m-1]:.2f} Hz)")
    else:
        print(f"{lbl}: NEVER reaches {TARGET:g}% - stops at "
              f"{cumul[-1, col]:.1f}% after {n} modes")
