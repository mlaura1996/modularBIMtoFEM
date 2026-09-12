"""
Renders the self-weight + eigenmode shapes with REAL gmsh screenshots
(true OpenGL z-buffer -> correct hidden-surface removal) instead of
matplotlib, whose separate Poly3DCollection/Line3DCollection have no
proper per-pixel depth sorting - confirmed to be the cause of the "x-ray"
look (far-side geometry edges drawn on top of near-side opaque faces) even
after restricting edges to exterior-only surfaces.

Reads the portable, ALREADY-DEFORMED triangle/edge data
docker/opensees/export_gmsh_view_data.py exported (raw coordinates, not a
mesh to regenerate - the local castelnuovo_viewer env's apeGmsh/gmsh
version differs from the Docker image's, so re-meshing locally would not
reproduce the same node numbering; feeding pre-computed geometry directly
sidesteps that).

Colored faces: a gmsh View with "ST" (scalar triangle) list-data - gmsh's
own colormap/scalebar machinery, real depth-buffered rendering.
Geometry edges: actual discrete MESH line elements (not a View) with an
explicit flat RGB color via gmsh.model.setColor - avoids any colormap
guessing and renders through the same mesh pipeline (so it composites
correctly, depth-wise, against the View triangles - both are part of the
one OpenGL scene gmsh draws).

Run locally, on the castelnuovo_viewer conda environment:

    conda activate castelnuovo_viewer
    python scripts/render_eigen_gmsh.py            # all cases
    python scripts/render_eigen_gmsh.py selfweight  # just one, for iterating
"""
import os
import sys

import gmsh
import numpy as np

EXPORT_DIR = "output/castelnuovo/plots/gmsh_export"
OUT_DIR = "output/castelnuovo/plots"
VIEWS = [("view1", 18, -65), ("view2", 25, -20)]  # (name, elev, azim) - matches
# the matplotlib VIEWS convention (elev, azim); converted to gmsh's
# RotationX/Y below.
EDGE_COLOR = (40, 40, 40)

CASES = (["selfweight"] + [f"mode{m}" for m in range(1, 11)]
         if len(sys.argv) < 2 else [sys.argv[1]])


def elev_azim_to_gmsh_rotation(elev, azim):
    """matplotlib's (elev, azim) and gmsh's (RotationX, RotationY,
    RotationZ) don't share a convention - reuse the same RotationX/Y/Z
    triples already tuned by eye for this model's default views in
    render_partition_views.py / select_interfaces_gui.py instead of trying
    to derive an exact analytic mapping between the two."""
    presets = {
        (18, -65): (-25, 0, -25),
        (25, -20): (-35, 0, -60),
    }
    return presets.get((elev, azim), (-25, 0, -25))


gmsh.initialize()
gmsh.option.setNumber("General.GraphicsPositionX", -32000)
gmsh.option.setNumber("General.GraphicsPositionY", -32000)
gmsh.option.setNumber("General.GraphicsWidth", 50)
gmsh.option.setNumber("General.GraphicsHeight", 50)
gmsh.option.setNumber("General.Terminal", 0)
gmsh.option.setNumber("General.Trackball", 0)
gmsh.option.setNumber("General.Axes", 0)
gmsh.option.setNumber("General.SmallAxes", 0)
gmsh.option.setNumber("Mesh.SurfaceEdges", 0)
gmsh.option.setNumber("Mesh.SurfaceFaces", 0)  # actual mesh has none loaded here
gmsh.option.setNumber("Mesh.Lines", 1)
gmsh.option.setNumber("Mesh.LineWidth", 1.2)
gmsh.option.setNumber("Geometry.Points", 0)  # hide the bbox corner points themselves
gmsh.fltk.initialize()

os.makedirs(OUT_DIR, exist_ok=True)

