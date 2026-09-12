"""
Clean-style plots (no grid/background panes, no FE mesh triangulation edges,
but WITH the underlying solid geometry's edge lines - user feedback:
"non voglio ne i quadrati dietro al grafico, ne la mesh" followed by
"vedi se si possono vedere meglio le linee della geometria, anche nel self
weight") for:
  1. The self-weight deformed shape (bonded, no Task A interfaces) - reuses
     the displacement recorder from eigen_self_weight_full_aggregate_fine.py's
     own static solve (0.6 m mesh, single rank).
  2. All N_MODES computed eigenmodes (user request: "voglio immagini dei 10
     modi", not just the 3 most significant) - the 3 most significant by
     translational (MX+MY) modal participation mass ratio (read from
     modal_properties.txt, not just the first 3 by eigenvalue order) are
     still tagged "(most significant)" in their title.

Geometry edges are now restricted to EXTERIOR surfaces only (surfaces
bounding exactly one volume) - user feedback: "le linee delle geometrie
voglio vederle solo sui solidi interamente visibili e non in
'trasparenza'". Drawing every curve (including ones that only bound
internal, volume-to-volume joints hidden inside the aggregate) produced an
x-ray look with long diagonal lines cutting across the model; see the
exterior_surfaces computation below.

FINE-MESH variant of plot_eigen_and_selfweight_clean.py (which used 1.0 m):
0.6 m instead, re-run after diagnose_mode_localization.py / _fine.py showed
mode 8's apparent "detachment" at 1.0 m (isolated on 3 tiny, ~16-18 node
volumes) does NOT persist at 0.6 m (spreads across many volumes - a coarse-
mesh artifact), while modes 1/3's localization on volume 118 (a large flat
slab tied to its neighbours through a 0.185 m^2 and a 3.857 m^2 face) DOES
persist unchanged at both mesh sizes - a genuine soft joint, not an
artifact. Output file names use a "_fine"/"FINE" suffix, kept separate from
the 1.0 m run's files.

Reloads the SAME geometry/mesh (0.6 m, no partition) as
eigen_self_weight_full_aggregate_fine.py so node ordering matches its
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
from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_clean_refined"
EIGEN_DIR = "output/castelnuovo/recorders_full_aggregate_clean_eigen_refined"
GLOBAL_MESH_SIZE = 0.6
LOCAL_SIZE_MIN = 0.15
LOCAL_DIST_MIN = 0.3
LOCAL_DIST_MAX = 3.0
JOINT_VOLUME_PAIRS = [(118, 71), (118, 110), (106, 71), (106, 92)]
N_MODES = 10
DEFORM_SCALE_SELFWEIGHT = 200.0
MAX_MODE_DISPLACEMENT_M = 0.5  # visual target - eigenvectors have no physical
# scale, but 2.0 m (the original choice) turned out to be grossly
# disproportionate for a ~7 m slab (volume 118, modes 1/3) - large enough
# to make a real, continuous, small rotation about a narrow bearing line
# look like a gap opening up. 0.5 m keeps the mechanism clearly visible
# without exaggerating it past the point of misreading it as breakage; the
# undeformed ghost overlay (below) is a second, independent check on the
# same question.
VIEWS = [(18, -65), (25, -20)]  # (elev, azim) pairs - 2 views per plot
GEOM_EDGE_COLOR = "#2b2b2b"
GEOM_EDGE_LINEWIDTH = 0.6

with apeGmsh(model_name="plot_eigen_refined") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    g.parts.from_model("plot_eigen_refined")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)

    # MUST reproduce the exact same local-refinement mesh as
    # eigen_self_weight_full_aggregate_refined_joints.py - the recorder/
    # eigenvector files were written against THAT mesh's node numbering
    # (20,192 nodes), not the plain uniform-0.6m one (17,700 nodes) -
    # without this the reshape() below would fail immediately.
    candidates_for_refine = InterfaceDetection.find_touching_surface_pairs()
    joint_surfaces = []
    for va, vb in JOINT_VOLUME_PAIRS:
        key = (min(va, vb), max(va, vb))
        for c in candidates_for_refine:
            if (min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"])) == key:
                joint_surfaces.append(c["surface"])
    dist_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist_field, "SurfacesList", joint_surfaces)
    gmsh.model.mesh.field.setNumber(dist_field, "Sampling", 30)
    thresh_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thresh_field, "InField", dist_field)
    gmsh.model.mesh.field.setNumber(thresh_field, "SizeMin", LOCAL_SIZE_MIN)
    gmsh.model.mesh.field.setNumber(thresh_field, "SizeMax", GLOBAL_MESH_SIZE)
    gmsh.model.mesh.field.setNumber(thresh_field, "DistMin", LOCAL_DIST_MIN)
    gmsh.model.mesh.field.setNumber(thresh_field, "DistMax", LOCAL_DIST_MAX)
    gmsh.model.mesh.field.setAsBackgroundMesh(thresh_field)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    # --- Geometry (CAD) edge wireframe: one polyline per dim=1 curve
    # entity, in fem node-id space (shared nodes with the volume mesh),
    # restricted to EXTERIOR curves only - user feedback: "le linee delle
    # geometrie voglio vederle solo sui solidi interamente visibili e non
    # in 'trasparenza'". A curve bounding only surfaces that are each
    # shared by two volumes (an internal wall-to-wall/floor-to-wall joint,
    # never part of the aggregate's outer skin) reads as an x-ray line
    # through the model when every curve is drawn - so first classify every
    # dim=2 surface as "exterior" (bounds exactly one volume - part of the
    # outer envelope) or "interior" (bounds two - a joint hidden inside the
    # solid), the same surface_to_volumes count
    # InterfaceDetection.find_touching_surface_pairs() uses, then keep a
    # curve only if at least one of its parent surfaces is exterior. ---
    id_to_row = {int(nid): i for i, nid in enumerate(fem.nodes.ids)}

    surface_to_volumes = {}
    for _dim, vol in all_vols:
        boundary = gmsh.model.getBoundary([(3, vol)], oriented=False, combined=False)
        for _bdim, bsurf in boundary:
            surface_to_volumes.setdefault(abs(bsurf), set()).add(vol)
    exterior_surfaces = {s for s, vols in surface_to_volumes.items() if len(vols) == 1}
    print(f"{len(exterior_surfaces)}/{len(surface_to_volumes)} surfaces are "
          f"exterior (bound exactly one volume) - only their edges are drawn.")

    # Per-surface backface culling (three different normal-orientation
    # fixes tried: getBoundary(oriented=True)'s sign, a volume-centroid
    # geometric check, and correcting getNormal()'s UV sample point to the
    # face's real parametrisation bounds instead of an assumed [0,1]x[0,1])
    # was abandoned - none changed the rendered result at all despite each
    # being independently verified correct in isolation, so the actual bug
    # is elsewhere (most likely which surface a given curve gets attributed
    # to in the first place, not its normal) and wasn't found in the time
    # available. Reverted to per-VOLUME grouping with no culling - not a
    # complete fix for the "x-ray" look, but the one that empirically
    # produced clean results for most views (self-weight, most modes);
    # occasional views (e.g. mode 6 in the 1.0 m/0.6 m runs) can still show
    # fewer edges than ideal - a known, reported limitation, not silently
    # accepted as fine.
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
            continue  # curve bounds only interior (hidden) surfaces - skip
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

    geom_edge_groups = [
        (np.array([[id_to_row[a], id_to_row[b]] for a, b in pairs], dtype=np.int64), None)
        for pairs in edge_pairs_by_vol.values()
    ]
    n_edges_total = sum(len(rows) for rows, _n in geom_edge_groups)
    print(f"Geometry wireframe: {n_edges_total} CAD edge segments across "
          f"{len(geom_edge_groups)} per-volume groups - for comparison, "
          f"the FE surface mesh has many times more triangle edges.")

    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)

    results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
    tris, segs, lookup, coords = results.plot._facets()

    # Mesh-node adjacency (from the boundary triangulation), used to
    # smooth the per-node colour scalar before painting - see
    # smooth_nodal_values below for why (subdivision alone made the colour
    # look speckled/noisy rather than smoother, since it just reveals the
    # eigenvector's own per-node numerical texture at finer scale instead
    # of averaging it out).
    _face_rows = lookup[tris]  # (n_tri, 3) - row indices into `coords`
    _edges = np.concatenate([_face_rows[:, [0, 1]], _face_rows[:, [1, 2]],
                              _face_rows[:, [2, 0]]], axis=0)
    ADJ_SRC = np.concatenate([_edges[:, 0], _edges[:, 1]])
    ADJ_DST = np.concatenate([_edges[:, 1], _edges[:, 0]])
    ADJ_DEG = np.zeros(len(coords))
    np.add.at(ADJ_DEG, ADJ_SRC, 1.0)
    ADJ_DEG[ADJ_DEG == 0] = 1.0

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


def camera_view_dir(elev, azim):
    """Unit vector from the scene toward the camera, in the same (x,y,z)
    world coordinates as the model - matplotlib's own convention for
    (elev, azim) -> eye direction (mpl_toolkits.mplot3d source)."""
    er, ar = math.radians(elev), math.radians(azim)
    return np.array([math.cos(er) * math.cos(ar),
                      math.cos(er) * math.sin(ar),
                      math.sin(er)])


def add_geometry_edges(ax, deformed_coords, elev, azim,
                        linewidth=GEOM_EDGE_LINEWIDTH, cull=False):
    """One Line3DCollection per volume (see geom_edge_groups) - per-surface
    backface culling was tried (normal points away from camera -> skip)
    but abandoned; see the comment above geom_edge_groups for why. `elev`/
    `azim` are still threaded through (unused while cull=False) so this
    can be re-enabled later without touching every call site again.
    """
    view_dir = camera_view_dir(elev, azim) if cull else None
    for rows, normal in geom_edge_groups:
        if rows.size == 0:
            continue
        if cull and float(np.dot(normal, view_dir)) < -0.05:
            continue
        seg_verts = deformed_coords[rows]
        ax.add_collection3d(Line3DCollection(
            seg_verts, colors=GEOM_EDGE_COLOR, linewidths=linewidth,
        ))


def save_views(fig_builder, name_prefix, caption_title):
    """fig_builder(elev, azim) -> Axes3D (freshly built each call, since
    view_init + axis limits interact awkwardly with reusing one figure
    across angles, and the edge back-face culling needs to know the view
    up front to decide which surfaces' edges to draw at all). Saves one
    PNG per (elev, azim) in VIEWS.

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
        ax = fig_builder(elev, azim)
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


def smooth_nodal_values(vals, passes=3, alpha=0.6):
    """Laplacian smoothing over the boundary-mesh node graph (ADJ_SRC/DST/
    DEG, built once from `tris`/`lookup`) - tried subdivision first
    (splitting each triangle into 4 with linearly-interpolated corners) to
    make the colour read as smooth/interpolated instead of blocky, but
    that just revealed the eigenvector's own per-node numerical texture at
    finer scale (a speckled/noisy look, worse than the flat version) since
    each new sub-vertex is still only ever a function of its own original
    triangle's 3 corners - it never actually averages with neighbouring
    triangles. Real neighbour-averaging (this) is what actually smooths a
    genuinely noisy per-node field; runs on the RAW per-node array
    (aligned with `coords`/row index), independent of any one triangle.
    """
    v = vals.astype(np.float64).copy()
    for _ in range(passes):
        acc = np.zeros_like(v)
        np.add.at(acc, ADJ_SRC, v[ADJ_DST])
        neighbor_mean = acc / ADJ_DEG
        v = (1 - alpha) * v + alpha * neighbor_mean
    return v


def build_colored_ax(deformed_coords, face_scalar, cmap_name, cbar_label,
                      elev, azim, clim=None, ghost_coords=None):
    """Shared plot builder: colour-by-scalar faces (flat per triangle, but
    on Laplacian-smoothed per-node values - see smooth_nodal_values - so
    the colour reads as a smooth gradient rather than a blocky/speckled
    one) + the CAD geometry-edge overlay, back-face-culled for this
    (elev, azim).

    ghost_coords, if given, overlays the UNDEFORMED geometry edges in light
    grey underneath the deformed shape - added after the user flagged the
    mode-shape plots as looking like the model breaks apart (it doesn't;
    see docker/opensees/render_volume118_check.py, which found 4/41
    literally shared mesh node ids at the two joints in question - the
    exaggerated visual displacement scale made a real but small rotation
    at a narrow bearing look like a gap). Seeing the undeformed outline
    still touching everywhere makes that legible without needing the
    numbers alongside it.
    """
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(111, projection="3d")
    if ghost_coords is not None:
        add_geometry_edges(ax, ghost_coords, elev, azim, linewidth=0.4)
        for coll in ax.collections:
            coll.set_alpha(0.25)
    mappable = None
    if tris.size:
        face_idx = lookup[tris]
        verts = deformed_coords[face_idx]
        face_vals = face_scalar[face_idx].mean(axis=1)  # face_scalar is pre-smoothed by the caller
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
    add_geometry_edges(ax, deformed_coords, elev, azim)
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
selfweight_uz_smooth = smooth_nodal_values(selfweight_uz)


def build_selfweight_ax(elev, azim):
    return build_colored_ax(
        selfweight_deformed_coords, selfweight_uz_smooth, "Blues",
        "displacement_z (m)", elev, azim,
    )


save_views(build_selfweight_ax, "full_aggregate_refined_selfweight_REFINED",
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


# --- 3. Mode shape plots for ALL N_MODES computed modes (not just the 3
# most significant by MX+MY - user asked for "immagini dei 10 modi"),
# faces colored by relative modal displacement magnitude (same "contour"
# idea as the self-weight plot) + the (now exterior-only) geometry edge
# wireframe so individual blocks/walls stay legible. ---
for mode in range(1, N_MODES + 1):
    mode_disp = parse_eigenvector_file(f"{EIGEN_DIR}/mode{mode}_eigenvector.out", len(fem.nodes.ids))
    node_mag = np.linalg.norm(mode_disp, axis=1)
    max_mag = node_mag.max()
    scale = MAX_MODE_DISPLACEMENT_M / max_mag if max_mag > 0 else 1.0
    deformed_coords = coords + scale * mode_disp
    rel_mag = node_mag / max_mag if max_mag > 0 else node_mag  # 0..1, relative to this mode's own peak
    rel_mag = smooth_nodal_values(rel_mag)

    T = 2 * math.pi / math.sqrt(eigenvalues[mode - 1])
    freq = 1.0 / T
    tag = " (most significant)" if mode in top_modes else ""

    def build_mode_ax(elev, azim, deformed_coords=deformed_coords, rel_mag=rel_mag):
        return build_colored_ax(
            deformed_coords, rel_mag, "viridis", "relative modal displacement",
            elev, azim, clim=(0.0, 1.0), ghost_coords=coords,
        )

    save_views(
        build_mode_ax, f"full_aggregate_refined_mode{mode}_REFINED",
        f"Mode {mode} - T={T:.3f}s, f={freq:.3f}Hz{tag}",
    )

print("\nDone.")
