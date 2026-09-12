"""
Clean-style plots (colour-by-scalar faces on Laplacian-smoothed nodal
values, CAD geometry-edge wireframe grouped per volume, no grid/background
panes) for the self-weight + all-modes results
docker/opensees/eigen_castelnuovo_native_gmsh.py wrote - same visual style
as docker/opensees/plot_eigen_and_selfweight_refined.py (the apeGmsh/TCL
pipeline's plot script), adapted to this run's plain-text output instead of
apeGmsh's Results/Recorders wrapper:
  - node_coords.txt / mode<k>_eigenvector.txt / selfweight_displacement.txt
    are "node_id,x,y,z" plain CSV, not TCL recorder files - no apeGmsh
    Results object at all here, since the native script never built one.
  - Boundary/geometry-edge extraction re-meshes the SAME STEP at the SAME
    settings the eigen script used (0.6 m global, no local joint
    refinement - the native run doesn't have that, see the eigen script's
    docstring) to get a live gmsh session to query surfaces/curves from;
    node ordering must then be re-sorted the same way
    (node_tags_sorted = sorted(...)) to align with the eigenvector files,
    which were written in that same sorted order.

Run in Docker (needs the full repo mounted, like the eigen script - core/,
external/, utils/, not just docker/opensees/).
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

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
DATA_DIR = "output/castelnuovo/recorders_castelnuovo_native"
GLOBAL_MESH_SIZE = 0.6
N_MODES = 10
DEFORM_SCALE_SELFWEIGHT = 200.0
MAX_MODE_DISPLACEMENT_M = 0.5
VIEWS = [(18, -65), (25, -20)]
GEOM_EDGE_COLOR = "#2b2b2b"
GEOM_EDGE_LINEWIDTH = 0.6
IMG_PREFIX = "full_aggregate_native"
IMG_SUFFIX = "NATIVE"

# --- 1. Re-mesh (same settings as eigen_castelnuovo_native_gmsh.py) to get
# a live gmsh session for surface/curve queries. ---
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("plot_castelnuovo_native")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
all_vols = gmsh.model.getEntities(3)
vol_tags = [t for _, t in all_vols]
pg_tag = gmsh.model.addPhysicalGroup(3, vol_tags)
gmsh.model.setPhysicalName(3, pg_tag, "Masonry")
gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)
gmsh.model.mesh.generate(3)

all_node_tags, all_node_coords, _ = gmsh.model.mesh.getNodes()
node_tags_sorted = np.array(sorted(int(t) for t in all_node_tags), dtype=np.int64)
id_to_row = {int(nid): i for i, nid in enumerate(node_tags_sorted)}
n_nodes = len(node_tags_sorted)
print(f"Mesh: {n_nodes} nodes")

# --- Boundary triangles for the coloured surface: every triangle on every
# EXTERIOR surface (bounds exactly one volume). ---
surface_to_volumes = {}
for vol in vol_tags:
    boundary = gmsh.model.getBoundary([(3, vol)], oriented=False, combined=False)
    for _bdim, bsurf in boundary:
        surface_to_volumes.setdefault(abs(bsurf), set()).add(vol)
exterior_surfaces = {s for s, vols in surface_to_volumes.items() if len(vols) == 1}

tri_rows = []
for surf in exterior_surfaces:
    etypes, _etags, enodes_list = gmsh.model.mesh.getElements(dim=2, tag=surf)
    for etype, enode_arr in zip(etypes, enodes_list):
        _name, _edim, _order, n_per_elem, _, _ = gmsh.model.mesh.getElementProperties(etype)
        if n_per_elem != 3:
            continue
        arr = np.asarray(enode_arr, dtype=np.int64).reshape(-1, 3)
        for a, b, c in arr:
            if a in id_to_row and b in id_to_row and c in id_to_row:
                tri_rows.append([id_to_row[a], id_to_row[b], id_to_row[c]])
tri_rows = np.array(tri_rows, dtype=np.int64)
print(f"{len(tri_rows)} boundary triangles on {len(exterior_surfaces)} exterior surfaces")

# --- Geometry edges, grouped per volume (see plot_eigen_and_selfweight_
# refined.py's comment on why per-surface backface culling was abandoned -
# same reasoning applies here, so this reuses the per-volume, no-culling
# approach that empirically works for most views). ---
edge_pairs_by_vol = {}
for _dim, curve_tag in gmsh.model.getEntities(1):
    upward, _downward = gmsh.model.getAdjacencies(1, curve_tag)
    owning_vol = None
    for s in upward:
        vols = surface_to_volumes.get(abs(s), set())
        if len(vols) == 1:
            owning_vol = next(iter(vols))
            break
    if owning_vol is None:
        continue
    etypes, _etags, enodes_list = gmsh.model.mesh.getElements(dim=1, tag=curve_tag)
    for etype, enode_arr in zip(etypes, enodes_list):
        _name, _edim, _order, n_per_elem, _, _ = gmsh.model.mesh.getElementProperties(etype)
        arr = np.asarray(enode_arr, dtype=np.int64).reshape(-1, n_per_elem)
        for row in arr:
            for a, b in zip(row[:-1], row[1:]):
                a, b = int(a), int(b)
                if a in id_to_row and b in id_to_row:
                    pair = (a, b) if a < b else (b, a)
                    edge_pairs_by_vol.setdefault(owning_vol, set()).add(pair)

geom_edge_row_groups = [
    np.array([[id_to_row[a], id_to_row[b]] for a, b in pairs], dtype=np.int64)
    for pairs in edge_pairs_by_vol.values()
]
n_edges_total = sum(len(g) for g in geom_edge_row_groups)
print(f"{n_edges_total} geometry edges across {len(geom_edge_row_groups)} per-volume groups")

gmsh.finalize()

# --- Mesh-node adjacency (from tri_rows), for Laplacian smoothing. --------
_edges = np.concatenate([tri_rows[:, [0, 1]], tri_rows[:, [1, 2]], tri_rows[:, [2, 0]]], axis=0)
ADJ_SRC = np.concatenate([_edges[:, 0], _edges[:, 1]])
ADJ_DST = np.concatenate([_edges[:, 1], _edges[:, 0]])
ADJ_DEG = np.zeros(n_nodes)
np.add.at(ADJ_DEG, ADJ_SRC, 1.0)
ADJ_DEG[ADJ_DEG == 0] = 1.0


def smooth_nodal_values(vals, passes=3, alpha=0.6):
    v = vals.astype(np.float64).copy()
    for _ in range(passes):
        acc = np.zeros_like(v)
        np.add.at(acc, ADJ_SRC, v[ADJ_DST])
        v = (1 - alpha) * v + alpha * (acc / ADJ_DEG)
    return v


def _parse_float(s):
    """The writer used repr() (f"{x!r}") on numpy float64 scalars, which
    on numpy>=2.0 renders as "np.float64(1.23)" instead of a plain number
    - strip that wrapper here rather than re-running the (expensive) eigen
    analysis just to fix the write side's formatting."""
    s = s.strip()
    if s.startswith("np.float64(") and s.endswith(")"):
        s = s[len("np.float64("):-1]
    return float(s)


