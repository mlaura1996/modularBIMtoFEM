"""
Standalone end-to-end test of the Task A node-split wiring (run inside the
Docker image, which has a working openseespy - broken on Windows locally).
Not part of the pipeline; delete after the wiring is trusted or keep as a
regression check, TBD.

Proves the split is real, not just "runs without error": fixes every node
that volume_a's elements reference, loads volume_b, and checks that (a) the
analysis converges, (b) an original interface node (now only referenced by
volume_a, which is fixed) has ~zero displacement, while (c) its duplicate
(referenced by volume_b's elements, connected back to the original only
through the zeroLengthContactASDimplex) moves under load. If the
substitution silently failed, original and duplicate would be the same
node and (b)/(c) would be identical/degenerate instead of different.
"""
import sys
sys.path.insert(0, '/app')

import gmsh
import numpy as np
import openseespy.opensees as ops

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, ContactInterfaceGenerator, NodeSplitter,
)
from core.opensees_generation.model_builder import ModelBuilder, Element
from core.ifc_processing.data_extractor import Material

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.mesh.setOrder(1)
gmsh.open("resources/ifc_examples/castelnuovo/final_example_PRONTO.stp")
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)
test_candidate = next(c for c in candidates if c["volume_a"] == 34 and c["volume_b"] == 260)
print(f"Testing interface {test_candidate['volume_a']}-{test_candidate['volume_b']}, "
      f"area={test_candidate['area_m2']:.3f} m2, normal={test_candidate['normal']}")

vol_a, vol_b = test_candidate["volume_a"], test_candidate["volume_b"]
all_vols = [t for d, t in gmsh.model.getEntities(3)]
gmsh.model.occ.remove([(3, v) for v in all_vols if v not in (vol_a, vol_b)], recursive=True)
gmsh.model.occ.synchronize()

gmsh.model.addPhysicalGroup(3, [vol_a, vol_b], name="TestMaterial")
ContactInterfaceGenerator.tag_physical_groups([test_candidate])

gmsh.option.setNumber("Mesh.MeshSizeMax", 0.3)
gmsh.model.mesh.generate(3)
print(f"Meshed: {len(gmsh.model.mesh.getNodes()[0])} nodes")

material = Material(
    name="TestMaterial", density=2000.0, young_modulus=700.0, poisson_ratio=0.2,
    is_structural=True, material_model_type="LinearElastic",
    compressive_strength=0, tensile_strength=0, compression_fracture_energy=0,
    tensile_fracture_energy=0, compressive_elastic_behaviour=0,
)
materials_dict = {"TestMaterial": material}

ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

substitution = NodeSplitter.create_duplicate_nodes(gmsh.model, [test_candidate])
n_dup = sum(len(v) for v in substitution.values())
print(f"Created {n_dup} duplicate nodes for volume {test_candidate['split_volume']}")

element_tags = Element.add_elements_to_opensees(gmsh.model, materials_dict, node_substitution=substitution)
print(f"Created {len(element_tags)} solid elements")

# Brief's Kn=69000/Kt=0.001 are per-unit-area penalty stiffnesses in the
# N-mm-t system Ch.6/7 uses. This test's geometry/material are in the
# SI-meter system core/config.py's create_linear_elastic_element assumes
# (E converted to Pa). 1 N/mm^3 = 1e9 N/m^3, so the per-area stiffness
# needs the same 1e9 scaling, or the contact springs end up ~9 orders of
# magnitude too soft relative to the solid (E=700 MPa) - unit-inconsistent,
# so keep this scaling regardless of what else is going on. NOTE: this was
# NOT the cause of the exact-zero-displacement bug seen while developing
# this test (that was node-tag collision - see NodeSplitter.TAG_OFFSET's
# docstring); fixing units alone, before the tag fix, left the same 53/285
# nodes at exactly 0.0 - only the tag fix resolved it (285/285 now move).
Kn_nominal_SI = 69000.0 * 1e9
Kt_nominal_SI = 0.001 * 1e9
contact_results = ContactInterfaceGenerator.generate([test_candidate], Kn_nominal=Kn_nominal_SI, Kt_nominal=Kt_nominal_SI)
n_contact = len(contact_results[0]["elements"])
print(f"Created {n_contact} zeroLengthContactASDimplex elements")

# --- Sanity check on the substitution itself, before running anything ---
node_map = test_candidate["node_map"]
sample_orig, sample_dup = next(iter(node_map.items()))
assert sample_orig != sample_dup, "duplicate tag must differ from original"
assert sample_dup in ops.getNodeTags(), "duplicate node was not actually created in OpenSees"
print(f"Sample pair: original={sample_orig}, duplicate={sample_dup} - both exist, tags differ. OK.")

