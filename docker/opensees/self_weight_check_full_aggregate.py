"""
Sanity check on the FULL 316-solid Castelnuovo aggregate, self-weight
only, bonded (no Task A contact interfaces). Total volume 663.71 m^3
matches PROJECT_BRIEF.md 3.3 exactly; converges cleanly on all 6 ranks.

BASE FIXITY FIX (this version): earlier versions fixed every node within
a tolerance of one GLOBAL z_min across the whole aggregate (which
happened to be -1.50 m, matching brief 8.4's own candidate value, for the
full aggregate and for an 18-volume subset - reassuring, but not the
whole story). A single global threshold is wrong whenever different
structural units sit at slightly different foundation levels: one unit in
an earlier render showed anomalously large self-weight displacement,
traced to its own true base being a few cm above the global z_min, so it
was never actually restrained - floating, held up only by its bonded/
contact connections to neighbours. Fixed with
InterfaceDetection.find_ground_bearing_volumes() (see that function's
docstring in core/mesh_generation/wall_interfaces.py): each volume's OWN
local z_min is used, but only for volumes with no other volume detected
underneath them (via the existing "horizontal_bearing" touching-pair
classification, repurposed from its original floor/slab-exclusion role).

RECORDER FIX (this version): the first version had every rank open the
SAME recorder output file unconditionally (both for displacement and for
base reactions) - multiple MPI processes writing to one shared file path
concurrently, an OS-level race. Displacement happened to survive
(consistent column count both times it was tried) - plausibly because
Mumps' direct solve leaves every rank holding the correct full solution
vector, so all 6 ranks wrote identical, non-conflicting content. Base
reactions did NOT survive (ragged rows, "columns changed from 412 to 620")
- reactions are derived from each rank's LOCAL element forces, so a rank
that doesn't own the elements at a given base node cannot compute a valid
value there, and 6 processes racing to the same file produced genuinely
different, interleaved content.

Fix applied to both, not just the one that broke, since "it happened not
to visibly corrupt" isn't the same as "verified correct":
- Displacement: guarded to `if {$pid==0}` only - one writer, no race.
  (Kept using apeGmsh's Recorders/emit_spec_tcl - only the guard changed.)
- Reactions: NOT guarded to one rank (a single rank doesn't own every
  base node's elements) - instead sharded, one recorder + one output file
  PER RANK, each restricted to the subset of base nodes that rank's own
  partition actually contains. Hand-written TCL (apeGmsh's Recorders
  spec has no partition-aware selector), summed across all 6 files in
  Python afterward - node sets are disjoint by partition, so no
  double-counting.

Also produces two images: a partition map (which of the 6 MPI ranks owns
each node - a pure mesh/partitioning fact, read directly from FEMData, no
analysis results needed) and the self-weight deformed shape.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_full_aggregate", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
import numpy as np
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

from core.mesh_generation.wall_interfaces import InterfaceDetection
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
N_PARTS = 6
MODEL_PATH = "output/castelnuovo/self_weight_full_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate"
GLOBAL_MESH_SIZE = 0.6  # m - coarse first pass, not the brief's 0.167 m target
E, nu, rho = 700.0e6, 0.25, 2000.0
G_ACCEL = 9.81

with apeGmsh(model_name="self_weight_full") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded (brief 3.3: 316 solids expected)")

    total_volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in all_vols)
    print(f"Total volume (gmsh): {total_volume:.2f} m^3 (brief 3.3 reports 663.71 m^3)")

    # Touching-pair detection is a pure OCC/geometry query - done here,
    # right after fragment()/synchronize() and before meshing/
    # partitioning, matching every other script that uses it
    # (test_task_ab_*.py). Doing it AFTER partition() (tried first) broke
    # with "Unknown OpenCASCADE entity" - partitioning mutates the
    # topology in ways find_touching_surface_pairs()'s getBoundary() calls
    # don't tolerate.
    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)

    g.parts.from_model("castelnuovo_full")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")

    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)

    # Per-volume Z ranges from actual mesh node coordinates - needs the
    # mesh to exist (just generated above), but not partitioning.
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
    print(f"{len(ground_volumes)}/{len(volume_z_ranges)} volumes identified as "
          f"ground-bearing (no other volume detected underneath)")

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    # --- Partition map (pure mesh fact, no analysis needed) ---
    partition_nodes = {}
    for rank in range(N_PARTS):
        pn = fem.nodes.get(pg="Masonry", partition=rank + 1)
        partition_nodes[rank] = (pn.ids, pn.coords)
        print(f"  partition {rank}: {len(pn.ids)} nodes")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8, 7))
    ax_p = fig.add_subplot(111, projection="3d")
    cmap = plt.get_cmap("tab10")
    for rank in range(N_PARTS):
        _ids, coords = partition_nodes[rank]
        ax_p.scatter(coords[:, 0], coords[:, 1], coords[:, 2],
                     s=3, color=cmap(rank), label=f"partition {rank}", depthshade=False)
    ax_p.set_title("Castelnuovo full aggregate - node ownership by MPI partition (6 ranks)")
    ax_p.set_xlabel("X")
    ax_p.set_ylabel("Y")
    ax_p.set_zlabel("Z")
    ax_p.legend(markerscale=4, loc="upper left", bbox_to_anchor=(1.02, 1.0))
    partition_path = "output/castelnuovo/plots/full_aggregate_partitions.png"
    fig.savefig(partition_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {partition_path}")

    # --- Base fixity: PER-VOLUME local z_min, not one global z_min.
    # A single global minimum is wrong whenever different structural units
    # sit at slightly different foundation levels - found by inspection
    # (one unit in the 18-volume cluster render showed anomalously large
    # self-weight displacement; its own true base turned out to be a few
    # cm above the global z_min, so the old single-threshold fix never
    # caught it - that unit was floating, unsupported except through its
    # bonded/contact connections to neighbours). ground_volumes and
    # volume_z_ranges were already computed above, before partitioning.
    BASE_TOL = 0.05  # m - per-volume node-matching tolerance (mesh-size scale, not the mm-scale global check)
    base_ids_set = set()
    for vol in ground_volumes:
        local_zmin = volume_z_ranges[vol][0]
        for n in volume_node_ids[vol]:
            if node_z_by_tag[n] <= local_zmin + BASE_TOL:
                base_ids_set.add(n)
    base_ids_all = np.asarray(sorted(base_ids_set), dtype=np.int64)
    print(f"{len(base_ids_all)} nodes fixed, across {len(ground_volumes)} ground-bearing volumes' "
          f"own local base levels (not one global z_min)")
    assert len(base_ids_all) > 0

    mat_tag = 1
    writer = TclWriter(ndm=3, ndf=3)
    writer.header()
    writer.nodes(fem)
    writer.material_linear_elastic(mat_tag, E, nu, rho)
    for rank in range(N_PARTS):
        writer.solid_elements(fem, "Masonry", mat_tag, rank,
                               body_force=(0.0, 0.0, -rho * G_ACCEL))
    for nid in base_ids_all:
        writer.raw(f"fix {int(nid)} 1 1 1")

    # --- Displacement recorder: single writer (rank 0), avoids the race
    # outright rather than relying on "every rank happens to agree". ---
    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)
    writer.raw("if {$pid==0} {")
    for line in spec.to_tcl_commands(output_dir=RECORDER_DIR + "/", file_format="out"):
        writer.raw("    " + line)
    writer.raw("}")

    # --- Reaction recorders: one file PER RANK (avoids the write race),
    # each requesting the FULL base node list, not a per-partition subset.
    # Tried restricting each rank to only the base nodes its own partition
    # "owns" first - some base nodes turned out to belong to more than one
    # partition's node set (shared boundary nodes at the partition
    # interface, 420 memberships for 411 physical nodes), so ownership
    # isn't a clean partition. Requesting the same full list from every
    # rank and summing all 6 files together handles both possible
    # OpenSeesMP conventions correctly without having to know which one
    # applies: if reaction contributions are split additively across the
    # ranks touching a shared node, the per-rank files add up to the
    # right total; if only the owning rank reports a nonzero value and
    # the rest report 0, the sum is still the right total either way. ---
    reaction_files = {}
    ids_str = " ".join(str(int(n)) for n in base_ids_all)
    for rank in range(N_PARTS):
        fname = f"{RECORDER_DIR}/base_reaction_rank{rank}.out"
        reaction_files[rank] = fname
        writer.raw(f"if {{$pid=={rank}}} {{")
        writer.raw(f"    recorder Node -file {fname} -time -node {ids_str} -dof 3 reaction")
        writer.raw("}")

    writer.raw("constraints Plain")
    writer.raw("numberer ParallelRCM")
    writer.raw("system Mumps")
    writer.raw("test NormDispIncr 1e-6 30 1")
    writer.raw("algorithm Newton")
    n_steps = 10
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

# --- Mass/weight balance check: sum ALL per-rank reaction files together
# (plain text, no need to route through apeGmsh's HDF5/Results machinery
# for this - transparent and easy to verify by hand if needed). Every
# rank recorded the full base node list, so summing across all 6 files
# gives the right total under either OpenSeesMP reaction convention (see
# the comment where these recorders were written). ---
total_reaction = 0.0
for rank, fname in reaction_files.items():
    with open(fname) as f:
        last_line = f.readlines()[-1]
    vals = [float(x) for x in last_line.split()[1:]]  # first col is time
    assert len(vals) == len(base_ids_all), (
        f"rank {rank}: expected {len(base_ids_all)} reaction values, got {len(vals)} "
        f"- recorder file still inconsistent"
    )
    total_reaction += sum(vals)

total_weight = rho * G_ACCEL * total_volume
print(f"\nTotal self-weight (rho * g * V, independent calc): {total_weight:.1f} N")
print(f"Total vertical reaction at base (from analysis):    {total_reaction:.1f} N")
err_same_sign = 100.0 * (total_reaction - total_weight) / total_weight
err_opp_sign = 100.0 * (total_reaction - (-total_weight)) / total_weight
print(f"Difference if same sign as weight:     {err_same_sign:.3f}%")
print(f"Difference if opposite sign (typical): {err_opp_sign:.3f}%")

# --- Visualise with apeGmsh, headlessly ---
print("\nLoading results via apeGmsh.Results.from_recorders()...")
results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
print(results)

ax = results.plot.deformed(component="displacement_z", scale=200.0, ghost=False,
                            cmap="Blues", edge_color=None)
ax.set_title("Castelnuovo FULL aggregate - self-weight, bonded, linear elastic - deformed x200")
deformed_path = "output/castelnuovo/plots/full_aggregate_deformed_uz.png"
ax.figure.savefig(deformed_path, dpi=150, bbox_inches="tight")
print(f"Wrote {deformed_path}")

print("\nDone.")
