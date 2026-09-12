"""
Exports the EXACT mesh eigen_castelnuovo_native_gmsh.py analysed, as a
.msh file, so scripts/view_results_gmsh.py can load the results into a
local interactive gmsh window without re-meshing (the local
castelnuovo_viewer environment pins a different gmsh version than this
image, and node numbering is not guaranteed to survive that - loading the
analysed mesh itself sidesteps the question entirely).

Re-meshes with the same settings as the eigen script and then ASSERTS the
node tags/coordinates match its node_coords.txt exactly before writing -
if that assertion ever fails, the mesh is not reproducible from the same
inputs and the eigen script itself would need to write the .msh directly.
"""
import os
import sys

sys.path.insert(0, "/app")

import numpy as np
import gmsh

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
DATA_DIR = "output/castelnuovo/recorders_castelnuovo_native"
MSH_PATH = f"{DATA_DIR}/castelnuovo_native.msh"
GLOBAL_MESH_SIZE = 0.6


def parse_float(s):
    s = s.strip()
    if s.startswith("np.float64(") and s.endswith(")"):
        s = s[len("np.float64("):-1]
    return float(s)


gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("castelnuovo_native")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

all_vols = gmsh.model.getEntities(3)
vol_tags = [t for _, t in all_vols]
pg_tag = gmsh.model.addPhysicalGroup(3, vol_tags)
gmsh.model.setPhysicalName(3, pg_tag, "Masonry")

gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)
gmsh.model.mesh.generate(3)

node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
coord_by_tag = {int(t): c for t, c in zip(node_tags, node_coords.reshape(-1, 3))}

ref_tags, ref_coords = [], []
with open(f"{DATA_DIR}/node_coords.txt") as f:
    for line in f:
        parts = line.strip().split(",")
        if len(parts) != 4:
            continue
        ref_tags.append(int(parts[0]))
        ref_coords.append([parse_float(parts[1]), parse_float(parts[2]), parse_float(parts[3])])
ref_tags = np.array(ref_tags, dtype=np.int64)
ref_coords = np.array(ref_coords)

assert len(ref_tags) == len(node_tags), (
    f"node count differs: mesh {len(node_tags)} vs results {len(ref_tags)} - "
    f"the analysed mesh is not reproducible from the same inputs"
)
missing = [int(t) for t in ref_tags if int(t) not in coord_by_tag]
assert not missing, f"{len(missing)} result node tags absent from the re-meshed model, e.g. {missing[:5]}"
max_dev = max(
    float(np.linalg.norm(coord_by_tag[int(t)] - c)) for t, c in zip(ref_tags, ref_coords)
)
assert max_dev < 1e-9, f"node coordinates differ by up to {max_dev:.3e} m"
print(f"Mesh reproduced exactly: {len(node_tags)} nodes, max coordinate deviation {max_dev:.3e} m")

gmsh.option.setNumber("Mesh.SaveAll", 1)
gmsh.write(MSH_PATH)
print(f"Wrote {MSH_PATH}")
gmsh.finalize()
