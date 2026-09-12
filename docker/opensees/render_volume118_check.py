"""
Direct visual check of the user's pushback: "le geometrie sembrano
sbagliate, sono staccate invece che continue" - is volume 118 (the volume
diagnose_mode_localization.py / _fine.py attributed modes 1/3's localized
displacement to) actually touching its neighbours in the UNDEFORMED model,
or is this a real gap in the source geometry?

Renders the UNDEFORMED (scale=0) aggregate with volume 118 highlighted in
red and its two candidate neighbours (71, 110 - from the earlier
diagnostic's touching-surface search) highlighted in orange, everything
else light grey, with the CAD geometry-edge wireframe on top, at 2 views:
one of the whole aggregate (context) and one zoomed into just that region.

This does NOT touch the deformed mode-shape rendering at all - it is a
narrower, more basic question (does this solid actually touch its
neighbours in the original, unmodified geometry) that has to be settled
before trusting any deformed-shape interpretation.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import gmsh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
GLOBAL_MESH_SIZE = 0.6
TARGET_VOL = 118
NEIGHBOR_VOLS = (71, 110)

with apeGmsh(model_name="render_volume118_check") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    joint_centroids = {}  # other_vol -> centroid of the shared face
    for c in candidates:
        if TARGET_VOL in (c["volume_a"], c["volume_b"]):
            other = c["volume_b"] if c["volume_a"] == TARGET_VOL else c["volume_a"]
            print(f"  candidate touch: vol {TARGET_VOL} <-> vol {other}, "
                  f"area={c['area_m2']:.4f} m^2, centroid={c['centroid']}, "
                  f"orientation={c.get('orientation')}")
            if other in NEIGHBOR_VOLS:
                joint_centroids[other] = np.array(c["centroid"], dtype=np.float64)

    g.parts.from_model("render_volume118_check")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    id_to_row = {int(nid): i for i, nid in enumerate(fem.nodes.ids)}

    # Per-element -> volume tag, so we can color faces by which volume they
    # belong to (surface triangles alone don't carry that).
    elem_to_vol = {}
    vol_node_ids = {}
    for _dim, vol in all_vols:
        _etypes, etags, enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
        if not etags or len(etags[0]) == 0:
            continue
        for et in etags[0]:
            elem_to_vol[int(et)] = vol
        vol_node_ids[vol] = set(int(n) for n in enodes[0]) if enodes and len(enodes[0]) else set()

    # --- Numeric proof, independent of any rendering: are there mesh nodes
    # literally shared (same node id, appearing in BOTH volumes' own
    # tetrahedra) between volume 118 and each neighbour? No node-splitting
    # is applied anywhere in this bonded (no Task A interfaces) model - see
    # eigen_self_weight_full_aggregate_fine.py's solid_elements() call,
    # which passes no node_substitution/split_element_ids - so if such
    # shared nodes exist, volume 118's own tetrahedra and volume 110's/71's
    # own tetrahedra reference the EXACT SAME row in the stiffness matrix
    # there: not "two coincident points", the same point, structurally
    # impossible to separate in a linear static/modal solve on this mesh.
    for other in NEIGHBOR_VOLS:
        shared = vol_node_ids.get(TARGET_VOL, set()) & vol_node_ids.get(other, set())
        print(f"\nVolume {TARGET_VOL} <-> volume {other}: {len(shared)} literally "
              f"shared mesh node ids (same node, not just coincident).")
        for nid in sorted(shared)[:3]:
            row = id_to_row[nid]
            print(f"    node {nid}: coords {np.asarray(fem.nodes.coords).reshape(-1,3)[row]}")

    # Geometry (CAD) edge wireframe, same technique as plot_eigen_and_
    # selfweight_*.py.
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

    # Boundary surface triangles per volume, via the 2-D boundary entities
    # of each volume (robust even where two volumes share a surface).
    coords = np.asarray(fem.nodes.coords, dtype=np.float64).reshape(-1, 3)

    def volume_boundary_tris(vol_tag):
        tris = []
        boundary = gmsh.model.getBoundary([(3, vol_tag)], oriented=False, combined=False)
        for _bdim, bsurf in boundary:
            etypes, _etags, enodes = gmsh.model.mesh.getElements(dim=2, tag=abs(bsurf))
            for etype, enode_arr in zip(etypes, enodes):
                _name, _edim, _order, n_per_elem, _, _ = gmsh.model.mesh.getElementProperties(etype)
                if n_per_elem != 3:
                    continue  # skip any non-tri facet (shouldn't occur for a tet mesh boundary)
                arr = np.asarray(enode_arr, dtype=np.int64).reshape(-1, 3)
                for a, b, c in arr:
                    if a in id_to_row and b in id_to_row and c in id_to_row:
                        tris.append([id_to_row[a], id_to_row[b], id_to_row[c]])
        return np.array(tris, dtype=np.int64) if tris else np.zeros((0, 3), dtype=np.int64)

    target_tris = volume_boundary_tris(TARGET_VOL)
    neighbor_tris = {v: volume_boundary_tris(v) for v in NEIGHBOR_VOLS}
    other_vols = [t for _, t in all_vols if t != TARGET_VOL and t not in NEIGHBOR_VOLS]
    other_tris_list = [volume_boundary_tris(v) for v in other_vols]
    other_tris = (np.vstack([t for t in other_tris_list if t.size])
                  if any(t.size for t in other_tris_list) else np.zeros((0, 3), dtype=np.int64))

    print(f"Volume {TARGET_VOL}: {len(target_tris)} boundary triangles")
    for v, t in neighbor_tris.items():
        print(f"Volume {v}: {len(t)} boundary triangles")


def draw(ax, tris, color, alpha=1.0):
    if tris.size == 0:
        return
    verts = coords[tris]
    ax.add_collection3d(Poly3DCollection(verts, facecolor=color, edgecolor="none", alpha=alpha))


def add_geom_edges(ax):
    if geom_edge_rows.size == 0:
        return
    seg_verts = coords[geom_edge_rows]
    ax.add_collection3d(Line3DCollection(seg_verts, colors="#2b2b2b", linewidths=0.5))


def build_ax(zoom=False, elev=18, azim=-65):
    fig = plt.figure(figsize=(9, 8))
    ax = fig.add_subplot(111, projection="3d")
    draw(ax, other_tris, "#cfcfcf", alpha=0.5)
    for v, t in neighbor_tris.items():
        draw(ax, t, "#ff9900", alpha=0.95)
    draw(ax, target_tris, "#d62728", alpha=0.95)
    add_geom_edges(ax)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()

    if zoom:
        focus_tris = np.vstack([target_tris] + [t for t in neighbor_tris.values() if t.size])
        pts = coords[focus_tris.reshape(-1)]
        mins, maxs = pts.min(axis=0), pts.max(axis=0)
        pad = 0.4 * np.max(maxs - mins)
        mins -= pad
        maxs += pad
    else:
        mins, maxs = coords.min(axis=0), coords.max(axis=0)

    ax.set_xlim(mins[0], maxs[0])
    ax.set_ylim(mins[1], maxs[1])
    ax.set_zlim(mins[2], maxs[2])
    try:
        ax.set_box_aspect((maxs - mins))
    except Exception:
        pass
    return ax


def build_joint_ax(other_vol, center, half_window=1.5, elev=20, azim=-45):
    """Tight close-up on ONE candidate joint: only volume 118 (red, 70%
    alpha so the neighbour shows through where they overlap) and the one
    neighbour (blue) - no other context to avoid occlusion clutter -
    centered on the shared face's own centroid, +/- half_window metres."""
    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(111, projection="3d")
    draw(ax, target_tris, "#d62728", alpha=0.6)
    draw(ax, neighbor_tris[other_vol], "#1f77b4", alpha=0.6)
    add_geom_edges(ax)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    mins = center - half_window
    maxs = center + half_window
    ax.set_xlim(mins[0], maxs[0])
    ax.set_ylim(mins[1], maxs[1])
    ax.set_zlim(mins[2], maxs[2])
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:
        pass
    return ax


import os
os.makedirs("output/castelnuovo/plots", exist_ok=True)

for name, zoom in [("context", False), ("zoom", True)]:
    ax = build_ax(zoom=zoom)
    title = (f"Volume {TARGET_VOL} (red) and neighbours {NEIGHBOR_VOLS} (orange) "
             f"- UNDEFORMED, {name}")
    ax.set_title(title, fontsize=10)
    path = f"output/castelnuovo/plots/volume118_check_{name}.png"
    ax.figure.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(ax.figure)
    print(f"Wrote {path}")

for other_vol, center in joint_centroids.items():
    for elev, azim, view_name in [(20, -45, "a"), (60, 10, "b")]:
        ax = build_joint_ax(other_vol, center, elev=elev, azim=azim)
        ax.set_title(f"Joint volume {TARGET_VOL} (red) <-> volume {other_vol} "
                      f"(blue) - UNDEFORMED, tight close-up", fontsize=9)
        path = f"output/castelnuovo/plots/volume118_joint_{other_vol}_{view_name}.png"
        ax.figure.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(ax.figure)
        print(f"Wrote {path}")

print("\nDone.")