def load_disp_file(path, n_nodes):
    """node_id,x,y,z CSV (from get_displacements_at_nodes/get_eigenvector_
    at_nodes, written in node_tags_sorted order) -> (n_nodes,3) array,
    re-validated against node_tags_sorted (not just trusted positionally)."""
    ids, vals = [], []
    with open(path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 4:
                continue
            ids.append(int(parts[0]))
            vals.append([_parse_float(parts[1]), _parse_float(parts[2]), _parse_float(parts[3])])
    ids = np.array(ids, dtype=np.int64)
    vals = np.array(vals, dtype=np.float64)
    assert np.array_equal(ids, node_tags_sorted), (
        f"{path}: node id order does not match node_tags_sorted - "
        f"re-meshing here did not reproduce the eigen script's mesh."
    )
    return vals


def load_coords_file(path):
    return load_disp_file(path, n_nodes)


coords = load_coords_file(f"{DATA_DIR}/node_coords.txt")


def clean_axes(ax):
    ax.set_axis_off()


def add_geometry_edges(ax, deformed_coords, linewidth=GEOM_EDGE_LINEWIDTH):
    for rows in geom_edge_row_groups:
        if rows.size == 0:
            continue
        seg_verts = deformed_coords[rows]
        ax.add_collection3d(Line3DCollection(
            seg_verts, colors=GEOM_EDGE_COLOR, linewidths=linewidth,
        ))


def save_views(fig_builder, name_prefix, caption_title):
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


def build_colored_ax(deformed_coords, face_scalar, cmap_name, cbar_label, clim=None, ghost_coords=None):
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(111, projection="3d")
    if ghost_coords is not None:
        add_geometry_edges(ax, ghost_coords, linewidth=0.4)
        for coll in ax.collections:
            coll.set_alpha(0.25)
    mappable = None
    if tri_rows.size:
        verts = deformed_coords[tri_rows]
        face_vals = face_scalar[tri_rows].mean(axis=1)
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


# --- 1. Self-weight ---------------------------------------------------------
selfweight_disp = load_disp_file(f"{DATA_DIR}/selfweight_displacement.txt", n_nodes)
selfweight_deformed = coords + DEFORM_SCALE_SELFWEIGHT * selfweight_disp
selfweight_uz_smooth = smooth_nodal_values(selfweight_disp[:, 2])


def build_selfweight_ax():
    return build_colored_ax(selfweight_deformed, selfweight_uz_smooth, "Blues", "displacement_z (m)")


save_views(build_selfweight_ax, f"{IMG_PREFIX}_selfweight_{IMG_SUFFIX}",
           f"Self-weight, native gmsh+openseespy - deformed x{DEFORM_SCALE_SELFWEIGHT:g}")

# --- 2. Modes ---------------------------------------------------------------
with open(f"{DATA_DIR}/modal_properties.txt") as f:
    modal_txt = f.read()
section = modal_txt.split("9. MODAL PARTICIPATION MASS RATIOS")[1].split("* 10.")[0]
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

with open(f"{DATA_DIR}/eigenvalues.txt") as f:
    eigenvalues = [float(x) for x in f.read().split()]

for mode in range(1, N_MODES + 1):
    mode_disp = load_disp_file(f"{DATA_DIR}/mode{mode}_eigenvector.txt", n_nodes)
    node_mag = np.linalg.norm(mode_disp, axis=1)
    max_mag = node_mag.max()
    scale = MAX_MODE_DISPLACEMENT_M / max_mag if max_mag > 0 else 1.0
    deformed_coords = coords + scale * mode_disp
    rel_mag = node_mag / max_mag if max_mag > 0 else node_mag
    rel_mag = smooth_nodal_values(rel_mag)

    T = 2 * math.pi / math.sqrt(eigenvalues[mode - 1])
    freq = 1.0 / T
    tag = " (most significant)" if mode in top_modes else ""

    def build_mode_ax(deformed_coords=deformed_coords, rel_mag=rel_mag):
        return build_colored_ax(deformed_coords, rel_mag, "viridis",
                                 "relative modal displacement",
                                 clim=(0.0, 1.0), ghost_coords=coords)

    save_views(build_mode_ax, f"{IMG_PREFIX}_mode{mode}_{IMG_SUFFIX}",
               f"Mode {mode} - T={T:.3f}s, f={freq:.3f}Hz{tag}")

print("\nDone.")
