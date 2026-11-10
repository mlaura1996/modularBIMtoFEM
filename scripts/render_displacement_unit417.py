"""Chapter 9: deformed shape of unit 417 at the peak roof displacement of
the results run (displacement.csv of benchmark_unit417_fields.py, net of
the self-weight state), coloured by the norm of the displacement, the
undeformed edges in grey. Rendered by gmsh off screen and composed like the
strain figures (scripts/render_strain_figure_gmsh.py): the two views
stacked, the same ten-band colour table, the bar on the right.

    conda activate castelnuovo_viewer
    python scripts/render_displacement_unit417.py <results_unit417 dir> [out_dir] [--factor 200]
"""
import csv
import os
import sys

import numpy as np
import gmsh
from PIL import Image, ImageChops, ImageDraw, ImageFont

ARGS = [a for i, a in enumerate(sys.argv[1:], 1)
        if not a.startswith("--") and sys.argv[i - 1] != "--factor"]
RUN_DIR = ARGS[0].rstrip("/\\")
OUT_DIR = ARGS[1] if len(ARGS) > 1 else "output/castelnuovo/plots/chapter9/unit417_response"
FACTOR = float(sys.argv[sys.argv.index("--factor") + 1]) if "--factor" in sys.argv else 200.0
CAMERAS = {"1": (-60, 0, -70), "2": (130, 180, -70)}
SCALE = 0.68
PRINT_W, PRINT_H = 2600, 2000
BAND_COLOURS = [(255, 255, 255), (246, 246, 229), (235, 235, 189), (223, 212, 168),
                (212, 184, 154), (202, 152, 138), (183, 120, 120), (148, 97, 97),
                (104, 68, 68), (0, 0, 0)]
os.makedirs(OUT_DIR, exist_ok=True)

tags, vecs = [], []
with open(f"{RUN_DIR}/displacement.csv") as fh:
    header = fh.readline()
    snapshot = header.split("t =")[-1].strip() if "t =" in header else "?"
    for row in csv.reader(fh):
        tags.append(int(row[0]))
        vecs.append([float(row[1]), float(row[2]), float(row[3])])
vecs = np.array(vecs)
norm = np.linalg.norm(vecs, axis=1)
top = float(np.ceil(norm.max() * 1000 * 2) / 2)          # mm, rounded up to 0.5
print(f"{len(tags)} nodes, snapshot at {snapshot}, max |u| {norm.max() * 1000:.2f} mm, "
      f"scale to {top} mm, deformation x{FACTOR:g}")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
for name, val in (("GraphicsPositionX", -32000), ("GraphicsPositionY", -32000),
                  ("GraphicsWidth", 50), ("GraphicsHeight", 50),
                  ("Trackball", 0), ("Axes", 0), ("BackgroundGradient", 0)):
    gmsh.option.setNumber(f"General.{name}", val)
gmsh.option.setColor("General.Background", 255, 255, 255)
gmsh.option.setColor("General.SmallAxes", 90, 90, 90)
for k, val in (("Light0X", 0.0), ("Light0Y", 0.0), ("Light0Z", 1.0)):
    gmsh.option.setNumber(f"General.{k}", val)
for k in ("ScaleX", "ScaleY", "ScaleZ"):
    gmsh.option.setNumber(f"General.{k}", SCALE)
gmsh.fltk.initialize()
gmsh.open(f"{RUN_DIR}/mesh.msh")
model = gmsh.model.getCurrent()
for opt in ("Geometry.Points", "Geometry.Curves", "Geometry.Surfaces", "Geometry.Volumes",
            "Mesh.Points", "Mesh.SurfaceEdges", "Mesh.SurfaceFaces",
            "Mesh.VolumeEdges", "Mesh.VolumeFaces"):
    gmsh.option.setNumber(opt, 0)
# the undeformed edges of the walls: the 1D mesh elements on the geometry curves
gmsh.option.setNumber("Mesh.Lines", 1)
gmsh.option.setNumber("Mesh.LineWidth", 1)
gmsh.option.setNumber("Mesh.ColorCarousel", 0)
gmsh.option.setColor("Mesh.Lines", 170, 170, 170)
gmsh.option.setColor("Mesh.One", 170, 170, 170)

