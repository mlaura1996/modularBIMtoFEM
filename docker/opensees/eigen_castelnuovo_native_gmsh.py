"""
Self-weight + eigenvalue analysis of the full Castelnuovo aggregate (bonded,
no Task A interfaces), rebuilt on the user's OWN established framework
(plain gmsh + external/gmsh2opensees + core/opensees_generation/
model_builder.py + openseespy, the same stack main.py/in_plane_wall.py use)
instead of apeGmsh + TclWriter + OpenSeesMP - per explicit request: "rifai
l'analisi anche solo con gmsh nel mio framework normale senza ape visto che
le eigenvalue le facciamo sequenziali" - the eigenvalue solve was already
confirmed to need N_PARTS=1 (no MPI domain decomposition) regardless of
mesh size, so there is no parallel-partitioning benefit apeGmsh's TCL
export gives up by dropping it here; this stays fully sequential/headless
(no gmsh.fltk.run() - those block for an interactive window, fine for her
local workflow, not for a Docker run) and uses openseespy directly (Python
return values for eigenvalues/eigenvectors, no TCL recorder files to
parse).

Material: the weighted average of the 4 HMO/MQI-calibrated masonry types
(docs/source/case_study/materials.md) - E = mean(1526.6, 1198.7, 987.8,
1198.7[type D=B]) = 1227.95 MPa, nu = 0.2, rho = 1450 kg/m^3 - replacing
the generic placeholder (700 MPa/0.25/2000 kg/m^3) used throughout the
apeGmsh pipeline. Equal-weighted across the 4 types since a real per-
facade material assignment needs a volume<->facade mapping that doesn't
exist yet (docs/source/case_study/open_questions.md #6).

Ground-bearing base fixity reuses core.mesh_generation.wall_interfaces.
InterfaceDetection as-is - it's written directly against gmsh.model.* calls,
with no apeGmsh dependency, so it works identically here.

Writes output/castelnuovo/recorders_castelnuovo_native/:
  - eigenvalues.txt, modal_properties.txt (same layout/parsing as the
    apeGmsh/TCL pipeline's eigen scripts)
  - mode<k>_eigenvector.txt - node_id,ux,uy,uz per line (plain text, not
    the TCL recorder's flat single-line format - openseespy hands back
    ops.nodeEigenvector(tag, mode, dof) directly per node, no file-based
    recorder involved at all)
  - node_coords.txt - node_id,x,y,z (undeformed), so a separate plotting
    script can rebuild geometry without re-meshing
  - summary.json
"""
import json
import math
import os
import sys

sys.path.insert(0, "/app")
OUT_DIR = "output/castelnuovo/recorders_castelnuovo_native"
os.makedirs(OUT_DIR, exist_ok=True)

import numpy as np
import gmsh
import openseespy.opensees as ops

from external.gmsh2opensees.g2o_nodes_functions import (
    get_all_nodes, add_nodes_to_ops, fix_nodes, get_eigenvector_at_nodes,
    get_displacements_at_nodes,
)
from core.opensees_generation.model_builder import ModelBuilder, Element
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
GLOBAL_MESH_SIZE = 0.6
N_MODES = 10
E_MPA, NU, RHO = 1227.95, 0.2, 1450.0  # see module docstring for the weighted-average derivation
G_ACCEL = -9.81  # matches core.config.G's sign convention (negative = -z)

# --- 1. Mesh (plain gmsh, headless - no gmsh.fltk.run()) ------------------
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("castelnuovo_native")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

all_vols = gmsh.model.getEntities(3)
vol_tags = [t for _, t in all_vols]
print(f"{len(vol_tags)} volumes loaded.")
total_volume = sum(gmsh.model.occ.getMass(3, t) for t in vol_tags)
print(f"Total volume: {total_volume:.2f} m^3")

pg_tag = gmsh.model.addPhysicalGroup(3, vol_tags)
gmsh.model.setPhysicalName(3, pg_tag, "Masonry")

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)

gmsh.model.mesh.setOrder(1)  # Element.create_linear_elastic_element needs Tet4, not Tet10
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)
gmsh.model.mesh.generate(3)
print("Meshing done.")

# --- 2. OpenSees model (her framework: ModelBuilder + Element + g2o) -----
ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

node_tags_all, node_coords_all = get_all_nodes(gmsh.model)
add_nodes_to_ops(node_tags_all, gmsh.model)
print(f"{len(node_tags_all)} nodes added to OpenSees.")

# g2o's get_displacements_at_nodes/get_eigenvector_at_nodes both call
# numpy.unique() on the node-tag list internally, which SORTS it - fix the
# canonical node order to that same sorted order everywhere below (coords,
# self-weight displacement, every mode's eigenvector), so row i means the
# same node in every one of these files without relying on get_all_nodes's
# own (not guaranteed sorted) return order.
node_tags_sorted = np.array(sorted(int(t) for t in node_tags_all), dtype=np.int64)
coord_by_tag = {int(t): c for t, c in zip(node_tags_all, node_coords_all)}
node_coords_sorted = np.array([coord_by_tag[int(t)] for t in node_tags_sorted])

