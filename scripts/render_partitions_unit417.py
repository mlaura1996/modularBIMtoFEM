"""Chapter 9 figure: unit 417 coloured by the MPI process that owns each
element, for 2, 4 and 8 processes (the METIS partitions of the scalability
benchmark), rendered by gmsh off screen like the strain figures and put
side by side in the thesis figure style.

    conda activate castelnuovo_viewer
    python scripts/render_partitions_unit417.py <benchmark_dir> [out_dir] [nparts] --render-only
    python scripts/render_partitions_unit417.py <benchmark_dir> [out_dir] [nparts] --compose-only

Two steps because the castelnuovo_viewer environment, which has the gmsh
that renders off screen, has a matplotlib that crashes on the thesis font;
the composition runs with any Python that has matplotlib and Pillow.
Without a flag both steps run in the same process.

<benchmark_dir> is the output of docker/opensees/benchmark_unit417_build.py
(model/mesh.msh, model/np<N>/rank<r>_lists.tcl, build_summary.json). The
colours are the Okabe-Ito colour-blind-safe set.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

REPO_ROOT = Path(__file__).resolve().parent.parent
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SRC = Path(ARGS[0])
OUT = Path(ARGS[1]) if len(ARGS) > 1 else REPO_ROOT / "output/castelnuovo/plots/chapter9"
NPARTS = [int(v) for v in (ARGS[2] if len(ARGS) > 2 else "2,4,8").split(",")]
OUT.mkdir(parents=True, exist_ok=True)
CAMERA = (-60, 0, -40)
PRINT_W, PRINT_H = 1800, 1800
OKABE_ITO = [(230, 159, 0), (86, 180, 233), (0, 158, 115), (240, 228, 66),
             (0, 114, 178), (213, 94, 0), (204, 121, 167), (153, 153, 153)]


def raw_path(npart):
    return OUT / f"unit417_partition_np{npart}_view.png"


def render():
    import gmsh

    def rank_elements(npart):
        out = []
        for r in range(npart):
            text = open(SRC / "model" / f"np{npart}" / f"rank{r}_lists.tcl").read()
            out.append([int(v) for v in re.search(r"set RANK_ELES \{([^}]*)\}", text).group(1).split()])
        return out

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    for name, val in (("GraphicsPositionX", -32000), ("GraphicsPositionY", -32000),
                      ("GraphicsWidth", 50), ("GraphicsHeight", 50), ("Trackball", 0),
                      ("Axes", 0), ("BackgroundGradient", 0), ("SmallAxes", 0)):
        gmsh.option.setNumber(f"General.{name}", val)
    gmsh.option.setColor("General.Background", 255, 255, 255)
    # light from the viewer, so every face keeps its process colour
    # recognisable (the default light from the upper right turns the faces
    # turned away from it almost black)
    for k, val in (("Light0X", 0.0), ("Light0Y", 0.0), ("Light0Z", 1.0)):
        gmsh.option.setNumber(f"General.{k}", val)
    # zoom out a little: the default fit crops the top and the foot of the unit
    for k in ("ScaleX", "ScaleY", "ScaleZ"):
        gmsh.option.setNumber(f"General.{k}", 0.70)
    gmsh.fltk.initialize()
    gmsh.open(str(SRC / "model" / "mesh.msh"))
    model = gmsh.model.getCurrent()
    for opt in ("Geometry.Points", "Geometry.Curves", "Geometry.Surfaces", "Geometry.Volumes",
                "Mesh.Points", "Mesh.Lines", "Mesh.SurfaceEdges", "Mesh.SurfaceFaces",
                "Mesh.VolumeEdges", "Mesh.VolumeFaces"):
        gmsh.option.setNumber(opt, 0)
    for npart in NPARTS:
        eles = rank_elements(npart)
        tags = [t for es in eles for t in es]
        vals = [[float(r)] for r, es in enumerate(eles) for _t in es]
        v = gmsh.view.add(f"np{npart}")
        gmsh.view.addModelData(v, 0, model, "ElementData", tags, vals, numComponents=1)
        for opt, val in (("RangeType", 2), ("CustomMin", -0.5), ("CustomMax", npart - 0.5),
                         ("IntervalsType", 3), ("NbIso", npart), ("ShowScale", 0)):
            gmsh.view.option.setNumber(v, opt, val)
        opt_path = OUT / "_colortable.opt"
        table = ", ".join("{%d, %d, %d}" % c for c in OKABE_ITO[:npart])
        opt_path.write_text(f"View[{gmsh.view.getIndex(v)}].ColorTable = {{ {table} }};\n")
        gmsh.merge(str(opt_path))
        opt_path.unlink()
        gmsh.fltk.finalize()
        gmsh.fltk.initialize()
        gmsh.option.setNumber("Print.Width", PRINT_W)
        gmsh.option.setNumber("Print.Height", PRINT_H)
        for ax, rot in zip("XYZ", CAMERA):
            gmsh.option.setNumber(f"General.Rotation{ax}", rot)
        gmsh.write(str(raw_path(npart)))
        gmsh.view.remove(v)
        print(f"np={npart}: {len(tags)} elements rendered -> {raw_path(npart)}", flush=True)
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

    summ = json.load(open(SRC / "build_summary.json"))
    dirs = [Path.home() / "AppData/Local/Microsoft/Windows/Fonts", Path("C:/Windows/Fonts"),
            REPO_ROOT / "resources/fonts", Path("C:/Users/mlaur/Documents/aggregate_tests/graph_maker")]
    for name in ("n015003t.ttf", "n015006t.ttf"):     # News Gothic Regular, then Bold
        path = next((d / name for d in dirs if (d / name).exists()), None)
        if path:
            font_manager.fontManager.addfont(str(path))
            rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
    rcParams["font.weight"] = "normal"
    rcParams.update({"font.size": 16, "legend.frameon": False})
    # The figure is printed at the text width of the thesis (about 6.3 in): an
    # 11 in wide figure keeps the 16 pt text at about 9 pt on the page. Each
    # unit occupies the upper part of its column, inset from the borders, the
    # title above it and the legend below it, with clear space in between.
    n = len(NPARTS)
    fig = plt.figure(figsize=(11.0, 6.4))
    col_w = 1.0 / n
    for k, npart in enumerate(NPARTS):
        info = summ["partitions"][str(npart)]
        x0 = k * col_w
        fig.text(x0 + col_w / 2, 0.97, f"{npart} processes", ha="center", va="top", fontsize=17)
        fig.text(x0 + col_w / 2, 0.915, f"{info['shared_nodes']} shared nodes", ha="center", va="top",
                 fontsize=16, color="0.25")
        ax = fig.add_axes([x0 + 0.12 * col_w, 0.32, 0.76 * col_w, 0.50])
        ax.imshow(np.asarray(crop(Image.open(raw_path(npart)).convert("RGB"))))
        ax.set_axis_off()
        ax.legend(handles=[Patch(facecolor=np.array(OKABE_ITO[r]) / 255, edgecolor="black", lw=0.6,
                                 label=f"Process {r}") for r in range(npart)],
                  loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=2, fontsize=15,
                  handlelength=1.2, columnspacing=1.2, labelspacing=0.35)
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"scalability_partitions.{ext}", dpi=220, bbox_inches="tight")
    print(f"saved {OUT / 'scalability_partitions'}.png/.svg")


if "--compose-only" not in sys.argv:
    render()
if "--render-only" not in sys.argv:
    compose()
