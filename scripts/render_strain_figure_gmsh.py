"""Thesis figures of the principal strain envelopes (Figures 8.36 and 8.37),
rendered by gmsh off screen and composed like the earlier screenshots: the
two views of the aggregate stacked, a vertical colour bar on the right and
the small axes at the bottom right.

Same fields, colour map and cameras as scripts/view_timehistory_gmsh.py:
ElementData of every element, the ten-band white-to-black colour table of the
earlier figures, filled iso bands, the scale clipped at the 99th percentile so the few
numerical hot spots do not flatten the rest of the structure.

    conda activate castelnuovo_viewer
    python scripts/render_strain_figure_gmsh.py [results_dir] [out_dir]
"""
import csv
import os
import sys

import numpy as np
import gmsh
from PIL import Image, ImageChops

RUN_DIR = (sys.argv[1] if len(sys.argv) > 1
           else "output/castelnuovo/results_timehistory_mesh03_descaled").rstrip("/\\")
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "output/castelnuovo/plots/descaled"
CLIP_PERCENTILE = 99.0
N_BANDS = 10
CAMERAS = {"1": (-60, 0, -70), "2": (130, 180, -70)}   # Tools > Manipulator rotation
PRINT_W, PRINT_H = 2600, 2000
os.makedirs(OUT_DIR, exist_ok=True)

idx_to_tag = {}
with open(f"{RUN_DIR}/sampled_elements.txt") as fh:
    for line in fh:
        if not line.startswith("#"):
            i, tag = line.strip().split(",")
            idx_to_tag[int(i)] = int(tag)
tags, tens, comp = [], [], []
with open(f"{RUN_DIR}/principal_strains.csv") as fh:
    for row in csv.DictReader(fh):
        i = int(row["element_index"])
        if i in idx_to_tag:
            tags.append(idx_to_tag[i])
            tens.append(float(row["max_tensile_principal_strain"]))
            comp.append(abs(float(row["max_compressive_principal_strain"])))
tens, comp = np.array(tens), np.array(comp)
def round_up_2sf(x):
    """The end of the colour scale: the percentile rounded UP to two
    significant figures, so the value written at the end of the bar is
    exactly where the colours end (e.g. 6.45e-3 -> 0.0065)."""
    e = np.floor(np.log10(x)) - 1
    return float(np.ceil(x / 10 ** e) * 10 ** e)


FIELDS = {
    # name: (values, end of the colour scale, sign of the label)
    "tension": (tens, round_up_2sf(np.percentile(tens, CLIP_PERCENTILE)), 1),
    "compression": (comp, round_up_2sf(np.percentile(comp, CLIP_PERCENTILE)), -1),
}
for k, (v, c, _) in FIELDS.items():
    print(f"{k}: {len(v)} elements, clipped at {c:.4e}, {(v > c).sum()} above")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
for name, val in (("GraphicsPositionX", -32000), ("GraphicsPositionY", -32000),
                  ("GraphicsWidth", 50), ("GraphicsHeight", 50),
                  ("Trackball", 0), ("Axes", 0), ("BackgroundGradient", 0)):
    gmsh.option.setNumber(f"General.{name}", val)
gmsh.option.setColor("General.Background", 255, 255, 255)
gmsh.option.setColor("General.SmallAxes", 90, 90, 90)
gmsh.fltk.initialize()
gmsh.open(f"{RUN_DIR}/mesh.msh")
model = gmsh.model.getCurrent()
for opt in ("Geometry.Points", "Geometry.Curves", "Geometry.Surfaces", "Geometry.Volumes",
            "Mesh.Points", "Mesh.Lines", "Mesh.SurfaceEdges", "Mesh.SurfaceFaces",
            "Mesh.VolumeEdges", "Mesh.VolumeFaces"):
    gmsh.option.setNumber(opt, 0)


def shot(path, rot, small_axes=False):
    gmsh.fltk.finalize()
    gmsh.fltk.initialize()
    gmsh.option.setNumber("Print.Width", PRINT_W)
    gmsh.option.setNumber("Print.Height", PRINT_H)
    gmsh.option.setNumber("General.SmallAxes", 1 if small_axes else 0)
    gmsh.option.setNumber("General.SmallAxesSize", 70)
    gmsh.option.setNumber("General.SmallAxesPositionX", -150)
    gmsh.option.setNumber("General.SmallAxesPositionY", -150)
    for ax, r in zip("XYZ", rot):
        gmsh.option.setNumber(f"General.Rotation{ax}", r)
    gmsh.write(path)
    # With gmsh's built-in colour maps the off-screen export came out with
    # red and blue swapped ("hot" turned cyan); with the explicit ColorTable
    # below the colours come out as given, so no channel fix is needed.
    return Image.open(path).convert("RGB")


def crop(im, pad=10):
    bg = Image.new("RGB", im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).convert("L").point(lambda p: 255 if p > 8 else 0).getbbox()
    l, t, r, b = box
    return im.crop((max(l - pad, 0), max(t - pad, 0), min(r + pad, im.width), min(b + pad, im.height)))