for case in CASES:
    npz_path = f"{EXPORT_DIR}/{case}.npz"
    if not os.path.isfile(npz_path):
        print(f"SKIP {case}: {npz_path} not found")
        continue
    data = np.load(npz_path, allow_pickle=True)
    tri_verts = data["tri_verts"].astype(np.float64)   # (Ntri,3,3)
    tri_vals = data["tri_vals"].astype(np.float64)      # (Ntri,3)
    edge_verts = data["edge_verts"].astype(np.float64)  # (Nedge,2,3)
    clim = tuple(float(x) for x in data["clim"])
    title = str(data["title"])
    cbar_label = str(data["cbar_label"])
    n_tri = len(tri_verts)
    n_edge = len(edge_verts)
    print(f"{case}: {n_tri} tris, {n_edge} edges, clim={clim}")

    gmsh.model.add(case)

    # gmsh's camera auto-fit reads the MODEL's bounding box - a bare View
    # (no real geometry/mesh entity backing it) doesn't register one, which
    # left the camera at its default framing and rendered everything as a
    # near-invisible sliver in early testing. Two invisible corner points
    # (an OCC point entity, not a View) give gmsh a real bounding box to
    # fit to, at negligible cost.
    all_pts = np.vstack([tri_verts.reshape(-1, 3), edge_verts.reshape(-1, 3)])
    bbox_min = all_pts.min(axis=0)
    bbox_max = all_pts.max(axis=0)
    gmsh.model.occ.addPoint(*bbox_min)
    gmsh.model.occ.addPoint(*bbox_max)
    gmsh.model.occ.synchronize()

    # --- colored faces: View "ST" list-data ---
    coords9 = tri_verts.reshape(n_tri, 9)
    row = np.concatenate([coords9, tri_vals], axis=1)  # (Ntri, 12)
    view_tag = gmsh.view.add(f"{case}_faces")
    gmsh.view.addListData(view_tag, "ST", n_tri, row.flatten().tolist())
    gmsh.view.option.setNumber(view_tag, "RangeType", 2)  # custom
    gmsh.view.option.setNumber(view_tag, "CustomMin", clim[0])
    gmsh.view.option.setNumber(view_tag, "CustomMax", clim[1])
    gmsh.view.option.setNumber(view_tag, "ShowScale", 1)
    gmsh.view.option.setString(view_tag, "Name", cbar_label)
    gmsh.view.option.setNumber(view_tag, "IntervalsType", 3)  # continuous map

    # --- geometry edges: real discrete mesh line elements, flat color ---
    if n_edge:
        etag = gmsh.model.addDiscreteEntity(1)
        n_nodes = n_edge * 2
        node_tags = np.arange(1, n_nodes + 1)
        node_coords = edge_verts.reshape(-1, 3)
        gmsh.model.mesh.addNodes(1, etag, node_tags.tolist(),
                                  node_coords.flatten().tolist())
        elem_tags = np.arange(1, n_edge + 1)
        gmsh.model.mesh.addElements(1, etag, [1], [elem_tags.tolist()],
                                     [node_tags.tolist()])
        gmsh.model.setColor([(1, etag)], *EDGE_COLOR, 255)

    for view_name, elev, azim in VIEWS:
        rx, ry, rz = elev_azim_to_gmsh_rotation(elev, azim)
        gmsh.fltk.finalize()
        gmsh.fltk.initialize()
        gmsh.option.setNumber("Print.Width", 2000)
        gmsh.option.setNumber("Print.Height", 1700)
        gmsh.option.setNumber("General.RotationX", rx)
        gmsh.option.setNumber("General.RotationY", ry)
        gmsh.option.setNumber("General.RotationZ", rz)
        path = f"{OUT_DIR}/full_aggregate_gmsh_{case}_{view_name}.png"
        gmsh.write(path)
        print(f"  Wrote {path}")

    gmsh.view.remove(view_tag)
    gmsh.model.remove()

gmsh.fltk.finalize()
gmsh.finalize()
print("\nDone.")
