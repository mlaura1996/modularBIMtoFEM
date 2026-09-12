"""
Diagnostic for the user's observation on the bonded (no Task A interfaces)
model's mode shapes: "sembra che si staccano due unita, tral altro in un
punto in cui non mi aspetto le interfacce" - modes 1/3/8 all show a small
region (top of the aggregate) moving with much larger relative amplitude
than everything else, reading visually like a detachment.

This does NOT re-run the eigen solve - it regenerates the exact same 1.0 m,
unpartitioned mesh eigen_self_weight_full_aggregate_clean.py used (same
STEP, same fragment/global-size calls, same apeGmsh v1.5.0 image - node
ordering is deterministic for identical inputs, already relied on by
plot_eigen_and_selfweight_clean.py to combine a fresh fem with the cached
recorder files), then:

  1. Builds volume -> node-id-set (same technique as the eigen script's own
     ground-bearing detection) so displacement can be attributed to
     specific volumes, not just node coordinates.
  2. For each of the 3 top modes, finds the nodes with the largest relative
     displacement and reports which volume(s) they belong to (by fraction
     of that volume's own nodes appearing in the high-displacement set) -
     answers "is this one appendage-like volume, or a broad region".
  3. Cross-references those volumes against
     InterfaceDetection.find_touching_surface_pairs() (the SAME candidate
     detector used to build the Task A interface list elsewhere) to report
     the actual shared contact area between the "detaching" volume and its
     neighbours - fragment() is documented (wall_interfaces.py docstring)
     to produce genuinely shared topology, not just visually-touching
     geometry, so a small mesh region moving as a near-rigid block most
     likely means a small shared area (soft joint), not an unfused gap -
     this checks that directly instead of assuming it.
  4. Reports basic volume geometry (bounding box, an approximate
     "slenderness" measure) for the flagged volume(s), to distinguish a
     genuine slender appendage (merlon/chimney/decorative element) from an
     ordinary-looking wall segment that happens to be softly connected.

Prints only - no plots, no files written (other than this stdout log).
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import gmsh
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
EIGEN_DIR = "output/castelnuovo/recorders_full_aggregate_clean_eigen_fine"
GLOBAL_MESH_SIZE = 0.6
TOP_MODES = [3]
HIGH_FRAC_THRESHOLD = 0.6  # relative displacement above which a node counts as "high"

with apeGmsh(model_name="diagnose_mode_localization_fine") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidate touching-surface pairs detected "
          f"(this is the full bonded-topology check, independent of which "
          f"11 became Task A interfaces elsewhere).")
    cand_by_pair = {}
    for c in candidates:
        cand_by_pair.setdefault((c["volume_a"], c["volume_b"]), []).append(c)

    g.parts.from_model("diagnose_mode_localization")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)
    fem = g.mesh.queries.get_fem_data(dim=3)
    n_nodes = len(fem.nodes.ids)
    print(f"FEMData: {n_nodes} nodes, {len(fem.elements.ids)} elements")

    all_node_tags, all_node_coords, _ = gmsh.model.mesh.getNodes()
    node_coord_by_tag = {int(t): c for t, c in zip(all_node_tags, all_node_coords.reshape(-1, 3))}

    volume_node_ids = {}
    volume_bbox = {}
    for _dim, vol in all_vols:
        _etypes, _etags, enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
        if not enodes or len(enodes[0]) == 0:
            continue
        vol_nodes = sorted(set(int(n) for n in enodes[0]))
        volume_node_ids[vol] = set(vol_nodes)
        volume_bbox[vol] = gmsh.model.occ.getBoundingBox(3, vol)

    # id (as used in fem.nodes.ids / recorder files) -> row index, for
    # matching the recorder's flat node order back to node tags.
    id_to_row = {int(nid): i for i, nid in enumerate(fem.nodes.ids)}


def parse_eigenvector_file(path, n_nodes):
    with open(path) as f:
        last_line = f.readlines()[-1]
    vals = np.array([float(x) for x in last_line.split()])
    return vals.reshape(n_nodes, 3)


for mode in TOP_MODES:
    print(f"\n{'='*70}\nMode {mode}\n{'='*70}")
    mode_disp = parse_eigenvector_file(f"{EIGEN_DIR}/mode{mode}_eigenvector.out", n_nodes)
    node_mag = np.linalg.norm(mode_disp, axis=1)
    max_mag = node_mag.max()
    rel_mag = node_mag / max_mag if max_mag > 0 else node_mag

    high_rows = set(np.where(rel_mag >= HIGH_FRAC_THRESHOLD)[0])
    print(f"{len(high_rows)}/{n_nodes} nodes have relative displacement >= "
          f"{HIGH_FRAC_THRESHOLD:.1f}")

    # Attribute to volumes: fraction of EACH volume's own nodes that fall
    # in the high-displacement set.
    row_to_id = {i: int(nid) for i, nid in enumerate(fem.nodes.ids)}
    high_ids = {row_to_id[r] for r in high_rows}

    flagged = []
    for vol, node_set in volume_node_ids.items():
        if not node_set:
            continue
        overlap = len(node_set & high_ids)
        frac = overlap / len(node_set)
        if frac > 0.03:
            flagged.append((vol, frac, len(node_set), overlap))
    flagged.sort(key=lambda t: -t[1])

    if not flagged:
        print("No single volume dominates the high-displacement set "
              "(spread across many volumes / a broad region, not a "
              "localized appendage).")
        continue

    for vol, frac, n_own, overlap in flagged:
        bbox = volume_bbox[vol]
        xmin, ymin, zmin, xmax, ymax, zmax = bbox
        dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
        dims_sorted = sorted([dx, dy, dz])
        slenderness = dims_sorted[-1] / max(dims_sorted[0], 1e-6)
        print(f"\nVolume {vol}: {frac:.0%} of its {n_own} nodes are in the "
              f"high-displacement set ({overlap} nodes).")
        print(f"  bbox size (m): dx={dx:.2f} dy={dy:.2f} dz={dz:.2f}  "
              f"(longest/shortest side ratio: {slenderness:.1f})")

        # neighbours + shared contact area from the SAME candidate detector
        # used to build the Task A interface list.
        neighbours = []
        for (va, vb), cs in cand_by_pair.items():
            if vol in (va, vb):
                other = vb if va == vol else va
                total_area = sum(c["area_m2"] for c in cs)
                orientations = sorted(set(c["orientation"] for c in cs))
                neighbours.append((other, total_area, len(cs), orientations))
        neighbours.sort(key=lambda t: t[1])
        print(f"  {len(neighbours)} touching neighbour volume(s) "
              f"(from fragment()'s shared topology, i.e. genuinely fused, "
              f"not just visually close):")
        for other, area, n_faces, orientations in neighbours:
            print(f"    - volume {other}: shared area {area:.3f} m^2 "
                  f"across {n_faces} face(s), orientation(s) {orientations}")

print("\nDone.")
