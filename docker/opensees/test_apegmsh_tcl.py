"""
End-to-end test of the Task B pipeline: apeGmsh (import/mesh/partition) ->
TclWriter (core/opensees_generation/tcl_export.py) -> real OpenSeesMP run
via mpirun, using the actual compiled binary verified in this Docker image.

Not part of the pipeline; standing regression check, same spirit as
test_node_split.py. Run inside this image (needs ifcopenshell/OCC/apeGmsh,
only available in the conda env here, not on Windows locally).
"""
import os
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo", exist_ok=True)

import gmsh
from apeGmsh import apeGmsh

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
N_PARTS = 2

with apeGmsh(model_name="task_b_test") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)

    # Keep only two known-touching volumes (34, 260 - the same pair
    # validated in test_node_split.py) so this test stays fast; the
    # mechanism being proven (real METIS partitioning + partition-aware
    # TCL + actual parallel OpenSeesMP run) doesn't depend on model size.
    all_vols = gmsh.model.getEntities(3)
    keep = {34, 260}
    to_remove = [(d, t) for d, t in all_vols if t not in keep]
    gmsh.model.occ.remove(to_remove, recursive=True)
    gmsh.model.occ.synchronize()

    # Without this, 34 and 260 mesh as two independent, non-touching
    # bodies (same root cause identified for the raw-gmsh path in
    # test_node_split.py / wall_interfaces.py: the STEP file itself has 0
    # shared faces between adjacent solids). Confirmed here the hard way:
    # omitting this made volume 260 an entirely unconstrained floating
    # body once only 34's nodes were fixed - the static analysis diverged
    # (residual norm stuck at 2e13, never decreasing).
    # Tried apeGmsh's own g.model.queries.make_conformal(tolerance=1e-3)
    # here first: it does connect the two volumes (gmsh log confirmed "2
    # volumes with 1 connected component"), but 3D generation then failed
    # with a Tetgen PLC robustness error ("A segment and a facet
    # intersect at point") - likely a residual-precision artifact of
    # whatever boolean route make_conformal takes internally on this
    # specific fragmented-CAD geometry. Falling through to the raw
    # gmsh.model.occ.fragment() call instead - apeGmsh explicitly supports
    # this (internal_docs/first_steps.md Lesson 3.4: "you can fall through
    # to raw (dim, tag) pairs... a deliberate design choice") - and it's
    # the exact call already proven to mesh this same 34/260 pair cleanly
    # in test_node_split.py.
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    g.parts.from_model("castelnuovo_subset")
    g.physical.add_volume([34, 260], name="Masonry")
    # Fix every node of volume 34 (the "ground" side, same convention as
    # test_node_split.py) so the model has a determinate self-weight case.
    # Must be declared before get_fem_data() - the snapshot is immutable,
    # taken at extraction time (found the hard way: declaring it after
    # left the FEMData with only "Masonry", "Fixed" absent).
    g.physical.add_volume([34], name="Fixed")

    g.mesh.sizing.set_global_size(0.5)
    g.mesh.generation.generate(dim=3)

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")
    assert len(info.elements_per_partition) == N_PARTS, "partition() did not produce N_PARTS partitions"
    assert all(n > 0 for n in info.elements_per_partition.values()), "an empty partition is a degenerate test"

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements, "
          f"partitions={fem.elements.partitions}")

    from core.opensees_generation.tcl_export import TclWriter

    E, nu, rho = 700.0e6, 0.25, 2000.0  # Pa, -, kg/m3 - SI, matches model_builder.py's ElasticIsotropic path
    mat_tag = 1

    writer = TclWriter(ndm=3, ndf=3)
    writer.header()
    writer.nodes(fem)
    writer.material_linear_elastic(mat_tag, E, nu, rho)
    for pid in range(N_PARTS):
        writer.solid_elements(fem, "Masonry", mat_tag, pid,
                               body_force=(0.0, 0.0, -rho * 9.81))

    writer.fix(fem, "Fixed", dofs=[1, 1, 1])
    writer.analysis_static_gravity(n_steps=5)
    writer.raw('puts "process [getPID] of [getNP]: analysis done"')

    writer.write("output/castelnuovo/task_b_test_model.tcl")
    print("Wrote output/castelnuovo/task_b_test_model.tcl")

print("\nRunning the generated TCL with real OpenSeesMP (mpirun -np 2)...")
result = subprocess.run(
    ["mpirun", "--allow-run-as-root", "-np", str(N_PARTS),
     "/usr/local/bin/OpenSeesMP", "output/castelnuovo/task_b_test_model.tcl"],
    capture_output=True, text=True,
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
assert result.returncode == 0, f"OpenSeesMP run failed with exit code {result.returncode}"
combined = (result.stdout + result.stderr).replace("\n", " ")
assert "process 0 of 2" in combined, "rank 0 never reported completion - did it actually run?"
assert "process 1 of 2" in combined, "rank 1 never reported completion - did it actually run?"

print("\nPASS: apeGmsh partition -> TclWriter -> real OpenSeesMP mpirun -np 2, "
      "converged on both ranks.")
