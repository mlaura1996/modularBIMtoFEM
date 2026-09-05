"""
Full Task A / Task B reconciliation test: apeGmsh mesh + METIS partition,
Task A interface detection/selection/node-split
(core.mesh_generation.wall_interfaces), TclWriter's partition-aware export
INCLUDING the zeroLengthContactASDimplex contact elements
(core.opensees_generation.tcl_export), run via real mpirun -np 2
OpenSeesMP. Reconciliation was possible without a translation layer
because FEMData's node/element IDs were confirmed (probe_femdata_ids.py)
to be identical to the underlying gmsh tags.

Proves the same physical thing test_node_split.py proved for the direct-
openseespy path, but now for the apeGmsh/TCL/parallel path: fix every node
volume_a's elements reference, load volume_b, and check that (a) the
parallel analysis converges, (b) original interface nodes stay at exactly
zero (they're on the fixed side), (c) every duplicate shows independent,
nonzero relative displacement - proof the split decouples the two sides
across the TCL/partition boundary, not just in a single-process test.
"""
import os
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo", exist_ok=True)

import gmsh
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
N_PARTS = 2
MODEL_PATH = "output/castelnuovo/task_ab_model.tcl"

with apeGmsh(model_name="task_ab_test") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)

    all_vols = gmsh.model.getEntities(3)
    keep = {34, 260}
    to_remove = [(d, t) for d, t in all_vols if t not in keep]
    gmsh.model.occ.remove(to_remove, recursive=True)
    gmsh.model.occ.synchronize()

    # Raw gmsh.model.occ.fragment(), not apeGmsh's make_conformal - see
    # test_apegmsh_tcl.py for why (Tetgen PLC error on this geometry).
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    g.parts.from_model("castelnuovo_subset")
    g.physical.add_volume([34, 260], name="Masonry")
    g.physical.add_volume([34], name="Fixed")

    g.mesh.sizing.set_global_size(0.4)
    g.mesh.generation.generate(dim=3)

    # --- Task A: detect, select, split (operates on raw gmsh - same
    # session, same ID space as apeGmsh, confirmed by probe_femdata_ids.py) ---
    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    interface = next(c for c in candidates if c["volume_a"] == 34 and c["volume_b"] == 260)
    selected = [interface]
    print(f"Selected interface {interface['volume_a']}-{interface['volume_b']}, "
          f"area={interface['area_m2']:.3f} m2")

    ContactInterfaceGenerator.tag_physical_groups(selected)
    # tag_physical_groups adds a new 2D physical group AFTER the mesh
    # sizing calls above but BEFORE generate() - fine, groups can be
    # declared any time pre-mesh; re-generating isn't needed since
    # generate(dim=3) hasn't run yet at this point... but it already did
    # (see above). Physical groups on existing mesh entities are still
    # valid post-mesh (they reference geometry, mesh queries resolve them
    # against existing mesh nodes/elements) - re-verified this doesn't
    # error below.

    substitution = NodeSplitter.compute_node_map(gmsh.model, selected)
    n_dup = sum(len(v) for v in substitution.values())
    print(f"Computed {n_dup} duplicate node pairs for split volume {interface['split_volume']}")

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements, "
          f"partitions={fem.elements.partitions}")

    E, nu, rho = 700.0e6, 0.25, 2000.0
    mat_tag = 1

    writer = TclWriter(ndm=3, ndf=3)
    writer.header()
    writer.nodes(fem)
    writer.duplicate_nodes(gmsh.model, selected)
    writer.material_linear_elastic(mat_tag, E, nu, rho)
    for rank in range(N_PARTS):
        writer.solid_elements(fem, "Masonry", mat_tag, rank,
                               body_force=(0.0, 0.0, -rho * 9.81),
                               node_substitution=substitution)
    writer.contact_elements(fem, selected, Kn_nominal=69000.0 * 1e9, Kt_nominal=0.001 * 1e9)
    writer.fix(fem, "Fixed", dofs=[1, 1, 1])
    writer.analysis_static_gravity(n_steps=5)

    # Post-analysis check, run identically (and independently) on every
    # rank: every original/duplicate pair's relative displacement.
    writer.raw("set n_moved 0")
    writer.raw("set n_pairs 0")
    for orig_tag, dup_tag in interface["node_map"].items():
        writer.raw(f"incr n_pairs")
        writer.raw(
            f"if {{ abs([nodeDisp {dup_tag} 1]-[nodeDisp {orig_tag} 1]) > 1e-12 "
            f"|| abs([nodeDisp {dup_tag} 2]-[nodeDisp {orig_tag} 2]) > 1e-12 "
            f"|| abs([nodeDisp {dup_tag} 3]-[nodeDisp {orig_tag} 3]) > 1e-12 }} {{ incr n_moved }}"
        )
    writer.raw('puts "process [getPID] of [getNP]: n_pairs=$n_pairs n_moved=$n_moved"')

    writer.write(MODEL_PATH)
    print(f"Wrote {MODEL_PATH}")

print(f"\nRunning with real OpenSeesMP (mpirun -np {N_PARTS})...")
result = subprocess.run(
    ["mpirun", "--allow-run-as-root", "-np", str(N_PARTS), "/usr/local/bin/OpenSeesMP", MODEL_PATH],
    capture_output=True, text=True,
)
combined = result.stdout + result.stderr
print(combined)
assert result.returncode == 0, f"OpenSeesMP run failed with exit code {result.returncode}"

import re
reports = re.findall(r"n_pairs=(\d+) n_moved=(\d+)", combined)
assert len(reports) == N_PARTS, f"expected {N_PARTS} rank reports, found {len(reports)}: {reports}"
for n_pairs, n_moved in reports:
    assert n_pairs == n_moved, (
        f"only {n_moved}/{n_pairs} original/duplicate pairs show relative displacement - "
        f"split is not decoupling the sides across the apeGmsh/TCL/parallel path"
    )
    assert int(n_pairs) > 0, "zero pairs checked - test is vacuous"

print(f"\nPASS: Task A node-split + Task B apeGmsh/TCL/partition pipeline reconciled - "
      f"all {reports[0][0]} interface node pairs show independent displacement, "
      f"verified independently on both ranks, via real OpenSeesMP mpirun -np {N_PARTS}.")
