"""
Clean-style plots (no grid/background panes, no FE mesh triangulation edges,
but WITH the underlying solid geometry's edge lines - user feedback:
"non voglio ne i quadrati dietro al grafico, ne la mesh" followed by
"vedi se si possono vedere meglio le linee della geometria, anche nel self
weight") for:
  1. The self-weight deformed shape (bonded, no Task A interfaces) - reuses
     the displacement recorder from eigen_self_weight_full_aggregate_clean.py's
     own static solve (same 1.0 m mesh, single rank).
  2. The 3 most significant eigenmodes by translational (MX+MY) modal
     participation mass ratio, read from modal_properties.txt - not just
     the first 3 by eigenvalue order.

Reloads the SAME geometry/mesh (1.0 m, no partition) as
eigen_self_weight_full_aggregate_clean.py so node ordering matches its
already-written recorder files - does not re-run the analysis.

Geometry edge lines: apeGmsh's own Results.plot._facets() only returns
"tris" (the FE mesh's own triangulated boundary faces) and "segs" (1-D line
ELEMENTS, empty for this solid-only model) - drawing "segs" or the triangle
edges is exactly "the mesh" the user rejected. What she is asking for
instead is the underlying CAD wireframe (one line per solid geometric
edge - wall corners, block boundaries - the same "linee dei muri" look
from the interactive gmsh screenshots she took herself earlier), which is
a different thing: gmsh meshes every dim=1 (curve) entity too as part of
generating the volume mesh, using the SAME node ids as the volume mesh
(shared, since curves bound the surfaces of the solids) - so those curve
elements are extracted here directly (dim=1, per-entity) while the gmsh
model is still loaded, independent of fem/Results, giving one polyline per
geometric edge instead of one line per mesh-triangle edge. Because
fragment() shares topology between touching volumes (verified in
wall_interfaces.py / diagnose_mode_localization.py), each shared wall-to-
wall edge is a single curve, not duplicated - exactly a clean line drawing
of the block boundaries, at 1/10-1/100th the density of the mesh
triangulation.

Both the self-weight and mode-shape plots are now built by hand (Poly3D-
Collection for the colored, edge-less faces + Line3DCollection for the
geometry edges) rather than through apeGmsh's results.plot.deformed()
wrapper, which has no hook for a separate geometry-edge overlay.
"""
import math
import os
import shutil
import sys
import time

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import numpy as np
import gmsh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib import cm
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_clean"
EIGEN_DIR = "output/castelnuovo/recorders_full_aggregate_clean_eigen"
GLOBAL_MESH_SIZE = 1.0
N_MODES = 10
DEFORM_SCALE_SELFWEIGHT = 200.0
MAX_MODE_DISPLACEMENT_M = 2.0  # visual target - eigenvectors have no physical scale
VIEWS = [(18, -65), (25, -20)]  # (elev, azim) pairs - 2 views per plot
GEOM_EDGE_COLOR = "#2b2b2b"
GEOM_EDGE_LINEWIDTH = 0.6

with apeGmsh(model_name="plot_eigen_clean") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    g.parts.from_model("plot_eigen_clean")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    # --- Geometry (CAD) edge wireframe: one polyline per dim=1 curve
    # entity, in fem node-id space (shared nodes with the volume mesh). ---
    id_to_row = {int(nid): i for i, nid in enumerate(fem.nodes.ids)}
    edge_pairs = set()
    for _dim, curve_tag in gmsh.model.getEntities(1):
        etypes, _etags, enodes_list = gmsh.model.mesh.getElements(dim=1, tag=curve_tag)
        for etype, enode_arr in zip(etypes, enodes_list):
            _name, _edim, _order, n_per_elem, _, _ = gmsh.model.mesh.getElementProperties(etype)
            arr = np.asarray(enode_arr, dtype=np.int64).reshape(-1, n_per_elem)
            for row in arr:
                for a, b in zip(row[:-1], row[1:]):
                    a, b = int(a), int(b)
                    if a in id_to_row and b in id_to_row:
                        edge_pairs.add((a, b) if a < b else (b, a))
    geom_edge_rows = np.array(
        [[id_to_row[a], id_to_row[b]] for a, b in edge_pairs], dtype=np.int64
    )
    print(f"Geometry wireframe: {len(geom_edge_rows)} CAD edge segments "
          f"(from {len(list(gmsh.model.getEntities(1)))} curve entities) - "
          f"for comparison, the FE surface mesh has many times more "
          f"triangle edges.")

    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)

    results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
    tris, segs, lookup, coords = results.plot._facets()
    selfweight_uz = results.plot._read_node_scalars("displacement_z", step=-1, stage=None)
    selfweight_disp = np.column_stack([
        results.plot._read_node_scalars(c, step=-1, stage=None)
        for c in ("displacement_x", "displacement_y", "displacement_z")
    ])
    selfweight_deformed_coords = coords + DEFORM_SCALE_SELFWEIGHT * selfweight_disp
    print(f"facets: coords {coords.shape}")


