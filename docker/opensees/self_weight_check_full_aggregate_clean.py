"""
Same self-weight-only, bonded (no Task A interfaces) sanity check as
self_weight_check_full_aggregate.py, but on the CLEANED Castelnuovo
geometry (resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp -
277/279 volumes after fragment, no slabs, duplicates/interpenetrations
resolved - see scripts/repair_step_geometry.py) instead of the original
final_example_PRONTO.stp (316 solids, brief 3.3's 663.71 m^3).

Why a separate script rather than swapping STEP_PATH in place: the old
script's numbers (663.71 m^3, 0.027% mass/weight error, ~1.4mm max
displacement) are a validated reference for the OLD geometry - useful to
diff against if this run's numbers look wrong. Total volume/weight here
is EXPECTED to differ (no slabs), so there is no single "right" number to
assert against; this script just prints what it computes and checks
internal consistency (reaction sum vs. its own independently-computed
weight), the same way the original does.

Run BEFORE full_aggregate_with_interfaces_clean.py: confirms base fixity
and self-weight balance still hold on the cleaned geometry before layering
Task A contact interfaces on top of it.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_full_aggregate_clean", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
import numpy as np
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

from core.mesh_generation.wall_interfaces import InterfaceDetection
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
N_PARTS = 6
MODEL_PATH = "output/castelnuovo/self_weight_full_clean_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_clean"
GLOBAL_MESH_SIZE = 0.6  # m - coarse first pass, not the brief's 0.167 m target
# Weighted-average of the 4 HMO/MQI-calibrated masonry types (materials.md):
# E = mean(1526.6, 1198.7, 987.8, 1198.7[type D=B]) = 1227.95 MPa, nu=0.2,
# rho=1450 kg/m3 (same for all 4 types). Replaces the generic placeholder
# (700 MPa/nu=0.25/2000 kg/m3, copy-pasted across this whole pipeline,
# never the project's own calibrated material) - equal-weighted since a
# real per-facade/unit material assignment needs a volume<->facade mapping
# that doesn't exist yet (open_questions.md #6: unit subdivision is only
# inferred from the cadastral map, not cross-referenced against the STEP
# geometry).
E, nu, rho = 1227.95e6, 0.2, 1450.0
G_ACCEL = 9.81

with apeGmsh(model_name="self_weight_full_clean") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded (cleaned geometry - no slabs, "
          f"see scripts/repair_step_geometry.py; expect ~279, NOT the old 316)")

    total_volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in all_vols)
    print(f"Total volume (gmsh): {total_volume:.2f} m^3 (no fixed expectation here - "
          f"no slabs, so this will not match the old geometry's 663.71 m^3)")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)

    g.parts.from_model("castelnuovo_full_clean")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")

    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)

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

    # Per-volume element ids, for the partition-by-volume export below -
    # MUST happen before partition() (same reason as everywhere else in
    # this project: partitioning mutates gmsh's element/entity bookkeeping,
    # this same query silently returns empty afterward).
    volume_element_ids = {}
    for _dim, vol in all_vols:
        _etypes, etags, _enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
        ids = set()
        for tags in etags:
            ids.update(int(t) for t in tags)
        volume_element_ids[vol] = ids

    ground_volumes = InterfaceDetection.find_ground_bearing_volumes(candidates, volume_z_ranges)
    print(f"{len(ground_volumes)}/{len(volume_z_ranges)} volumes identified as "
          f"ground-bearing (no other volume detected underneath)")

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    # Partition-by-volume export, for LOCAL gmsh rendering
    # (scripts/inspect_partition_gui.py, scripts/render_partition_views.py)
    # - same reasoning as full_aggregate_with_interfaces_clean.py: real
    # gmsh screenshots don't work inside this container (gmsh.write()
    # hangs under its Xvfb/software-OpenGL stack), and centroid (not
    # volume tag) is what's portable across apeGmsh/gmsh versions.
    rank_element_ids = {}
    for rank in range(N_PARTS):
        er = fem.elements.get(pg="Masonry", partition=rank + 1)
        ids = set()
        for group in er:
            for eid, _conn in group:
                ids.add(int(eid))
        rank_element_ids[rank] = ids

    volume_rank = {}
    for vol, elem_ids in volume_element_ids.items():
        if not elem_ids:
            continue
        counts = [(rank, len(elem_ids & rank_element_ids[rank])) for rank in range(N_PARTS)]
        volume_rank[vol] = max(counts, key=lambda t: t[1])[0]

    volume_partition_export = []
    for _dim, vol in all_vols:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(3, vol)
        volume_partition_export.append({"centroid": [cx, cy, cz], "rank": volume_rank.get(vol, 0)})
    import json as _json
    partition_export_path = "output/castelnuovo/plots/full_aggregate_clean_partition_by_volume.json"
    with open(partition_export_path, "w") as _f:
        _json.dump(volume_partition_export, _f, indent=2)
    print(f"Wrote {partition_export_path} ({len(volume_partition_export)} volumes)")

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
    writer.material_linear_elastic(mat_tag, E, nu, rho)
    for rank in range(N_PARTS):
        writer.solid_elements(fem, "Masonry", mat_tag, rank,
                               body_force=(0.0, 0.0, -rho * G_ACCEL))
    for nid in base_ids_all:
        writer.raw(f"fix {int(nid)} 1 1 1")

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

DEFORM_SCALE = 200.0
# Same styling as full_aggregate_with_interfaces_clean.py's fix - real
# mesh/geometry edges + undeformed ghost, not a flat edgeless blob; view
# angle matched to scripts/inspect_partition_gui.py's default rotation.
ax = results.plot.deformed(component="displacement_z", scale=DEFORM_SCALE,
                            cmap="Blues", edge_color="#3a3a3a", linewidth=0.25, ghost=True)
ax.view_init(elev=18, azim=-65)
ax.set_title(f"Castelnuovo FULL aggregate (clean geometry) - self-weight, bonded, "
             f"linear elastic - deformed ×{DEFORM_SCALE:g}", fontsize=10)
ax.set_xlabel("X", fontsize=8)
ax.set_ylabel("Y", fontsize=8)
ax.set_zlabel("Z", fontsize=8)
for axis in ax.figure.axes:
    axis.tick_params(labelsize=7)
    if axis is not ax:
        axis.set_ylabel(axis.get_ylabel(), fontsize=8)
deformed_path = "output/castelnuovo/plots/full_aggregate_clean_deformed_uz.png"
ax.figure.savefig(deformed_path, dpi=200, bbox_inches="tight")
print(f"Wrote {deformed_path}")

print("\nDone.")
