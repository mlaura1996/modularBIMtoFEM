"""
Same model as self_weight_check_full_aggregate_clean.py (full 279-volume
aggregate, cleaned geometry, bonded - no Task A interfaces, 0.6 m mesh,
per-volume ground-bearing base fixity), run through the same static
self-weight check FIRST (gives the self-weight/reaction numbers), THEN an
eigenvalue (modal) analysis on the same domain - NEW capability, not
previously wired up anywhere in this pipeline (the only prior eigenvector
code, external/gmsh2opensees/g2o_*.py, is Chapter 4's serial openseespy
path, not this parallel TCL/OpenSeesMP one).

Writes, under output/castelnuovo/recorders_full_aggregate_clean_eigen/:
  - eigenvalues.txt        - raw omega^2 per mode, one per line
  - modal_properties.txt   - OpenSees' own `modalProperties` report
                              (participation factors, effective modal mass
                              ratios) - used afterward to pick which modes
                              are actually "most significant", not just
                              the first N by number
  - mode<k>_eigenvector.out - per-node eigenvector displacement for mode k,
                              same flat format as the static displacement
                              recorder (single writer, rank 0 - trusting
                              the same "every rank ends up holding the full
                              global result after a collective operation"
                              behaviour already verified for the static
                              case, not independently re-verified here for
                              eigen specifically)

No plotting here - deliberately split out (scripts/plot_eigen_modes.py,
local) so plot styling can be iterated without re-running the analysis
(eigen itself is cheap on this mesh, but no reason to couple them).
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_full_aggregate_clean", exist_ok=True)
os.makedirs("output/castelnuovo/recorders_full_aggregate_clean_eigen", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
import numpy as np
from apeGmsh import apeGmsh
from apeGmsh.solvers.Recorders import Recorders

from core.mesh_generation.wall_interfaces import InterfaceDetection
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
N_PARTS = 1  # NOT 6 - three attempts at 6-way partitioning all stalled identically
# (flat memory, same symptom regardless of mesh size or mode count) - user's own
# recollection: eigen didn't work under STKO's domain decomposition either.
# Testing whether ARPACK just doesn't cooperate with OpenSeesMP's partitioned
# domain at all, independent of problem size - N_PARTS=1 means no decomposition.
N_MODES = 10  # 3 modes (first working run) only reached ~30%/8% cumulative mass
# participation in X/Y - need more modes to find the actually significant ones.
MODEL_PATH = "output/castelnuovo/eigen_self_weight_full_clean_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_clean"
EIGEN_DIR = "output/castelnuovo/recorders_full_aggregate_clean_eigen"
GLOBAL_MESH_SIZE = 1.0  # coarser than the static-only checks (0.6m) - eigen (ARPACK)
# didn't converge in 15+ min at 0.6m (57,827 elements); much lighter DOF count here.
E, nu, rho = 700.0e6, 0.25, 2000.0
G_ACCEL = 9.81

with apeGmsh(model_name="eigen_self_weight_full_clean") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")
    total_volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in all_vols)
    print(f"Total volume: {total_volume:.2f} m^3")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)

    g.parts.from_model("eigen_self_weight_full_clean")
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

    # --- Eigenvalue (modal) analysis, on the same domain, after the static
    # self-weight solve above. New territory for this pipeline - eigen's
    # own solver is independent of the "system Mumps" set for the static
    # case (ARPACK-based, OpenSees' own dispatch), so no conflict expected,
    # but this has not been tried before on this model/image. ---
    all_ids_str = " ".join(str(int(n)) for n in fem.nodes.ids)
    writer.raw(f"set eigenvalues [eigen {N_MODES}]")
    writer.raw("if {$pid==0} {")
    writer.raw(f'    set fp [open "{EIGEN_DIR}/eigenvalues.txt" w]')
    writer.raw("    foreach val $eigenvalues { puts $fp $val }")
    writer.raw("    close $fp")
    writer.raw("}")
    # modalProperties: participation factors / effective modal mass ratios
    # - used afterward to pick the actually-significant modes, not just
    # the first N by eigenvalue order.
    writer.raw(f'modalProperties -print -file "{EIGEN_DIR}/modal_properties.txt"')
    for mode in range(1, N_MODES + 1):
        fname = f"{EIGEN_DIR}/mode{mode}_eigenvector.out"
        writer.raw("if {$pid==0} {")
        writer.raw(f'    recorder Node -file {fname} -node {all_ids_str} -dof 1 2 3 "eigen {mode}"')
        writer.raw("}")
    writer.raw("record")

    writer.write(MODEL_PATH)
    print(f"Wrote {MODEL_PATH}")

print(f"\nRunning with real OpenSeesMP (mpirun -np {N_PARTS})...")
result = subprocess.run(
    ["mpirun", "--allow-run-as-root", "-np", str(N_PARTS), "/usr/local/bin/OpenSeesMP", MODEL_PATH],
    capture_output=True, text=True,
)
combined = result.stdout + result.stderr
print(combined[-6000:])
assert result.returncode == 0, f"OpenSeesMP run failed with exit code {result.returncode}"

reports = re.findall(r"analyze returned (-?\d+)", combined)
assert len(reports) == N_PARTS, f"expected {N_PARTS} rank reports, found {len(reports)}: {reports}"
for ok in reports:
    assert ok == "0", f"static analysis did not converge on some rank (ok={ok})"
print(f"\nStatic self-weight converged on all {N_PARTS} ranks.")

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
print(f"Difference: {err_same_sign:.3f}%")

import json
summary = {
    "total_volume_m3": total_volume,
    "self_weight_calculated_N": total_weight,
    "total_base_reaction_N": total_reaction,
    "weight_reaction_diff_pct": err_same_sign,
    "n_modes": N_MODES,
    "mesh_nodes": len(fem.nodes.ids),
    "mesh_elements": len(fem.elements.ids),
}
with open(f"{EIGEN_DIR}/summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"Wrote {EIGEN_DIR}/summary.json")

print("\nDone.")
