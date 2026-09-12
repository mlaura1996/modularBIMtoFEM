"""
Same full aggregate + Task A wall-to-wall contact interfaces as
full_aggregate_with_interfaces.py, but on the CLEANED Castelnuovo geometry
(resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp - no slabs,
duplicates/interpenetrations resolved) AND with the REAL interface
selection made interactively via scripts/select_interfaces_gui.py
(resources/survey_data/castelnuovo/interface_selection.json - 11
interfaces, a deliberate choice made against the actual picture of the
building, not an arbitrary vertical[:2] slice) instead of a hard-coded
conservative subset.

Run self_weight_check_full_aggregate_clean.py FIRST if it hasn't been -
confirms base fixity and self-weight balance on this geometry before
adding interfaces on top (verified: 0.028% mass/weight error, converges
cleanly - see that script).

Still linear elastic, not the real ASDConcrete3D material - one variable
at a time, same reasoning as the original full_aggregate_with_interfaces.py.

interface_selection.json was built against THIS SAME STEP file
(example_clean_PRONTO.stp) by select_interfaces_gui.py, so
InterfaceSelection.load_selected()'s key matching (volume pair + centroid,
see InterfaceSelection.key_for's docstring) should resolve cleanly - if it
raises "selection references interfaces not found," the geometry has
drifted from what was selected against (e.g. example_clean_PRONTO.stp was
regenerated) and the selection needs to be redone.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_full_aggregate_interfaces_clean", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
import numpy as np
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)
from core.opensees_generation.tcl_export import TclWriter

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
N_PARTS = 6
MODEL_PATH = "output/castelnuovo/full_aggregate_interfaces_clean_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_interfaces_clean"
GLOBAL_MESH_SIZE = 0.6
# Weighted-average of the 4 HMO/MQI-calibrated masonry types (materials.md):
# E = mean(1526.6, 1198.7, 987.8, 1198.7[type D=B]) = 1227.95 MPa, nu=0.2,
# rho=1450 kg/m3 - replaces the generic placeholder (700 MPa/0.25/2000
# kg/m3) copy-pasted across this pipeline; see
# self_weight_check_full_aggregate_clean.py's comment for the full
# rationale and the open per-facade-mapping question this sidesteps.
E, nu, rho = 1227.95e6, 0.2, 1450.0
G_ACCEL = 9.81

# gmsh screenshots (the same technique scripts/select_interfaces_gui.py
# uses) do NOT work in this container - gmsh.write() hangs indefinitely
# under its Xvfb/software-OpenGL stack, confirmed by isolated testing even
# for a trivial one-box scene with LIBGL_ALWAYS_SOFTWARE=1 set
# (fltk.initialize() itself is fast; write() alone hangs). Real gmsh
# renders for this project happen locally on Windows instead - see
# scripts/render_partition_views.py, which this script exports data for
# below (search "partition_export_path").

with apeGmsh(model_name="full_aggregate_interfaces_clean") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded (cleaned geometry, expect ~279)")

    total_volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in all_vols)
    print(f"Total volume (gmsh): {total_volume:.2f} m^3")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidates detected")

    # The REAL selection made interactively against this same geometry -
    # non-interactive here since the file already exists (see
    # InterfaceSelection.select_interactive_or_cached's docstring).
    selected = InterfaceSelection.select_interactive_or_cached(candidates, SELECTION_PATH)
    print(f"{len(selected)} interfaces selected (from {SELECTION_PATH}, "
          f"made with scripts/select_interfaces_gui.py)")
    assert len(selected) >= 1

    ContactInterfaceGenerator.tag_physical_groups(selected)

    g.parts.from_model("castelnuovo_full_clean")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")

    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)

    substitution = NodeSplitter.compute_node_map(gmsh.model, selected)

    # MUST run before partition() - gmsh.model.mesh.getElements(dim=3, tag=vol)
    # silently returns empty for volumes after partitioning (same class of issue
    # as InterfaceDetection.find_touching_surface_pairs() after partition() -
    # found the hard way: this returned 0 elements when computed inside
    # TclWriter.solid_elements(), called after partition() below). Needed to
    # scope node_substitution to each interface own split_volume - see that
    # method's docstring for the two real bugs this fixes.
    split_element_ids = set()
    for vol in substitution:
        _etypes, etags, _enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
        for tags in etags:
            split_element_ids.update(int(t) for t in tags)

    # Same reason, same fix, for the partition-map screenshot below: need
    # to know which volume each element belongs to, which only works
    # BEFORE partition() mutates gmsh's element/entity bookkeeping.
    volume_element_ids = {}
    for _dim, vol in all_vols:
        _etypes, etags, _enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
        ids = set()
        for tags in etags:
            ids.update(int(t) for t in tags)
        volume_element_ids[vol] = ids

    n_dup_total = sum(len(v) for v in substitution.values())
    print(f"{n_dup_total} duplicate nodes across {len(selected)} interfaces")

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

    # --- Partition-by-volume, exported for LOCAL gmsh rendering, NOT
    # rendered here - gmsh.write() (the headless screenshot call) hangs
    # indefinitely under this container's Xvfb/software-OpenGL stack, even
    # for a trivial one-box scene with LIBGL_ALWAYS_SOFTWARE=1 set
    # (confirmed by isolated testing - fltk.initialize() itself is fast,
    # write() alone hangs). Real gmsh screenshots for this project only
    # work locally on Windows (scripts/select_interfaces_gui.py etc.), so
    # instead of the render, this exports each VOLUME's centroid + which
    # MPI rank owns the majority of its elements (a per-element rendering
    # would be exact, but gmsh has no per-element "paint this tet" color
    # call - setColor only works on geometric entities, same trade-off
    # already made for the interface-picker GUI). Centroid, not volume
    # TAG, because tags aren't portable across apeGmsh/gmsh versions (see
    # InterfaceSelection.key_for's docstring for the same lesson, hit
    # first on interface selection) - scripts/render_partition_views.py
    # matches these back to ITS OWN local volumes by nearest centroid. ---
    rank_element_ids = {}
    for rank in range(N_PARTS):
        er = fem.elements.get(pg="Masonry", partition=rank + 1)
        ids = set()
        for group in er:
            for eid, _conn in group:
                ids.add(int(eid))
        rank_element_ids[rank] = ids
        print(f"  partition {rank}: {len(ids)} elements")

    volume_rank = {}
    for vol, elem_ids in volume_element_ids.items():
        if not elem_ids:
            continue
        counts = [(rank, len(elem_ids & rank_element_ids[rank])) for rank in range(N_PARTS)]
        volume_rank[vol] = max(counts, key=lambda t: t[1])[0]

    volume_partition_export = []
    for _dim, vol in all_vols:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(3, vol)
        volume_partition_export.append({
            "centroid": [cx, cy, cz],
            "rank": volume_rank.get(vol, 0),
        })
    import json as _json
    partition_export_path = "output/castelnuovo/plots/full_aggregate_interfaces_clean_partition_by_volume.json"
    with open(partition_export_path, "w") as _f:
        _json.dump(volume_partition_export, _f, indent=2)
    print(f"Wrote {partition_export_path} ({len(volume_partition_export)} volumes) - "
          f"render locally with scripts/render_partition_views.py")

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
                               node_substitution=substitution, split_element_ids=split_element_ids)
    writer.contact_elements(fem, selected, Kn_nominal=69000.0e9, Kt_nominal=0.001e9)
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

    # NewtonLineSearch + finer increments - the original
    # full_aggregate_with_interfaces.py used these from the start rather
    # than waiting to hit plain-Newton convergence trouble.
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

# Max |uz| straight from the (single-writer, rank 0) displacement recorder -
# last time step, every 3rd value after the leading time column (ux,uy,uz
# per node, all nodes of physical group "Masonry" in the order Recorders
# resolved them).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

with open(f"{RECORDER_DIR}/nodes_0_disp.out") as f:
    last_disp_line = [float(x) for x in f.readlines()[-1].split()]
uz_values = last_disp_line[3::3]  # skip leading time column, then every 3rd (ux,uy,UZ)
max_uz = min(uz_values)  # most negative = largest downward displacement
print(f"Max downward displacement (uz): {max_uz * 1000:.3f} mm")

# --- Self-weight vs reaction comparison chart - the numbers side by side,
# not just printed, per user request ("voglio che si veda... che combacia"). ---
fig_w, ax_w = plt.subplots(figsize=(5, 4))
bars = ax_w.bar(["Calculated\n(ρ·g·V)", "Analysis\n(Σ base reactions)"],
                 [total_weight / 1000, total_reaction / 1000],
                 color=["#4C72B0", "#55A868"], width=0.5)
for b, v in zip(bars, [total_weight / 1000, total_reaction / 1000]):
    ax_w.text(b.get_x() + b.get_width() / 2, v, f"{v:,.1f} kN",
               ha="center", va="bottom", fontsize=10)
ax_w.set_ylabel("Total vertical force (kN)")
ax_w.set_title(f"Self-weight check - {abs(err_same_sign):.3f}% difference")
ax_w.set_ylim(0, max(total_weight, total_reaction) / 1000 * 1.15)
weight_chart_path = "output/castelnuovo/plots/full_aggregate_interfaces_clean_weight_check.png"
fig_w.savefig(weight_chart_path, dpi=150, bbox_inches="tight")
print(f"Wrote {weight_chart_path}")

# --- Results summary - JSON, not a PNG table this time: user wants tables
# in the actual thesis Word document (scripts/build_results_docx.py, run
# locally, reads this file), not as flat images. ---
summary = {
    "volumes": len(all_vols),
    "candidate_interfaces": len(candidates),
    "selected_interfaces": len(selected),
    "duplicate_nodes": n_dup_total,
    "mesh_nodes": len(fem.nodes.ids),
    "mesh_elements": len(fem.elements.ids),
    "mpi_ranks": N_PARTS,
    "ground_bearing_volumes": len(ground_volumes),
    "base_fixed_nodes": int(len(base_ids_all)),
    "converged_all_ranks": bool(all(ok == "0" for ok in reports)),
    "total_volume_m3": total_volume,
    "self_weight_calculated_N": total_weight,
    "total_base_reaction_N": total_reaction,
    "weight_reaction_diff_pct": err_same_sign,
    "max_downward_displacement_mm": max_uz * 1000.0,
    "n_parts": N_PARTS,
}
import json
summary_path = "output/castelnuovo/plots/full_aggregate_interfaces_clean_summary.json"
with open(summary_path, "w") as f:
    json.dump(summary, f, indent=2)
print(f"Wrote {summary_path}")

print("\nLoading results via apeGmsh.Results.from_recorders()...")
results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
print(results)

# --- Deformed shape - matplotlib (gmsh screenshot ruled out in this
# container, see the partition-export comment above). Tried a flat,
# edgeless, no-ghost rendering first (ghost=False, edge_color=None) -
# reads as a featureless coloured blob, no sense of the actual building
# geometry. Fixed by going back to apeGmsh's own defaults instead of
# overriding them away: edge_color draws the mesh/face edges (the real
# geometric lines - walls, openings, floor lines), ghost=True overlays the
# undeformed shape in light grey so the warp reads clearly against it.
# Font sizes trimmed down afterward - the default axis/tick labels read
# oversized against a plot this size. ---
DEFORM_SCALE = 200.0
ax = results.plot.deformed(
    component="displacement_z", scale=DEFORM_SCALE,
    cmap="Blues", edge_color="#3a3a3a", linewidth=0.25, ghost=True,
)
ax.set_title(
    f"Castelnuovo full aggregate + {len(selected)} Task A interfaces - "
    f"self-weight, deformed ×{DEFORM_SCALE:g}",
    fontsize=10,
)
ax.set_xlabel("X", fontsize=8)
ax.set_ylabel("Y", fontsize=8)
ax.set_zlabel("Z", fontsize=8)
for axis in ax.figure.axes:
    axis.tick_params(labelsize=7)
    if axis is not ax:
        axis.set_ylabel(axis.get_ylabel(), fontsize=8)  # colorbar label
deformed_path = "output/castelnuovo/plots/full_aggregate_interfaces_clean_deformed_uz.png"
ax.figure.savefig(deformed_path, dpi=200, bbox_inches="tight")
print(f"Wrote {deformed_path}")

print("\nDone.")
