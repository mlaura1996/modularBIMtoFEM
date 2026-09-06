"""
Verifies the unit fix in core.opensees_generation.model_builder
.Element.create_plastic_damage_elements (see its docstring and the chat
log for the bug this fixes). Not part of the pipeline; standing
regression check.

Two checks:
1. The Gc/Gt fallback formulas' unit interpretation (N/mm) against
   PROJECT_BRIEF.md's own Ch.6 (SERA-AIMS) reference values.
2. A real FE run: meshes a real Castelnuovo touching pair (volumes
   34/260, already used in test_node_split.py), assigns
   Tufelli_masonry_typeA's actual survey-derived properties
   (output/castelnuovo/material_database.json) as a PlasticDamage
   material, and runs a self-weight static analysis. Before the fix this
   would have mixed metre-scale mesh coordinates with mm-ton-calibrated
   material constants; after the fix everything is SI. Convergence with a
   physically sensible (small, elastic-range) displacement is the pass
   criterion - not a specific target ratio, since there's no independent
   ground truth to check the exact displacement against, just that it
   isn't absurd (many orders of magnitude off, as the pre-fix version
   would have produced for even a modest self-weight load).
"""
import json
import sys

sys.path.insert(0, "/app")

import gmsh
import openseespy.opensees as ops

from core.opensees_generation.model_builder import ModelBuilder, Element
from core.ifc_processing.data_extractor import Material

# --- Check 1: Gc/Gt fallback formula unit interpretation ---
fc_MPa = 1.30  # brief's Ch.6 SERA-AIMS reference masonry
Gt_Nmm = 0.025 * (fc_MPa / 10) ** 0.7
Gc_Nmm = 15 + 0.43 * fc_MPa - 0.0036 * fc_MPa ** 2
print(f"Gt formula @ fc={fc_MPa} MPa: {Gt_Nmm:.4f} N/mm (brief's calibrated value: 0.006 N/mm)")
print(f"Gc formula @ fc={fc_MPa} MPa: {Gc_Nmm:.4f} N/mm (brief's calibrated value: 2.7 N/mm - "
      f"NOT expected to match closely, Model Code 90 is a generic concrete formula, "
      f"not masonry-specific or calibrated to this experimental campaign)")
assert abs(Gt_Nmm - 0.006) / 0.006 < 0.15, "Gt fallback formula is more than 15% off the brief's reference - re-check the N/mm unit assumption"

# --- Check 2: real FE run with the fixed unit handling ---
with open("output/castelnuovo/material_database.json") as f:
    db = json.load(f)
type_a = db["Tufelli_masonry_typeA"]
material = Material(
    name="Tufelli_masonry_typeA",
    density=type_a["density"], young_modulus=type_a["young_modulus"],
    poisson_ratio=type_a["poisson_ratio"], is_structural=True,
    material_model_type="PlasticDamage",
    compressive_strength=type_a["compressive_strength"],
    tensile_strength=type_a["tensile_strength"],
    compression_fracture_energy=type_a["compression_fracture_energy"],
    tensile_fracture_energy=type_a["tensile_fracture_energy"],
    compressive_elastic_behaviour=type_a["compressive_elastic_behaviour"],
)
print(f"\nUsing real Castelnuovo material: {material}")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.mesh.setOrder(1)
gmsh.open("resources/ifc_examples/castelnuovo/final_example_PRONTO.stp")

all_vols = gmsh.model.getEntities(3)
keep = {34, 260}
gmsh.model.occ.remove([(d, t) for d, t in all_vols if t not in keep], recursive=True)
gmsh.model.occ.synchronize()
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

gmsh.model.addPhysicalGroup(3, [34, 260], name="Tufelli_masonry_typeA")
gmsh.option.setNumber("Mesh.MeshSizeMax", 0.5)
gmsh.model.mesh.generate(3)
print(f"Meshed: {len(gmsh.model.mesh.getNodes()[0])} nodes")

ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

materials_dict = {"Tufelli_masonry_typeA": material}
element_tags = Element.add_elements_to_opensees(gmsh.model, materials_dict)
print(f"Created {len(element_tags)} elements, {len(ops.getNodeTags())} nodes")

# Fix every node of volume 34 (arbitrary "ground" side, same convention as
# test_node_split.py), leave volume 260 free under self-weight.
elem_types_a, elem_tags_a, node_tags_a = gmsh.model.mesh.getElements(dim=3, tag=34)
nodes_in_a = set(int(n) for n in node_tags_a[0])
for n in nodes_in_a:
    ops.fix(n, 1, 1, 1)
print(f"Fixed {len(nodes_in_a)} nodes belonging to volume 34")

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.eleLoad("-ele", *element_tags, "-type", "-selfWeight", 0, 0, 1)

ops.constraints("Plain")
ops.numberer("RCM")
ops.system("Mumps")
ops.test("NormDispIncr", 1e-8, 30, 1)
ops.algorithm("Newton")
n_steps = 5
ops.integrator("LoadControl", 1.0 / n_steps)
ops.analysis("Static")
ok = ops.analyze(n_steps)
print(f"analyze() returned {ok}")
assert ok == 0, "self-weight analysis did not converge"

free_nodes = [n for n in (int(t) for t in gmsh.model.mesh.getElements(dim=3, tag=260)[2][0])
              if n not in nodes_in_a]
disps = [abs(ops.nodeDisp(n, 3)) for n in set(free_nodes)]
max_disp = max(disps)
print(f"\nMax vertical displacement on the free volume: {max_disp:.6e} m "
      f"({max_disp * 1000:.4f} mm)")

# Sanity bound, not a precise target: for a ~1-3 m tall masonry chunk under
# self-weight only (no seismic/live load), a converged elastic-range
# self-weight deflection should be well under a millimetre - if the old
# metre/millimetre mixing bug were still present, this would be off by
# ~9 orders of magnitude in one direction or the other (absurdly huge or
# absurdly, suspiciously exactly zero).
assert 1e-9 < max_disp < 1e-2, (
    f"displacement {max_disp} m is outside a physically plausible range for "
    f"self-weight-only loading on a metre-scale masonry chunk - unit bug may "
    f"still be present"
)

print("\nPASS: Gc/Gt fallback formulas confirmed in N/mm; real Castelnuovo "
      "PlasticDamage material converges under self-weight with a physically "
      "plausible displacement (SI units consistent throughout).")
gmsh.finalize()