def colour_bar(height, width=34):
    """Vertical bar like gmsh's: white (0) at the top, the ten bands of
    BAND_COLOURS down to black."""
    bands = BAND_COLOURS
    bar = Image.new("RGB", (width, height), (255, 255, 255))
    px = bar.load()
    for y in range(height):
        c = bands[min(int(y / height * len(bands)), len(bands) - 1)]
        for x in range(width):
            px[x, y] = c
    from PIL import ImageDraw
    ImageDraw.Draw(bar).rectangle([0, 0, width - 1, height - 1], outline=(0, 0, 0), width=2)
    return bar


def sci_label(x):
    """6.5e-3 -> '6.5 × 10⁻³' (the minus of a negative value as U+2212)."""
    sup = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
    e = int(np.floor(np.log10(abs(x))))
    m = abs(x) / 10 ** e
    sign = "−" if x < 0 else ""
    return f"{sign}{m:.2g} × 10{str(e).translate(sup)}"


def compose(name, views, axes_glyph, clip, sign):
    from PIL import ImageDraw, ImageFont
    gap = 60
    w = max(v.width for v in views)
    h = sum(v.height for v in views) + gap
    bar_h = int(0.62 * h)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 46)
    except OSError:
        font = ImageFont.load_default()
    label_lo = "0"
    label_hi = sci_label(sign * clip)
    right = 440
    canvas = Image.new("RGB", (w + right, h + 40), (255, 255, 255))
    y = 0
    for v in views:
        canvas.paste(v, ((w - v.width) // 2, y))
        y += v.height + gap
    bar = colour_bar(bar_h)
    bx, by = w + 70, int(0.12 * h)
    canvas.paste(bar, (bx, by))
    d = ImageDraw.Draw(canvas)
    d.text((bx + bar.width + 14, by - 30), label_lo, fill=(0, 0, 0), font=font)
    d.text((bx + bar.width + 14, by + bar_h - 30), label_hi, fill=(0, 0, 0), font=font)
    canvas.paste(axes_glyph, (bx - 40, min(by + bar_h + 90, canvas.height - axes_glyph.height - 10)))
    out = f"{OUT_DIR}/castelnuovo_strain_{name}_figure.png"
    canvas.save(out, dpi=(300, 300))
    print(f"Wrote {out} ({canvas.width}x{canvas.height})")


# The ten bands of the colour bar of the earlier thesis figures (read off
# their pixels): white, cream, pale yellow, beige, pink, mauve, brown, black.
# Given to gmsh as the view's own ColorTable, so the render and the bar use
# exactly the same colours; gmsh's built-in "pink" map is darker and more
# olive than these when exported off screen.
BAND_COLOURS = [(255, 255, 255), (246, 246, 229), (235, 235, 189), (223, 212, 168),
                (212, 184, 154), (202, 152, 138), (183, 120, 120), (148, 97, 97),
                (104, 68, 68), (0, 0, 0)]
N_BANDS = len(BAND_COLOURS)


def set_colour_table(view_tag):
    """View.ColorTable is a list option, which the gmsh API cannot set
    directly; merge a one-line option file instead."""
    idx = gmsh.view.getIndex(view_tag)
    table = ", ".join("{%d, %d, %d}" % c for c in BAND_COLOURS)
    path = f"{OUT_DIR}/_colortable.opt"
    with open(path, "w") as fh:
        fh.write(f"View[{idx}].ColorTable = {{ {table} }};" + "\n")
    gmsh.merge(path)
    os.remove(path)


axes_glyph = None
for name, (vals, clip, sign) in FIELDS.items():
    v = gmsh.view.add(name)
    gmsh.view.addModelData(v, 0, model, "ElementData", tags,
                           [[float(x)] for x in np.minimum(vals, clip)], numComponents=1)
    for opt, val in (("RangeType", 2), ("CustomMin", 0.0), ("CustomMax", clip),
                     ("IntervalsType", 3), ("NbIso", N_BANDS), ("ShowScale", 0)):
        gmsh.view.option.setNumber(v, opt, val)
    set_colour_table(v)
    views = []
    for cam, rot in CAMERAS.items():
        raw = f"{OUT_DIR}/castelnuovo_strain_{name}_view{cam}.png"
        views.append(crop(shot(raw, rot)))
        if axes_glyph is None and cam == "2":
            with_axes = shot(f"{OUT_DIR}/_axes.png", rot, small_axes=True)
            without = Image.open(raw).convert("RGB")
            diff = ImageChops.difference(with_axes, without).convert("L").point(lambda p: 255 if p > 8 else 0)
            axes_glyph = with_axes.crop(diff.getbbox())
            os.remove(f"{OUT_DIR}/_axes.png")
    compose(name, views, axes_glyph, clip, sign)
    gmsh.view.remove(v)

gmsh.fltk.finalize()
gmsh.finalize()