v = gmsh.view.add("displacement")
gmsh.view.addModelData(v, 0, model, "NodeData", tags, vecs.tolist(), numComponents=3)
idx = gmsh.view.getIndex(v)
for opt, val in (("VectorType", 5), ("DisplacementFactor", FACTOR), ("RangeType", 2),
                 ("CustomMin", 0.0), ("CustomMax", top / 1000), ("IntervalsType", 3),
                 ("NbIso", len(BAND_COLOURS)), ("ShowScale", 0), ("ShowElement", 0)):
    gmsh.view.option.setNumber(v, opt, val)
table = ", ".join("{%d, %d, %d}" % c for c in BAND_COLOURS)
with open(f"{OUT_DIR}/_colortable.opt", "w") as fh:
    fh.write(f"View[{idx}].ColorTable = {{ {table} }};\n")
gmsh.merge(f"{OUT_DIR}/_colortable.opt")
os.remove(f"{OUT_DIR}/_colortable.opt")


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
    return Image.open(path).convert("RGB")


def crop(im, pad=10):
    bg = Image.new("RGB", im.size, (255, 255, 255))
    l, t, r, b = ImageChops.difference(im, bg).convert("L").point(lambda p: 255 if p > 8 else 0).getbbox()
    return im.crop((max(l - pad, 0), max(t - pad, 0), min(r + pad, im.width), min(b + pad, im.height)))


views, axes_glyph = [], None
for cam, rot in CAMERAS.items():
    raw = f"{OUT_DIR}/unit417_displacement_view{cam}.png"
    views.append(crop(shot(raw, rot)))
    if cam == "2":
        with_axes = shot(f"{OUT_DIR}/_axes.png", rot, small_axes=True)
        diff = ImageChops.difference(with_axes, Image.open(raw).convert("RGB")).convert("L")
        axes_glyph = with_axes.crop(diff.point(lambda p: 255 if p > 8 else 0).getbbox())
        os.remove(f"{OUT_DIR}/_axes.png")
gmsh.fltk.finalize()
gmsh.finalize()

# --- composition, as the strain figures ------------------------------------------
gap = 60
w = max(im.width for im in views)
h = sum(im.height for im in views) + gap
bar_h, bar_w, right = int(0.62 * h), 34, 440
try:
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 46)
except OSError:
    font = ImageFont.load_default()
canvas = Image.new("RGB", (w + right, h + 40), (255, 255, 255))
y = 0
for im in views:
    canvas.paste(im, ((w - im.width) // 2, y))
    y += im.height + gap
bar = Image.new("RGB", (bar_w, bar_h), (255, 255, 255))
px = bar.load()
for yy in range(bar_h):
    c = BAND_COLOURS[min(int(yy / bar_h * len(BAND_COLOURS)), len(BAND_COLOURS) - 1)]
    for xx in range(bar_w):
        px[xx, yy] = c
ImageDraw.Draw(bar).rectangle([0, 0, bar_w - 1, bar_h - 1], outline=(0, 0, 0), width=2)
bx, by = w + 70, int(0.12 * h)
canvas.paste(bar, (bx, by))
d = ImageDraw.Draw(canvas)
d.text((bx + bar_w + 14, by - 30), "0", fill=(0, 0, 0), font=font)
d.text((bx + bar_w + 14, by + bar_h - 30), f"{top:g} mm", fill=(0, 0, 0), font=font)
d.text((bx - 40, by + bar_h + 60), f"deformation\n× {FACTOR:g}", fill=(0, 0, 0), font=font)
canvas.paste(axes_glyph, (bx - 40, min(by + bar_h + 230, canvas.height - axes_glyph.height - 10)))
out = f"{OUT_DIR}/unit417_displacement_figure.png"
canvas.save(out, dpi=(300, 300))
print(f"Wrote {out} ({canvas.width}x{canvas.height})")