material = Material(
    name="Masonry", density=RHO, young_modulus=E_MPA, poisson_ratio=NU,
    is_structural=True, material_model_type="LinearElastic",
    compressive_strength=0, tensile_strength=0,
    compression_fracture_energy=0, tensile_fracture_energy=0,
    compressive_elastic_behaviour=0,
)
element_tags = Element.add_elements_to_opensees(gmsh.model, {"Masonry": material})
print(f"{len(element_tags)} elements added to OpenSees "
      f"(self-weight body force baked directly into each element - "
      f"bx=by=0, bz=rho*G - same convention the apeGmsh/TCL pipeline used, "
      f"no separate eleLoad/pattern needed).")

# --- 3. Ground-bearing base fixity (reuses InterfaceDetection as-is) -----
node_z_by_tag = {int(t): float(c[2]) for t, c in zip(node_tags_all, node_coords_all)}

volume_node_ids = {}
volume_z_ranges = {}
for vol in vol_tags:
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
fix_nodes(base_ids_all, "XYZ")

# --- 4. Static self-weight solve ------------------------------------------
# Self-weight is already baked into every element's body force (step 2) -
# no load pattern needed, a single equilibrium solve is enough (there is no
# incremental/ramped load to step through, unlike a pattern-based load).
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Plain")
ops.test("NormDispIncr", 1e-6, 30, 1)
ops.algorithm("Newton")
ops.integrator("LoadControl", 1.0)
ops.analysis("Static")
ok = ops.analyze(1)
print(f"Static self-weight analysis returned: {ok}")
assert ok == 0, f"static analysis did not converge (ok={ok})"

ops.reactions()
total_reaction = sum(ops.nodeReaction(int(n), 3) for n in base_ids_all)
total_weight = RHO * (-G_ACCEL) * total_volume
err_pct = 100.0 * (total_reaction - total_weight) / total_weight
print(f"Self-weight calculated (rho*g*V): {total_weight:.1f} N")
print(f"Total vertical base reaction:      {total_reaction:.1f} N")
print(f"Difference: {err_pct:.3f}%")

selfweight_disp = get_displacements_at_nodes(node_tags_sorted)  # (N,3), rows match node_tags_sorted
with open(f"{OUT_DIR}/selfweight_displacement.txt", "w") as f:
    for tag, d in zip(node_tags_sorted, selfweight_disp):
        f.write(f"{int(tag)},{float(d[0])!r},{float(d[1])!r},{float(d[2])!r}\n")
print(f"Wrote {OUT_DIR}/selfweight_displacement.txt")

# --- 5. Eigenvalue analysis ------------------------------------------------
eigenvalues = ops.eigen(N_MODES)
print(f"Eigenvalues: {eigenvalues}")
with open(f"{OUT_DIR}/eigenvalues.txt", "w") as f:
    for lam in eigenvalues:
        f.write(f"{lam}\n")

modal_props_path = os.path.abspath(f"{OUT_DIR}/modal_properties.txt")
ops.modalProperties("-print", "-file", modal_props_path)
print(f"Wrote {modal_props_path}")

# Undeformed node coordinates, for a separate plotting script - sorted
# order, matching get_displacements_at_nodes/get_eigenvector_at_nodes's own
# internal numpy.unique() sort (see the node_tags_sorted comment above).
with open(f"{OUT_DIR}/node_coords.txt", "w") as f:
    for tag, coord in zip(node_tags_sorted, node_coords_sorted):
        f.write(f"{int(tag)},{float(coord[0])!r},{float(coord[1])!r},{float(coord[2])!r}\n")

for mode in range(1, N_MODES + 1):
    disp = get_eigenvector_at_nodes(node_tags_sorted, mode=mode)
    path = f"{OUT_DIR}/mode{mode}_eigenvector.txt"
    with open(path, "w") as f:
        for tag, d in zip(node_tags_sorted, disp):
            f.write(f"{int(tag)},{float(d[0])!r},{float(d[1])!r},{float(d[2])!r}\n")
    print(f"Wrote {path}")

summary = {
    "framework": "native gmsh + external.gmsh2opensees + openseespy (sequential)",
    "young_modulus_MPa": E_MPA,
    "poisson_ratio": NU,
    "density_kg_m3": RHO,
    "total_volume_m3": total_volume,
    "self_weight_calculated_N": total_weight,
    "total_base_reaction_N": total_reaction,
    "weight_reaction_diff_pct": err_pct,
    "n_modes": N_MODES,
    "mesh_nodes": len(node_tags_all),
    "mesh_elements": len(element_tags),
    "global_mesh_size_m": GLOBAL_MESH_SIZE,
}
with open(f"{OUT_DIR}/summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"Wrote {OUT_DIR}/summary.json")

print("\nDone.")