# --- Fix every node volume_a's elements touch (all of volume_a's nodes,
# including the un-substituted originals at the interface); load volume_b ---
elem_types_a, elem_tags_a, node_tags_a = gmsh.model.mesh.getElements(dim=3, tag=vol_a)
nodes_in_a = set(int(n) for n in node_tags_a[0])
for n in nodes_in_a:
    ops.fix(n, 1, 1, 1)
print(f"Fixed {len(nodes_in_a)} nodes belonging to volume {vol_a} (the anchored side)")

elem_types_b, elem_tags_b, node_tags_b = gmsh.model.mesh.getElements(dim=3, tag=vol_b)
nodes_in_b_raw = set(int(n) for n in node_tags_b[0])
# after substitution, volume_b's connectivity uses duplicate tags at the
# interface - the "raw" gmsh node tags for volume_b's far side (untouched
# by substitution) are still valid OpenSees node tags to load directly
far_nodes_b = [n for n in nodes_in_b_raw if n not in node_map]
load_node = far_nodes_b[0]

print(f"DEBUG: total OpenSees nodes = {len(ops.getNodeTags())}, total elements = {len(ops.getEleTags())}")
print(f"DEBUG: nodes_in_a = {len(nodes_in_a)}, nodes_in_b_raw = {len(nodes_in_b_raw)}, "
      f"far_nodes_b = {len(far_nodes_b)}, node_map size = {len(node_map)}")
print(f"DEBUG: load_node={load_node} in ops.getNodeTags()? {load_node in ops.getNodeTags()}")
print(f"DEBUG: load_node in nodes_in_a (should be False)? {load_node in nodes_in_a}")

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(load_node, 0.0, 0.0, -1000.0)

ops.system("Mumps")
ops.numberer("RCM")
ops.constraints("Plain")
ops.test("NormDispIncr", 1e-8, 20, 1)
ops.algorithm("Newton")
ops.integrator("LoadControl", 1.0)
ops.analysis("Static")
ok = ops.analyze(1)
print(f"analyze() returned {ok}")
assert ok == 0, "analysis did not converge"

load_node_disp = ops.nodeDisp(load_node, 3)
print(f"DEBUG: load_node {load_node} itself: disp_z = {load_node_disp}")

# Check every duplicate node's displacement, and whether it's actually
# referenced by any element in the domain (vs. an orphaned node that
# exists but nothing connects to).
elem_types_b2, elem_tags_b2, node_tags_b2_sub = gmsh.model.mesh.getElements(dim=3, tag=vol_b)
# re-derive volume_b's post-substitution connectivity the same way Element._get_volume_elements does
_, nnodes_b = gmsh.model.mesh.getElementProperties(elem_types_b2[0])[1], None
raw_conn_b = np.array(node_tags_b2_sub[0], dtype=int).reshape((-1, 4))
sub_conn_b = np.array([[node_map.get(int(n), int(n)) for n in row] for row in raw_conn_b])
referenced_dups = set(sub_conn_b.flatten().tolist()) & set(node_map.values())
print(f"DEBUG: {len(referenced_dups)} / {len(node_map)} duplicate nodes are actually referenced "
      f"by a volume_b element")

# Real proof of decoupling: compare the FULL displacement vector (not one
# arbitrary component) of every original/duplicate pair. original is fixed
# (all zero, by construction); if the pair is truly split, the duplicate's
# vector should differ from it (a relative gap/slip opened at the joint).
# A single-component check at an arbitrary node is too weak - a concentrated
# point load decays fast (St. Venant), so many nodes legitimately show ~0
# in one component while moving in another.
n_relative_motion = 0
max_relative = 0.0
for orig, dup in node_map.items():
    orig_vec = np.array([ops.nodeDisp(orig, i) for i in (1, 2, 3)])
    dup_vec = np.array([ops.nodeDisp(dup, i) for i in (1, 2, 3)])
    rel = np.linalg.norm(dup_vec - orig_vec)
    max_relative = max(max_relative, rel)
    if rel > 1e-12:
        n_relative_motion += 1

print(f"DEBUG: {n_relative_motion} / {len(node_map)} pairs show nonzero relative "
      f"displacement (original vs duplicate); max relative = {max_relative:.6e}")

assert n_relative_motion > 0, (
    "no original/duplicate pair shows any relative displacement - the split is "
    "NOT decoupling the sides (every duplicate is moving in lockstep with its "
    "original, as if they were still the same shared node)"
)
assert n_relative_motion == len(node_map), (
    f"only {n_relative_motion}/{len(node_map)} pairs show relative motion - expected "
    f"all of them to differ from their (fixed, zero) original, even if only slightly"
)

print("\nPASS: node split confirmed - every original/duplicate pair shows independent "
      "displacement (the duplicate moved under load while its original stayed fixed at "
      "zero), proving they are separate DOFs connected only through the contact element, "
      "not a single shared node.")

gmsh.finalize()
