"""
Same full 316-solid Castelnuovo aggregate and per-volume base fixity as
self_weight_check_full_aggregate.py, now WITH Task A wall-to-wall contact
interfaces - the combination that hadn't been tried yet (only "full
aggregate, bonded" and "18-volume subset, with interfaces" existed
separately). Still linear elastic, not the real ASDConcrete3D material -
one variable at a time, since that combination (material.py's
test_asdconcrete3d_parallel.py) is a separate, still-unresolved
convergence problem on the smaller 18-volume cluster.

Interface selection stays conservative (2 interfaces) for the same reason
as test_task_ab_scaled.py and this script's own base-fixity sibling:
selecting many candidate interfaces at once risks an unrestrained
mechanism under self-weight alone (found the hard way earlier this
session). On the full aggregate, with hundreds of candidate touching
pairs instead of 39, this risk is larger, not smaller - so the same
small, deliberate subset approach is used here too, not "select
everything."
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_full_aggregate_interfaces", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
import numpy as np
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, ContactInterfaceGenerator, NodeSplitter,
)
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
N_PARTS = 6
MODEL_PATH = "output/castelnuovo/full_aggregate_interfaces_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_interfaces"
GLOBAL_MESH_SIZE = 0.6
E, nu, rho = 700.0e6, 0.25, 2000.0
G_ACCEL = 9.81

with apeGmsh(model_name="full_aggregate_interfaces") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded (brief 3.3: 316 solids expected)")

    total_volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in all_vols)
    print(f"Total volume (gmsh): {total_volume:.2f} m^3 (brief 3.3 reports 663.71 m^3)")

    # Touching-pair detection before meshing/partitioning (see
    # self_weight_check_full_aggregate.py's comment - doing this after
    # partition() breaks with "Unknown OpenCASCADE entity").
    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    vertical = [c for c in candidates if c["orientation"] == "vertical_joint"]
    print(f"{len(candidates)} candidates, {len(vertical)} vertical_joint")

    # Conservative subset, same reasoning as test_task_ab_scaled.py.
    selected = vertical[:2]
    print(f"{len(selected)} interfaces selected (conservative subset, not all)")
    assert len(selected) >= 1

    ContactInterfaceGenerator.tag_physical_groups(selected)

    g.parts.from_model("castelnuovo_full")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")

    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)

    # Node split (needs the mesh to exist) - before partitioning, like
    # every other Task A/B script.
    substitution = NodeSplitter.compute_node_map(gmsh.model, selected)
    n_dup_total = sum(len(v) for v in substitution.values())
    print(f"{n_dup_total} duplicate nodes across {len(selected)} interfaces")

    # Per-volume Z ranges from mesh node coordinates, for ground-bearing
    # base fixity (same approach as self_weight_check_full_aggregate.py).
    all_node_tags, all_node_coords, _ = gmsh.model.mesh.getNodes()
    node_z_by_tag = {int(t): float(c[2]) for t, c in zip(all_node_tags, all_node_coords.reshape(-1, 3))}

    volume_node_ids = {}
    volume_z_ranges = {}
    for _dim, vol in all_vols:
        _etypes, _etags, enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
        if not enodes or len(enodes[0]) == 0:
            continue
        vol_nodes = sorted(set(int(n) for n in enodes[0]))
        zs = [node_z_by_tag[n] for n in vol_nodes if n in node_z_by_tag]
        if not zs:
            continue
        volume_node_ids[vol] = vol_nodes
        volume_z_ranges[vol] = (min(zs), max(zs))

    ground_volumes = InterfaceDetection.find_ground_bearing_volumes(candidates, volume_z_ranges)
    print(f"{len(ground_volumes)}/{len(volume_z_ranges)} volumes identified as ground-bearing")

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    BASE_TOL = 0.05
    base_ids_set = set()
    for vol in ground_volumes:
        local_zmin = volume_z_ranges[vol][0]
        for n in volume_node_ids[vol]:
            if node_z_by_tag[n] <= local_zmin + BASE_TOL:
                base_ids_set.add(n)
    base_ids_all = np.asarray(sorted(base_ids_set), dtype=np.int64)
    print(f"{len(base_ids_all)} nodes fixed, across {len(ground_volumes)} ground-bearing volumes")
    assert len(base_ids_all) > 0

    mat_tag = 1
    writer = TclWriter(ndm=3, ndf=3)
    writer.header()
    writer.nodes(fem)
    writer.duplicate_nodes(gmsh.model, selected)
    writer.material_linear_elastic(mat_tag, E, nu, rho)
    for rank in range(N_PARTS):
        writer.solid_elements(fem, "Masonry", mat_tag, rank,
                               body_force=(0.0, 0.0, -rho * G_ACCEL),
                               node_substitution=substitution)
    writer.contact_elements(fem, selected, Kn_nominal=69000.0e9, Kt_nominal=0.001e9)
    for nid in base_ids_all:
        writer.raw(f"fix {int(nid)} 1 1 1")

    # Recorders: same partition-safe pattern as self_weight_check_full_aggregate.py.
    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)
    writer.raw("if {$pid==0} {")
    for line in spec.to_tcl_commands(output_dir=RECORDER_DIR + "/", file_format="out"):
        writer.raw("    " + line)
    writer.raw("}")

    reaction_files = {}
    ids_str = " ".join(str(int(n)) for n in base_ids_all)
    for rank in range(N_PARTS):
        fname = f"{RECORDER_DIR}/base_reaction_rank{rank}.out"
        reaction_files[rank] = fname
        writer.raw(f"if {{$pid=={rank}}} {{")
        writer.raw(f"    recorder Node -file {fname} -time -node {ids_str} -dof 3 reaction")
        writer.raw("}")

    # NewtonLineSearch + finer increments - test_task_ab_scaled.py needed
    # this on its 18-volume/2-interface cluster (plain Newton + coarse
    # steps diverged there); using the same robust settings from the
    # start here rather than waiting to hit the same problem.
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
print(combined[-4000:])
assert result.returncode == 0, f"OpenSeesMP run failed with exit code {result.returncode}"

reports = re.findall(r"analyze returned (-?\d+)", combined)
assert len(reports) == N_PARTS, f"expected {N_PARTS} rank reports, found {len(reports)}: {reports}"
for ok in reports:
    assert ok == "0", f"analysis did not converge on some rank (ok={ok})"
print(f"\nConverged on all {N_PARTS} ranks.")

total_reaction = 0.0
for rank, fname in reaction_files.items():
    with open(fname) as f:
        last_line = f.readlines()[-1]
    vals = [float(x) for x in last_line.split()[1:]]
    assert len(vals) == len(base_ids_all), (
        f"rank {rank}: expected {len(base_ids_all)} reaction values, got {len(vals)}"
    )
    total_reaction += sum(vals)

total_weight = rho * G_ACCEL * total_volume
print(f"\nTotal self-weight (rho * g * V, independent calc): {total_weight:.1f} N")
print(f"Total vertical reaction at base (from analysis):    {total_reaction:.1f} N")
err_same_sign = 100.0 * (total_reaction - total_weight) / total_weight
err_opp_sign = 100.0 * (total_reaction - (-total_weight)) / total_weight
print(f"Difference if same sign as weight:     {err_same_sign:.3f}%")
print(f"Difference if opposite sign (typical): {err_opp_sign:.3f}%")

print("\nLoading results via apeGmsh.Results.from_recorders()...")
results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
print(results)

ax = results.plot.deformed(component="displacement_z", scale=200.0, ghost=False,
                            cmap="Blues", edge_color=None)
ax.set_title("Castelnuovo FULL aggregate + Task A interfaces - self-weight, linear elastic - deformed x200")
deformed_path = "output/castelnuovo/plots/full_aggregate_interfaces_deformed_uz.png"
ax.figure.savefig(deformed_path, dpi=150, bbox_inches="tight")
print(f"Wrote {deformed_path}")

print("\nDone.")
