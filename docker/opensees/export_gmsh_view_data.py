"""
Exports portable (already-deformed) triangle + edge data for the self-
weight and all N_MODES mode shapes, so they can be rendered LOCALLY with
real gmsh screenshots (true hidden-surface removal via gmsh's own OpenGL
z-buffer) instead of matplotlib's Poly3DCollection/Line3DCollection, which
has no proper depth-sorting between separate collections - confirmed to be
the cause of the "x-ray" look (far-side geometry edges drawn on top of
near-side opaque faces) that persisted even after restricting edges to
exterior-only surfaces (docker/opensees/plot_eigen_and_selfweight_fine.py).

Exports RAW COORDINATES (already deformed, already colored by scalar
value) rather than re-meshing the STEP file locally: the local
(castelnuovo_viewer) and Docker (this image) environments pin different
apeGmsh/gmsh versions, which number - and can even slightly re-realize -
meshes differently even from identical input (the same lesson as
InterfaceSelection.key_for()'s centroid-based matching), so matching
~17,700 individual nodes back up by nearest-coordinate would be fragile.
Feeding gmsh pre-computed triangle/line geometry as raw list-data (View
"ST"/"SL" data) sidesteps that entirely - nothing needs to be re-meshed or
matched locally, just rendered.

Writes output/castelnuovo/plots/gmsh_export/<case>.npz, each with:
  tri_verts   (Ntri, 3, 3) - deformed xyz of each triangle's 3 corners
  tri_vals    (Ntri, 3)    - the scalar to colour by, per corner
  edge_verts  (Nedge, 2, 3) - deformed xyz of each exterior-only edge's 2 ends
  clim        (2,)         - (vmin, vmax) for the colour scale
  title       scalar string - plot title
  cbar_label  scalar string - colorbar label
"""
import math
import os
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/plots/gmsh_export", exist_ok=True)

import numpy as np
import gmsh
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_clean_fine"
EIGEN_DIR = "output/castelnuovo/recorders_full_aggregate_clean_eigen_fine"
EXPORT_DIR = "output/castelnuovo/plots/gmsh_export"
GLOBAL_MESH_SIZE = 0.6
N_MODES = 10
DEFORM_SCALE_SELFWEIGHT = 200.0
MAX_MODE_DISPLACEMENT_M = 0.5

with apeGmsh(model_name="export_gmsh_view_data") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    g.parts.from_model("export_gmsh_view_data")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    id_to_row = {int(nid): i for i, nid in enumerate(fem.nodes.ids)}

    # Exterior-only geometry edges (same technique as plot_eigen_and_
    # selfweight_fine.py).
    surface_to_volumes = {}
    for _dim, vol in all_vols:
        boundary = gmsh.model.getBoundary([(3, vol)], oriented=False, combined=False)
        for _bdim, bsurf in boundary:
            surface_to_volumes.setdefault(abs(bsurf), set()).add(vol)
    exterior_surfaces = {s for s, vols in surface_to_volumes.items() if len(vols) == 1}

    edge_pairs = set()
    for _dim, curve_tag in gmsh.model.getEntities(1):
        upward, _downward = gmsh.model.getAdjacencies(1, curve_tag)
        if not any(abs(s) in exterior_surfaces for s in upward):
            continue
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
    print(f"{len(geom_edge_rows)} exterior geometry edges.")

    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)
    results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
    tris, segs, lookup, coords = results.plot._facets()
    face_idx = lookup[tris]
    edge_idx = geom_edge_rows  # already row indices into `coords`

    selfweight_uz = results.plot._read_node_scalars("displacement_z", step=-1, stage=None)
    selfweight_disp = np.column_stack([
        results.plot._read_node_scalars(c, step=-1, stage=None)
        for c in ("displacement_x", "displacement_y", "displacement_z")
    ])
    selfweight_deformed = coords + DEFORM_SCALE_SELFWEIGHT * selfweight_disp

    with open(f"{EIGEN_DIR}/modal_properties.txt") as f:
        modal_txt = f.read()
    section = modal_txt.split("9. MODAL PARTICIPATION MASS RATIOS")[1].split("* 10.")[0]
    rows_ratio = []
    for line in section.splitlines():
        parts = line.split()
        if len(parts) == 7 and parts[0].isdigit():
            m, mx, my = int(parts[0]), float(parts[1]), float(parts[2])
            rows_ratio.append((m, mx, my))
    rows_ratio.sort(key=lambda r: -(r[1] + r[2]))
    top_modes = {r[0] for r in rows_ratio[:3]}

    with open(f"{EIGEN_DIR}/eigenvalues.txt") as f:
        eigenvalues = [float(x) for x in f.read().split()]

    def parse_eigenvector_file(path, n_nodes):
        with open(path) as f:
            last_line = f.readlines()[-1]
        vals = np.array([float(x) for x in last_line.split()])
        return vals.reshape(n_nodes, 3)

    def export_case(name, tri_verts, tri_vals, edge_verts, clim, title, cbar_label):
        path = f"{EXPORT_DIR}/{name}.npz"
        np.savez(
            path,
            tri_verts=tri_verts.astype(np.float32),
            tri_vals=tri_vals.astype(np.float32),
            edge_verts=edge_verts.astype(np.float32),
            clim=np.array(clim, dtype=np.float32),
            title=np.array(title),
            cbar_label=np.array(cbar_label),
        )
        print(f"Wrote {path} ({len(tri_verts)} tris, {len(edge_verts)} edges)")

    # --- self-weight ---
    tri_verts = selfweight_deformed[face_idx]
    tri_vals = selfweight_uz[face_idx]
    edge_verts = selfweight_deformed[edge_idx]
    export_case(
        "selfweight", tri_verts, tri_vals, edge_verts,
        clim=(float(selfweight_uz.min()), float(selfweight_uz.max())),
        title=f"Self-weight, bonded - deformed x{DEFORM_SCALE_SELFWEIGHT:g}",
        cbar_label="displacement_z (m)",
    )

    # --- all modes ---
    for mode in range(1, N_MODES + 1):
        mode_disp = parse_eigenvector_file(f"{EIGEN_DIR}/mode{mode}_eigenvector.out", len(fem.nodes.ids))
        node_mag = np.linalg.norm(mode_disp, axis=1)
        max_mag = node_mag.max()
        scale = MAX_MODE_DISPLACEMENT_M / max_mag if max_mag > 0 else 1.0
        deformed = coords + scale * mode_disp
        rel_mag = node_mag / max_mag if max_mag > 0 else node_mag

        T = 2 * math.pi / math.sqrt(eigenvalues[mode - 1])
        freq = 1.0 / T
        tag = " (most significant)" if mode in top_modes else ""

        tri_verts = deformed[face_idx]
        tri_vals = rel_mag[face_idx]
        edge_verts = deformed[edge_idx]
        export_case(
            f"mode{mode}", tri_verts, tri_vals, edge_verts,
            clim=(0.0, 1.0),
            title=f"Mode {mode} - T={T:.3f}s, f={freq:.3f}Hz{tag}",
            cbar_label="relative modal displacement",
        )

print("\nDone.")