def clean_axes(ax):
    """No grid/background panes, no ticks - just the model + colorbar."""
    ax.set_axis_off()


def add_geometry_edges(ax, deformed_coords, linewidth=GEOM_EDGE_LINEWIDTH):
    if geom_edge_rows.size == 0:
        return
    seg_verts = deformed_coords[geom_edge_rows]
    ax.add_collection3d(Line3DCollection(
        seg_verts, colors=GEOM_EDGE_COLOR, linewidths=linewidth,
    ))


def save_views(fig_builder, name_prefix, caption_title):
    """fig_builder() -> Axes3D (freshly built each call, since view_init +
    axis limits interact awkwardly with reusing one figure across angles).
    Saves one PNG per (elev, azim) in VIEWS.

    Saves to a local (non-bind-mounted) temp path first, then copies to the
    bind-mounted output/ path with a short retry: writing directly to the
    Windows bind mount intermittently raised
    "OSError: [Errno 22] Invalid argument" on an otherwise-fine path
    (different file each run, no pattern found - looks like a transient
    host-side lock, not a bug in this script) - the copy+retry rides it
    out instead of failing the whole run over one flaky write.
    """
    paths = []
    for i, (elev, azim) in enumerate(VIEWS, start=1):
        ax = fig_builder()
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(caption_title, fontsize=10)
        clean_axes(ax)
        path = f"output/castelnuovo/plots/{name_prefix}_view{i}.png"
        tmp_path = f"/tmp/{name_prefix}_view{i}.png"
        ax.figure.savefig(tmp_path, dpi=200, bbox_inches="tight")
        plt.close(ax.figure)
        last_err = None
        for _attempt in range(5):
            try:
                shutil.copyfile(tmp_path, path)
                last_err = None
                break
            except OSError as e:
                last_err = e
                time.sleep(1.0)
        if last_err is not None:
            raise last_err
        paths.append(path)
        print(f"Wrote {path}")
    return paths


def build_colored_ax(deformed_coords, face_scalar, cmap_name, cbar_label,
                      clim=None):
    """Shared plot builder: flat color-by-scalar faces (no per-face edges,
    matches the mode-shape style) + the CAD geometry-edge overlay."""
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(111, projection="3d")
    mappable = None
    if tris.size:
        face_idx = lookup[tris]
        verts = deformed_coords[face_idx]
        face_vals = face_scalar[face_idx].mean(axis=1)
        if clim is None:
            lo, hi = float(face_vals.min()), float(face_vals.max())
            if lo == hi:
                hi = lo + 1.0
        else:
            lo, hi = clim
        norm = Normalize(vmin=lo, vmax=hi)
        face_colors = matplotlib.colormaps[cmap_name](norm(face_vals))
        poly = Poly3DCollection(verts, edgecolor="none")
        poly.set_facecolor(face_colors)
        ax.add_collection3d(poly)
        mappable = cm.ScalarMappable(norm=norm, cmap=cmap_name)
        mappable.set_array(face_vals)
    add_geometry_edges(ax, deformed_coords)
    all_pts = np.vstack([coords, deformed_coords])
    mins, maxs = all_pts.min(axis=0), all_pts.max(axis=0)
    ax.set_xlim(mins[0], maxs[0])
    ax.set_ylim(mins[1], maxs[1])
    ax.set_zlim(mins[2], maxs[2])
    try:
        ax.set_box_aspect((maxs - mins))
    except Exception:
        pass
    if mappable is not None:
        cbar = fig.colorbar(mappable, ax=ax, shrink=0.6, pad=0.02)
        cbar.set_label(cbar_label, fontsize=9)
        cbar.ax.tick_params(labelsize=8)
    return ax


