#!/usr/bin/env python3
"""Chapter 9: the response of unit 417 on the building in one figure, small
panels. Columns: envelope of the maximum tensile principal strain, envelope
of the maximum compressive principal strain, displacement at the peak roof
displacement (deformed shape); rows: the two views. One colour bar under
each column, in the ten-band colour table of the strain figures.

Composes the gmsh renders written by scripts/render_strain_figure_gmsh.py
and scripts/render_displacement_unit417.py (run those first, in the
castelnuovo_viewer environment); the colour scales are recomputed from the
same results with the same rules (99th percentile rounded up to two
significant figures for the strains, maximum rounded up to 0.5 mm for the
displacement), so they match the renders.

    python scripts/plot_unit417_response_maps.py <results_unit417 dir> [render_dir]
"""
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams, font_manager
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.cm import ScalarMappable

REPO_ROOT = Path(__file__).resolve().parent.parent
RES = Path(sys.argv[1])
RENDER = Path(sys.argv[2]) if len(sys.argv) > 2 else (
    REPO_ROOT / "output/castelnuovo/plots/chapter9/unit417_response")
BAND_COLOURS = [(255, 255, 255), (246, 246, 229), (235, 235, 189), (223, 212, 168),
                (212, 184, 154), (202, 152, 138), (183, 120, 120), (148, 97, 97),
                (104, 68, 68), (0, 0, 0)]

FONT_DIRS = [Path.home() / "AppData/Local/Microsoft/Windows/Fonts", Path("C:/Windows/Fonts"),
             REPO_ROOT / "resources/fonts", Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker")]
for name in ("n015003t.ttf", "n015006t.ttf"):     # News Gothic Regular, then Bold
    path = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
    if path:
        font_manager.fontManager.addfont(str(path))
        rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
rcParams.update({"font.weight": "normal", "font.size": 14, "mathtext.fontset": "dejavuserif",
                 "xtick.direction": "in", "xtick.major.size": 4, "xtick.major.width": 1.0,
                 "axes.linewidth": 1.0})


def round_up_2sf(x):
    e = np.floor(np.log10(x)) - 1
    return float(np.ceil(x / 10 ** e) * 10 ** e)


tens, comp = [], []
with open(RES / "principal_strains.csv") as fh:
    for row in csv.DictReader(fh):
        tens.append(float(row["max_tensile_principal_strain"]))
        comp.append(abs(float(row["max_compressive_principal_strain"])))
clip_t = round_up_2sf(np.percentile(tens, 99))
clip_c = round_up_2sf(np.percentile(comp, 99))
with open(RES / "displacement.csv") as fh:
    fh.readline()
    u = np.array([[float(v) for v in row[1:4]] for row in csv.reader(fh)])
top_u = float(np.ceil(np.linalg.norm(u, axis=1).max() * 1000 * 2) / 2)


def crop(path, pad=8):
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    l, t, r, b = ImageChops.difference(im, bg).convert("L").point(lambda p: 255 if p > 8 else 0).getbbox()
    return im.crop((max(l - pad, 0), max(t - pad, 0), min(r + pad, im.width), min(b + pad, im.height)))


COLUMNS = [
    ("castelnuovo_strain_tension", "Maximum tensile\nprincipal strain", clip_t * 1e4,
     r"$\varepsilon_1$ [$\times 10^{-4}$]"),
    ("castelnuovo_strain_compression", "Maximum compressive\nprincipal strain", clip_c * 1e4,
     r"$|\varepsilon_3|$ [$\times 10^{-4}$]"),
    ("unit417_displacement", "Displacement at the peak\nroof displacement (×200)", top_u,
     r"$|u|$ [mm]"),
]
cmap = ListedColormap(np.array(BAND_COLOURS) / 255)

fig = plt.figure(figsize=(10.5, 9.4))
col_w = 1.0 / 3
for j, (stem, title, top, unit) in enumerate(COLUMNS):
    x0 = j * col_w
    fig.text(x0 + col_w / 2, 0.94, title, ha="center", va="top", fontsize=15, linespacing=1.15)
    for i, view in enumerate(("view1", "view2")):
        img = crop(RENDER / f"{stem}_{view}.png")
        ax = fig.add_axes([x0 + 0.04 * col_w, 0.52 - i * 0.39, 0.92 * col_w, 0.37])
        ax.imshow(np.asarray(img))
        ax.set_axis_off()
    cax = fig.add_axes([x0 + 0.14 * col_w, 0.075, 0.72 * col_w, 0.022])
    bounds = np.linspace(0, top, len(BAND_COLOURS) + 1)
    cb = fig.colorbar(ScalarMappable(norm=BoundaryNorm(bounds, cmap.N), cmap=cmap), cax=cax,
                      orientation="horizontal", ticks=bounds[::5])
    cb.ax.set_xticklabels([f"{v:.3g}" for v in bounds[::5]], fontsize=13)
    cb.outline.set_linewidth(1.0)
    cb.set_label(unit, fontsize=14, labelpad=4)
    print(f"{stem}: scale 0 to {top:.3g}")

out = RENDER / "unit417_response_maps"
for ext in ("png", "svg"):
    fig.savefig(f"{out}.{ext}", dpi=220, bbox_inches="tight")
print(f"saved {out}.png/.svg")
