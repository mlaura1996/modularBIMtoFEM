"""Writes the material of every volume of the Castelnuovo STEP geometry.

    python scripts/map_castelnuovo_volume_materials.py

The prepared STEP geometry (example_clean_PRONTO.stp) has lost the IFC
labels of its solids, so the analyses could only give all of them one
averaged masonry material. Each volume is matched here to the IFC element
it comes from (core.ifc_processing.ifc_step_matching), and takes that
element's material, as recorded in example_clean.ifc, the model the STEP
geometry was produced from. The result is
resources/survey_data/castelnuovo/volume_materials.json, keyed by the
volume tags gmsh gives after the same open + fragment the analysis scripts
do, which the scripts read to build one physical group per material.
"""
import collections
import json
import sys

import gmsh

from core.ifc_processing.ifc_step_matching import assign_step_volumes_to_ifc_elements

def _argval(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


# --ifc and --out read another IFC model of the same geometry and write elsewhere
STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
IFC_PATH = _argval("--ifc", "resources/ifc_examples/castelnuovo/example_clean.ifc")
OUT = _argval("--out", "resources/survey_data/castelnuovo/volume_materials.json")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
vols = [t for _d, t in gmsh.model.getEntities(3)]
volume = {t: gmsh.model.occ.getMass(3, t) for t in vols}
assigned = assign_step_volumes_to_ifc_elements(IFC_PATH, vols)
gmsh.finalize()

doc = {"_meta": {"step": STEP_PATH, "ifc": IFC_PATH,
                 "description": "Material of each volume of the STEP geometry, from the IFC element it "
                                "comes from (centroid inside the element's solid, else the nearest element)."},
       "volumes": {str(t): {**assigned[t], "volume_m3": round(volume[t], 4)} for t in vols}}
json.dump(doc, open(OUT, "w", encoding="utf-8"), indent=1)

by_mat = collections.defaultdict(lambda: [0, 0.0])
for t in vols:
    by_mat[assigned[t]["material"]][0] += 1
    by_mat[assigned[t]["material"]][1] += volume[t]
how = collections.Counter(a["how"] for a in assigned.values())
print(f"{len(vols)} volumes: {dict(how)}")
for m, (n, v) in sorted(by_mat.items(), key=lambda x: -x[1][1]):
    print(f"  {m}: {n} volumes, {v:.2f} m^3")
far = [(t, a["distance"]) for t, a in assigned.items() if a.get("distance", 0) > 0.05]
print("nearest farther than 5 cm:", far[:20])
print("wrote", OUT)
