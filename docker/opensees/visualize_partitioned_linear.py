"""
Same model as test_task_ab_scaled.py (18-volume connected cluster, 2
wall-to-wall contact interfaces, 6 partitions, linear elastic material,
self-weight static, real mpirun OpenSeesMP + Mumps) - already proven to
converge. This script adds nothing to the model except recorders, then
loads the result back through apeGmsh and saves two static images
(deformed shape, contour) with results.plot - so there is something
to actually look at, not just a pass/fail assertion.

Deliberately NOT the nonlinear ASDConcrete3D material
(test_asdconcrete3d_parallel.py) - that combination didn't converge and is
being isolated separately. This script's job is to sanity-check the
apeGmsh recorder/visualisation bridge itself on a model that is already
known to work, before trusting it on a harder one.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_linear", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
N_PARTS = 6
MODEL_PATH = "output/castelnuovo/visualize_linear_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_linear"
CLUSTER_SIZE = 18

# --- Same BFS cluster build as test_task_ab_scaled.py ---
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
all_candidates = InterfaceDetection.find_touching_surface_pairs()
gmsh.finalize()

adjacency = {}
for c in all_candidates:
    adjacency.setdefault(c["volume_a"], set()).add(c["volume_b"])
    adjacency.setdefault(c["volume_b"], set()).add(c["volume_a"])

cluster = {34}
frontier = [34]
while frontier and len(cluster) < CLUSTER_SIZE:
    v = frontier.pop(0)
    for neighbor in sorted(adjacency.get(v, ())):
        if neighbor not in cluster:
            cluster.add(neighbor)
            frontier.append(neighbor)
            if len(cluster) >= CLUSTER_SIZE:
                break
print(f"Cluster of {len(cluster)} connected volumes: {sorted(cluster)}")

with apeGmsh(model_name="visualize_linear") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)

    all_vols = gmsh.model.getEntities(3)
    to_remove = [(d, t) for d, t in all_vols if t not in cluster]
    gmsh.model.occ.remove(to_remove, recursive=True)
    gmsh.model.occ.synchronize()
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    remaining = sorted(t for d, t in gmsh.model.getEntities(3))
    print(f"{len(remaining)} volumes survived fragment: {remaining}")

    g.parts.from_model("castelnuovo_cluster")
    g.physical.add_volume(remaining, name="Masonry")
    g.physical.add_volume([34], name="Fixed")

    g.mesh.sizing.set_global_size(0.4)
    g.mesh.generation.generate(dim=3)

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    vertical = [c for c in candidates if c["orientation"] == "vertical_joint"]
    selected = vertical[:2]  # same conservative subset - see test_task_ab_scaled.py's comment
    print(f"{len(candidates)} candidates, {len(vertical)} vertical_joint, "
          f"{len(selected)} selected")

    ContactInterfaceGenerator.tag_physical_groups(selected)
    substitution = NodeSplitter.compute_node_map(gmsh.model, selected)
    n_dup_total = sum(len(v) for v in substitution.values())
    print(f"{n_dup_total} duplicate nodes across {len(selected)} interfaces")

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

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

    # --- Recorders, via apeGmsh's own spec/emitter, so Results.from_recorders() can read them back. ---
    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)
    for line in spec.to_tcl_commands(output_dir=RECORDER_DIR + "/", file_format="out"):
        writer.raw(line)

    # Same solver settings as test_task_ab_scaled.py - already proven to converge on this cluster.
    writer.raw("constraints Plain")
    writer.raw("numberer ParallelRCM")
    writer.raw("system Mumps")
    writer.raw("test NormDispIncr 1e-6 30 1")
    writer.raw("algorithm NewtonLineSearch")
    n_steps = 20
    writer.raw(f"integrator LoadControl {1.0/n_steps:.6g}")
    writer.raw("analysis Static")
    writer.raw(f"set ok [analyze {n_steps}]")
    writer.raw('puts "process [getPID] of [getNP]: analyze returned $ok"')

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

reports = re.findall(r"analyze returned (-?\d+)", combined)
assert len(reports) == N_PARTS, f"expected {N_PARTS} rank reports, found {len(reports)}: {reports}"
for ok in reports:
    assert ok == "0", f"analysis did not converge on some rank (ok={ok})"

print(f"\nPASS: linear elastic + {len(selected)} contact interface(s) + "
      f"N_PARTS={N_PARTS} converged on every rank.")

# --- Visualise with apeGmsh, headlessly ---
print("\nLoading results via apeGmsh.Results.from_recorders()...")
results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
print(results)

DEFORM_SCALE = 30.0
ax = results.plot.deformed(component="displacement_z", scale=DEFORM_SCALE, ghost=True)
ax.set_title(f"Castelnuovo cluster - self-weight, linear elastic - deformed shape (x{DEFORM_SCALE:.0f}), colored by Uz")
deformed_path = "output/castelnuovo/plots/linear_parallel_deformed_uz.png"
ax.figure.savefig(deformed_path, dpi=150, bbox_inches="tight")
print(f"Wrote {deformed_path}")

ax2 = results.plot.contour("displacement_z", deformed=False)
contour_path = "output/castelnuovo/plots/linear_parallel_contour_uz.png"
ax2.figure.savefig(contour_path, dpi=150, bbox_inches="tight")
print(f"Wrote {contour_path}")

print("\nDone - open the two PNGs under output/castelnuovo/plots/ to inspect the result.")
