"""
Static visualization of Task A candidate wall-to-wall interfaces,
rendered by gmsh's OWN graphics engine (real building geometry - walls,
openings, the actual aggregate shape), not reconstructed from scratch in
matplotlib. Headless: `gmsh.fltk.initialize()` + `gmsh.write(*.png)`
renders and saves a screenshot without opening a blocking interactive
window.

(A first version plotted candidate centroids as bare points in matplotlib
- no wall outlines, unreadable, dropped: matplotlib has no CAD/BREP
rendering of its own, so a point cloud is all it could show without
reconstructing wall geometry by hand.)

Run OUTSIDE Docker, on a local conda environment with ifcopenshell,
pythonocc-core, gmsh, apeGmsh (see docs/source/user_guide/installation.md):

    python scripts/plot_candidate_interfaces.py

Deliberately does NOT use core.ifc_processing.ifc_step_matching's real
IFC-type classification (point-in-solid tests - a real bottleneck,
minutes in some environments) - instead uses a cheap volume-size
threshold to drop small door/window frame volumes (walls are far larger).

Produces two PNGs under output/castelnuovo/plots/ - candidate_interfaces_
real_plan.png (top view) and _iso.png (isometric) - the real building,
wireframe (not solid-shaded: tried solid walls + an alpha-transparency
color first so the internal candidate surfaces would show through the
masonry, but the alpha channel wasn't respected in the screenshot -
wireframe has no fill to hide anything behind, confirmed working),
candidate wall-to-wall interfaces highlighted in red
(gmsh.model.setColor(..., recursive=True) - recursive=False silently did
nothing, confirmed by a dedicated test coloring the whole building bright
green first).

Numbers aren't baked into these images (gmsh's own screenshot has no
simple way to stamp arbitrary per-candidate text) - use them to see WHERE
the candidates are, then do the actual selection in
scripts/inspect_interfaces.py's live window, which shows the same real
geometry and lets you identify each highlighted surface's number from its
physical-group name in the "Physical groups" panel.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
OUT_DIR = "output/castelnuovo/plots"
PLOT_ORIENTATIONS = ("vertical_joint",)
MIN_VOLUME_M3 = 0.3  # cheap door/window-frame filter - walls are far bigger

os.makedirs(OUT_DIR, exist_ok=True)

with apeGmsh(model_name="plot_candidates") as g:
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.", flush=True)

    big_vol_tags = {t for _d, t in all_vols if gmsh.model.occ.getMass(3, t) >= MIN_VOLUME_M3}
    print(f"{len(big_vol_tags)}/{len(all_vols)} volumes >= {MIN_VOLUME_M3} m^3 "
          f"(cheap door/window-frame filter).", flush=True)

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidates total.", flush=True)

    numbered = [(i, c) for i, c in enumerate(candidates, start=1)
                if c["orientation"] in PLOT_ORIENTATIONS
                and c["volume_a"] in big_vol_tags and c["volume_b"] in big_vol_tags]
    print(f"{len(numbered)} candidates will be highlighted "
          f"(orientation in {PLOT_ORIENTATIONS}, both volumes >= {MIN_VOLUME_M3} m^3).",
          flush=True)

    # Candidate interfaces are internal faces sandwiched between two solid
    # wall volumes - invisible from any exterior view against opaque
    # walls (found by looking: the first render showed no red at all,
    # solid masonry everywhere). Fix: make the wall volumes themselves
    # semi-transparent (gmsh.model.setColor's alpha channel) so the
    # bright, fully-opaque red interfaces show through.
    for _d, t in all_vols:
        gmsh.model.setColor([(3, t)], 200, 200, 210, 255, recursive=True)
    for _i, c in numbered:
        gmsh.model.setColor([(2, c["surface"])], 255, 0, 0, 255, recursive=True)

    # Number labels, in gmsh's own 3D view (not stamped on afterward -
    # gmsh.view.addListDataString positions real text at each candidate's
    # centroid, rendered as part of the same screenshot).
    label_view = gmsh.view.add("candidate_numbers")
    for i, c in numbered:
        gmsh.view.addListDataString(label_view, list(c["centroid"]), [str(i)],
                                     ["Font", "Helvetica-Bold", "FontSize", "14",
                                      "Align", "Center"])
    view_idx = gmsh.view.getIndex(label_view)
    gmsh.option.setNumber(f"View[{view_idx}].Visible", 1)
    gmsh.option.setNumber(f"View[{view_idx}].ShowScale", 0)

    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Geometry.Surfaces", 1)
    # Wireframe, not solid-shaded (tried solid + alpha transparency first -
    # the alpha channel wasn't respected in the screenshot, so the
    # internal red candidate surfaces stayed completely hidden behind
    # opaque exterior walls). Wireframe has no fill to hide anything
    # behind, at the cost of a less "solid" look.
    gmsh.option.setNumber("Geometry.SurfaceType", 0)
    gmsh.option.setNumber("Geometry.LineWidth", 2)
    gmsh.option.setNumber("General.Trackball", 0)
    gmsh.fltk.initialize()

    views = [
        ("plan", 0, 0, 0),      # default/top-ish view (matches the working test render)
        ("iso", -35, 0, -35),   # a rotated, more 3D-legible view
    ]
    written = []
    for name, rx, ry, rz in views:
        if rx or ry or rz:
            gmsh.option.setNumber("General.RotationX", rx)
            gmsh.option.setNumber("General.RotationY", ry)
            gmsh.option.setNumber("General.RotationZ", rz)
        path = os.path.join(OUT_DIR, f"candidate_interfaces_real_{name}.png")
        gmsh.write(path)
        written.append(path)
        print(f"Wrote {path}", flush=True)

print(f"\nDone - wrote {len(written)} real-geometry screenshots under "
      "output/castelnuovo/plots/, candidate interfaces highlighted in red. "
      "Use them to see WHERE the candidates are, then do the actual "
      "selection in scripts/inspect_interfaces.py's live window.",
      flush=True)
