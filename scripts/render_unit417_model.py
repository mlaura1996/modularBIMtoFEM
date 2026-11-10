"""Chapter 9, Figure 9.1: structural unit 417 of the scalability benchmark.

(a) the Castelnuovo di Porto aggregate with the volumes of unit 417 coloured
    by material and every other volume in light grey;
(b) the isolated benchmark model (the wall shared with unit 418 trimmed to
    the eaves line), coloured by material.

Masonry types take the colour-blind-safe palette of the knowledge-graph
pages and the enrichment editor (type A #2f6fa3, type D #c67aa6), stone and
brick their muted tones. Rendered by gmsh off screen as element data, like
the partition figure, then composed in the thesis figure style.

    conda activate castelnuovo_viewer
    python scripts/render_unit417_model.py <benchmark_dir> [out_dir] --render-only
    python scripts/render_unit417_model.py <benchmark_dir> [out_dir] --compose-only

<benchmark_dir> holds model/mesh.msh of benchmark_unit417_build.py.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

REPO_ROOT = Path(__file__).resolve().parent.parent
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SRC = Path(ARGS[0])
OUT = Path(ARGS[1]) if len(ARGS) > 1 else REPO_ROOT / "output/castelnuovo/plots/chapter9"
OUT.mkdir(parents=True, exist_ok=True)
STEP_PATH = REPO_ROOT / "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
VOLUME_MATERIALS = REPO_ROOT / "resources/survey_data/castelnuovo/volume_materials.json"
BOX = (13.8, 21.3, -17.3, -7.4)               # plan box of unit 417 (centroids), as the build
MATERIALS = [  # name, label, colour
    ("Tufelli_masonry_typeA", "Tuff masonry, type A", (0x2f, 0x6f, 0xa3)),
    ("Tufelli_masonry_typeD", "Tuff masonry, type D", (0xc6, 0x7a, 0xa6)),
    ("Stone", "Stone", (0xd3, 0xc8, 0xb1)),
    ("Bricks", "Brick", (0xb9, 0x80, 0x6a)),
]
OTHER = ("other", "Other structural units", (0xe6, 0xe2, 0xda))
INDEX = {m[0]: i for i, m in enumerate(MATERIALS)}
CAM_AGGREGATE = (-60, 0, -70)
CAM_UNIT = (-60, 0, -70)          # the camera of (a), so the unit is seen from the same side


def raw(name):
    return OUT / f"unit417_model_{name}.png"


def render():
    import gmsh

    def setup():
        gmsh.option.setNumber("General.Terminal", 0)
        for name, val in (("GraphicsPositionX", -32000), ("GraphicsPositionY", -32000),
                          ("GraphicsWidth", 50), ("GraphicsHeight", 50), ("Trackball", 0),
                          ("Axes", 0), ("BackgroundGradient", 0), ("SmallAxes", 0)):
            gmsh.option.setNumber(f"General.{name}", val)
        gmsh.option.setColor("General.Background", 255, 255, 255)
        for k, val in (("Light0X", 0.0), ("Light0Y", 0.0), ("Light0Z", 1.0)):
            gmsh.option.setNumber(f"General.{k}", val)

    def hide_all():
        for opt in ("Geometry.Points", "Geometry.Curves", "Geometry.Surfaces", "Geometry.Volumes",
                    "Mesh.Points", "Mesh.Lines", "Mesh.SurfaceEdges", "Mesh.SurfaceFaces",
                    "Mesh.VolumeEdges", "Mesh.VolumeFaces"):
            gmsh.option.setNumber(opt, 0)

    def element_view(values_by_volume, colours, path, camera, scale, size):
        tags, vals = [], []
        for vol, val in values_by_volume.items():
            _et, etg, _en = gmsh.model.mesh.getElements(3, vol)
            for block in etg:
                tags += [int(t) for t in block]
                vals += [[float(val)]] * len(block)
        v = gmsh.view.add("material")
        gmsh.view.addModelData(v, 0, gmsh.model.getCurrent(), "ElementData", tags, vals, numComponents=1)
        n = len(colours)
        for opt, val in (("RangeType", 2), ("CustomMin", -0.5), ("CustomMax", n - 0.5),
                         ("IntervalsType", 3), ("NbIso", n), ("ShowScale", 0)):
            gmsh.view.option.setNumber(v, opt, val)
        opt_path = OUT / "_colortable.opt"
        opt_path.write_text(f"View[{gmsh.view.getIndex(v)}].ColorTable = {{ "
                            + ", ".join("{%d, %d, %d}" % c for c in colours) + " };\n")
        gmsh.merge(str(opt_path))
        opt_path.unlink()
        for k in ("ScaleX", "ScaleY", "ScaleZ"):
            gmsh.option.setNumber(f"General.{k}", scale)
        gmsh.fltk.finalize()
        gmsh.fltk.initialize()
        gmsh.option.setNumber("Print.Width", size[0])
        gmsh.option.setNumber("Print.Height", size[1])
        for ax, rot in zip("XYZ", camera):
            gmsh.option.setNumber(f"General.Rotation{ax}", rot)
        gmsh.write(str(path))
        gmsh.view.remove(v)
        print(f"wrote {path}", flush=True)

    colours = [m[2] for m in MATERIALS] + [OTHER[2]]

    # (a) the aggregate, unit 417 by material, the rest grey
    gmsh.initialize()
    setup()
    gmsh.fltk.initialize()
    gmsh.open(str(STEP_PATH))
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    mat = {int(k): v["material"] for k, v in json.load(open(VOLUME_MATERIALS, encoding="utf-8"))["volumes"].items()}
    gmsh.option.setNumber("Mesh.MeshSizeMax", 0.8)
    gmsh.model.mesh.generate(3)
    hide_all()
    values = {}
    for _d, vol in gmsh.model.getEntities(3):
        cx, cy, _cz = gmsh.model.occ.getCenterOfMass(3, vol)
        inside = BOX[0] <= cx <= BOX[1] and BOX[2] <= cy <= BOX[3]
        values[vol] = INDEX.get(mat.get(vol), len(MATERIALS)) if inside else len(MATERIALS)
    element_view(values, colours, raw("aggregate"), CAM_AGGREGATE, 0.85, (2600, 2000))
    gmsh.fltk.finalize()
    gmsh.finalize()

    # (b) the benchmark model
    gmsh.initialize()
    setup()
    gmsh.fltk.initialize()
    gmsh.open(str(SRC / "model" / "mesh.msh"))
    hide_all()
    values = {}
    for _d, pg in gmsh.model.getPhysicalGroups(3):
        name = gmsh.model.getPhysicalName(3, pg)
        for vol in gmsh.model.getEntitiesForPhysicalGroup(3, pg):
            values[int(vol)] = INDEX[name]
    element_view(values, colours, raw("unit"), CAM_UNIT, 0.82, (1800, 1800))
    gmsh.fltk.finalize()
    gmsh.finalize()


def crop(im, pad=10):
    bg = Image.new("RGB", im.size, (255, 255, 255))
    l, t, r, b = ImageChops.difference(im, bg).convert("L").point(lambda p: 255 if p > 8 else 0).getbbox()
    return im.crop((max(l - pad, 0), max(t - pad, 0), min(r + pad, im.width), min(b + pad, im.height)))


def compose():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams, font_manager
    from matplotlib.patches import Patch

    dirs = [Path.home() / "AppData/Local/Microsoft/Windows/Fonts", Path("C:/Windows/Fonts"),
            REPO_ROOT / "resources/fonts", Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker")]
    for name in ("n015003t.ttf", "n015006t.ttf"):     # News Gothic Regular, then Bold
        path = next((d / name for d in dirs if (d / name).exists()), None)
        if path:
            font_manager.fontManager.addfont(str(path))
            rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
    rcParams.update({"font.weight": "normal", "font.size": 15})
    agg = crop(Image.open(raw("aggregate")).convert("RGB"))
    unit = crop(Image.open(raw("unit")).convert("RGB"))
    ratio_a = agg.width / agg.height
    ratio_u = unit.width / unit.height
    # 11 in wide: the figure is printed at the text width of the thesis (6.3 in),
    # so the legend still reads at about 8.5 pt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.0, 5.2),
                                 gridspec_kw={"width_ratios": [ratio_a, ratio_u * 1.0]})
    for ax, im, label in ((a1, agg, "(a)"), (a2, unit, "(b)")):
        ax.imshow(np.asarray(im))
        ax.set_axis_off()
        ax.set_title(label, fontsize=16)
    handles = [Patch(facecolor=np.array(c) / 255, edgecolor="black", lw=0.6, label=lab)
               for _n, lab, c in MATERIALS + [OTHER]]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=15, frameon=False,
               bbox_to_anchor=(0.5, -0.09), handlelength=1.4, columnspacing=1.6)
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"unit417_model.{ext}", dpi=220, bbox_inches="tight")
    print(f"saved {OUT / 'unit417_model'}.png/.svg")


if "--compose-only" not in sys.argv:
    render()
if "--render-only" not in sys.argv:
    compose()