# --- 1. Self-weight deformed shape, clean style, geometry edges on -------
def build_selfweight_ax():
    return build_colored_ax(
        selfweight_deformed_coords, selfweight_uz, "Blues",
        "displacement_z (m)",
    )


save_views(build_selfweight_ax, "full_aggregate_clean_selfweight_CLEAN",
           f"Self-weight, bonded - deformed x{DEFORM_SCALE_SELFWEIGHT:g}")


# --- 2. Parse modal_properties.txt for participation mass ratios, pick the
# 3 most significant modes by MX + MY (translational, most relevant). ---
with open(f"{EIGEN_DIR}/modal_properties.txt") as f:
    modal_txt = f.read()

# The (non-cumulative) "9. MODAL PARTICIPATION MASS RATIOS (%)" table -
# stop at the next "* 10." section header.
section = modal_txt.split("9. MODAL PARTICIPATION MASS RATIOS")[1]
section = section.split("* 10.")[0]
rows = []
for line in section.splitlines():
    parts = line.split()
    if len(parts) == 7 and parts[0].isdigit():
        mode, mx, my, mz, rmx, rmy, rmz = parts
        rows.append((int(mode), float(mx), float(my)))
rows.sort(key=lambda r: -(r[1] + r[2]))
top_modes = [r[0] for r in rows[:3]]
print(f"Most significant modes by MX+MY participation: {top_modes}")
print("(mode, MX%, MY%) ranking:", rows[:5])

with open(f"{EIGEN_DIR}/eigenvalues.txt") as f:
    eigenvalues = [float(x) for x in f.read().split()]


def parse_eigenvector_file(path, n_nodes):
    # NOTE: unlike the static displacement/reaction recorders (written with
    # "-time"), the eigen-mode recorders in eigen_self_weight_full_aggregate_
    # clean.py were written WITHOUT "-time" - so this file has no leading
    # pseudo-time value, just 3*n_nodes displacement components directly
    # (verified: file has exactly 3*n_nodes fields, not 3*n_nodes+1).
    with open(path) as f:
        last_line = f.readlines()[-1]
    vals = np.array([float(x) for x in last_line.split()])
    return vals.reshape(n_nodes, 3)


# --- 3. Mode shape plots: faces colored by relative modal displacement
# magnitude (same "contour" idea as the self-weight plot) + the geometry
# edge wireframe so individual blocks/walls stay legible. ---
for mode in top_modes:
    mode_disp = parse_eigenvector_file(f"{EIGEN_DIR}/mode{mode}_eigenvector.out", len(fem.nodes.ids))
    node_mag = np.linalg.norm(mode_disp, axis=1)
    max_mag = node_mag.max()
    scale = MAX_MODE_DISPLACEMENT_M / max_mag if max_mag > 0 else 1.0
    deformed_coords = coords + scale * mode_disp
    rel_mag = node_mag / max_mag if max_mag > 0 else node_mag  # 0..1, relative to this mode's own peak

    T = 2 * math.pi / math.sqrt(eigenvalues[mode - 1])
    freq = 1.0 / T

    def build_mode_ax(deformed_coords=deformed_coords, rel_mag=rel_mag):
        return build_colored_ax(
            deformed_coords, rel_mag, "viridis", "relative modal displacement",
            clim=(0.0, 1.0),
        )

    save_views(
        build_mode_ax, f"full_aggregate_clean_mode{mode}_CLEAN",
        f"Mode {mode} - T={T:.3f}s, f={freq:.3f}Hz",
    )

print("\nDone.")
