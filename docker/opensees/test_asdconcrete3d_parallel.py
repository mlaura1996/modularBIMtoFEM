"""
Closes the gap flagged in chat: Task A (wall-to-wall contact interfaces)
and Task B (apeGmsh partition + TCL + OpenSeesMP/Mumps) had only ever been
verified with a placeholder linear-elastic material
(test_task_ab_reconciled.py, test_task_ab_scaled.py) - never with the real
ASDConcrete3D damage-plasticity material and real Castelnuovo material
data together. This test does both at once, on the same 18-volume/6-
partition/2-interface cluster as test_task_ab_scaled.py, then adds a third
piece neither of those tests had: apeGmsh-based visualisation of the
result (headless, via apeGmsh's matplotlib-backed results.plot - no Qt/X11
needed), so the run produces an actual picture to look at, not just a
pass/fail assertion.

Analysis type: static, self-weight only (nonlinear, Newton). Not the full
TRBDF2 seismic dynamic analysis from PROJECT_BRIEF.md 4.4 - that depends on
open questions (ground motion record, boundary conditions, slab treatment)
that are not yet decided (see docs/source/case_study/open_questions.md).
This test isolates the one thing that was actually unverified: does
ASDConcrete3D behave correctly when combined with the partitioned/parallel
TCL path and Mumps, at all.

Material-model note: uses ONE shared ASDConcrete3D material/tag for the
whole "Masonry" physical group, with a single representative crack-band
length (from one real meshed element), unlike
core.opensees_generation.model_builder.Element.create_plastic_damage_elements
which gives every element its own tag and its own auto-regularised curve
(different elements have different volumes/side lengths). That per-element
approach isn't wired into TclWriter.solid_elements yet (single material_tag
per call) - fine for verifying the material+partition+solver combination
works at all, not a substitute for full per-element regularisation in a
real production run.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/recorders_parallel", exist_ok=True)
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

from core.config import G
from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)
from core.opensees_generation.tcl_export import TclWriter
from core.opensees_generation.model_builder import Element
from models.damage_law import ConstitutiveLaws
from utils.dict_helper import load_material_objects

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
N_PARTS = 6
MODEL_PATH = "output/castelnuovo/asdconcrete3d_parallel_model.tcl"
RECORDER_DIR = "output/castelnuovo/recorders_parallel"
CLUSTER_SIZE = 18

# --- Real Castelnuovo material (survey-derived, see docs/source/case_study/materials.md) ---
materials = load_material_objects("output/castelnuovo/material_database.json")
material = materials["Tufelli_masonry_typeA"]
print(f"Material: {material}")

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

with apeGmsh(model_name="asdconcrete3d_parallel") as g:
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

    # Same conservative subset as test_task_ab_scaled.py, same reasoning:
    # selecting every vertical joint on this cluster produces an
    # unrestrained mechanism under self-weight (see that test's comment).
    selected = vertical[:2]
    print(f"{len(candidates)} candidates, {len(vertical)} vertical_joint, "
          f"{len(selected)} selected")
    assert len(selected) >= 1

    ContactInterfaceGenerator.tag_physical_groups(selected)
    substitution = NodeSplitter.compute_node_map(gmsh.model, selected)
    n_dup_total = sum(len(v) for v in substitution.values())
    print(f"{n_dup_total} duplicate nodes across {len(selected)} interfaces")

    info = g.mesh.partitioning.partition(n_parts=N_PARTS)
    print(f"Partitioned into {N_PARTS} parts: {info.elements_per_partition}")
    assert len(info.elements_per_partition) == N_PARTS

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    # --- ASDConcrete3D curves: same SI-unit computation as
    # model_builder.py's create_plastic_damage_elements (post units-bug
    # fix), but with ONE representative side_length instead of a per-
    # element one - taken from a real element actually in this mesh, not
    # an assumed/target mesh size. ---
    masonry_result = fem.elements.get(pg="Masonry")
    first_eid = None
    for group in masonry_result:
        for eid, _conn in group:
            first_eid = int(eid)
            break
        if first_eid is not None:
            break
    assert first_eid is not None, "no elements found in 'Masonry' physical group"
    lch = Element.get_element_side_lenght([first_eid])[0]
    print(f"Representative element {first_eid}, side_length (lch) = {lch:.4f} m")

    fc_MPa = material.compressive_strength
    ft_MPa = material.tensile_strength
    Gc_Nmm = (float(material.compression_fracture_energy) if material.compression_fracture_energy
              else 15 + 0.43 * fc_MPa - 0.0036 * fc_MPa ** 2)
    Gt_Nmm = (float(material.tensile_fracture_energy) if material.tensile_fracture_energy
              else 0.025 * (fc_MPa / 10) ** 0.7)

    E = float(material.young_modulus) * 1e6
    fc = fc_MPa * 1e6
    ft = ft_MPa * 1e6
    Gc = Gc_Nmm * 1000
    Gt = Gt_Nmm * 1000
    nu = material.poisson_ratio
    rho = material.density
    f0 = (float(material.compressive_elastic_behaviour) * 1e6
          if material.compressive_elastic_behaviour else fc / 3)

    Te, Ts, Td = ConstitutiveLaws.ExponentialSoftening_Tension.tension(E, ft, Gt, lch)
    Ce, Cs, Cd = ConstitutiveLaws.BezierCurve_Compression.compression(E, f0, fc, Gc, lch)
    print(f"Tension curve: {len(Te)} points. Compression curve: {len(Ce)} points.")

    mat_tag = 1
    writer = TclWriter(ndm=3, ndf=3)
    writer.header()
    writer.nodes(fem)
    writer.duplicate_nodes(gmsh.model, selected)
    writer.material_asdconcrete3d(mat_tag, E, nu, Te, Ts, Td, Ce, Cs, Cd, lch, implex=True)
    for rank in range(N_PARTS):
        writer.solid_elements(fem, "Masonry", mat_tag, rank,
                               body_force=(0.0, 0.0, rho * G),
                               node_substitution=substitution)
    writer.contact_elements(fem, selected, Kn_nominal=69000.0e9, Kt_nominal=0.001e9)
    writer.fix(fem, "Fixed", dofs=[1, 1, 1])

    # --- Recorders, via apeGmsh's own spec/emitter (not hand-written),
    # so the output matches what Results.from_recorders() expects. ---
    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)
    for line in spec.to_tcl_commands(output_dir=RECORDER_DIR + "/", file_format="out"):
        writer.raw(line)

    # NewtonLineSearch + finer increments, same as test_task_ab_scaled.py -
    # this cluster's contact-connected topology needs it (plain Newton +
    # coarse steps diverged there with "Matrix is Singular Numerically").
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

print(f"\nPASS: ASDConcrete3D + {len(selected)} contact interface(s) + "
      f"N_PARTS={N_PARTS} partitioning + Mumps converged, verified independently "
      f"on every rank, via real OpenSeesMP mpirun -np {N_PARTS}.")

# --- Visualise with apeGmsh, headlessly (results.plot, not results.viewer -
# no Qt/X11 needed inside this container). ---
print("\nLoading results via apeGmsh.Results.from_recorders()...")
results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
print(results)

ax = results.plot.deformed(
    component="displacement_z", scale=1000.0, ghost=True,
    title="Castelnuovo cluster - self-weight, ASDConcrete3D - deformed shape (x1000), colored by Uz",
)
deformed_path = "output/castelnuovo/plots/asdconcrete3d_parallel_deformed_uz.png"
ax.figure.savefig(deformed_path, dpi=150, bbox_inches="tight")
print(f"Wrote {deformed_path}")

ax2 = results.plot.contour("displacement_z", deformed=False)
contour_path = "output/castelnuovo/plots/asdconcrete3d_parallel_contour_uz.png"
ax2.figure.savefig(contour_path, dpi=150, bbox_inches="tight")
print(f"Wrote {contour_path}")

print("\nDone - open the two PNGs under output/castelnuovo/plots/ to inspect the result.")
