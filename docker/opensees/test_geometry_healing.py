"""
Finds a geometry-healing recipe that closes the disconnected wall
junctions, before committing the whole pipeline to a re-run.

Established so far (audit_wall_connectivity.py -> audit_solid_overlap.py ->
audit_junction_gaps.py -> test_boolean_tolerance.py):
  - ~21 wall-to-wall junctions have their two solids drawn 1.5 mm - 5 cm
    APART in the cleaned STEP, so fragment() correctly won't fuse them and
    those walls are structurally independent in the model.
  - Geometry.ToleranceBoolean (the tolerance used DURING booleans) recovers
    at most 10 of 21, even at 5 cm.

This tries the other lever: Geometry.Tolerance, the tolerance OCC uses when
READING the STEP - it has to be set before gmsh.open() to have any effect,
which is why it wasn't covered by the previous sweep - plus OCC's shape-
healing switches (OCCSewFaces, OCCFixSmallEdges/Faces, OCCMakeSolids), on
their own and combined with the boolean tolerance.

For each recipe it reports the things that decide whether it is usable:
  - volumes: must stay at 279; a drop means OCC merged or dropped solids
  - total volume: must stay ~623.06 m3; a drop means mass was lost
  - touching pairs / of the 21 known gaps fused: what we are trying to fix

Prints only.
"""
import sys

sys.path.insert(0, "/app")

import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
BASELINE_VOLUMES = 279
BASELINE_TOTAL = 623.0566

KNOWN_GAPS = [
    (81, 101), (91, 102), (91, 103), (92, 102), (92, 103), (81, 102),
    (91, 101), (107, 118), (105, 107), (107, 110), (85, 111), (89, 111),
    (96, 107), (99, 107), (104, 106), (107, 281), (107, 280), (91, 107),
    (92, 107), (59, 115), (106, 107),
]

# (label, {option: value} applied BEFORE gmsh.open(), {option: value} applied after)
RECIPES = [
    ("baseline", {}, {}),
    ("Tolerance=5mm", {"Geometry.Tolerance": 5e-3}, {}),
    ("Tolerance=2cm", {"Geometry.Tolerance": 2e-2}, {}),
    ("Tolerance=5cm", {"Geometry.Tolerance": 5e-2}, {}),
    ("Tolerance=5cm + Boolean=5cm",
     {"Geometry.Tolerance": 5e-2, "Geometry.ToleranceBoolean": 5e-2}, {}),
    ("Tolerance=5cm + Sew + MakeSolids",
     {"Geometry.Tolerance": 5e-2, "Geometry.OCCSewFaces": 1,
      "Geometry.OCCMakeSolids": 1}, {}),
    ("Tolerance=5cm + Sew + FixSmall + Boolean=5cm",
     {"Geometry.Tolerance": 5e-2, "Geometry.OCCSewFaces": 1,
      "Geometry.OCCFixSmallEdges": 1, "Geometry.OCCFixSmallFaces": 1,
      "Geometry.ToleranceBoolean": 5e-2}, {}),
]

print(f"{'recipe':>44}  {'vols':>5}  {'total vol':>10}  {'pairs':>6}  {'gaps fused':>11}")
print("-" * 88)

for label, pre_opts, post_opts in RECIPES:
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        for k, v in pre_opts.items():
            gmsh.option.setNumber(k, v)
        gmsh.model.add(label.replace(" ", "_"))
        gmsh.open(STEP_PATH)
        for k, v in post_opts.items():
            gmsh.option.setNumber(k, v)
        gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
        gmsh.model.occ.synchronize()

        vols = gmsh.model.getEntities(3)
        total_vol = sum(gmsh.model.occ.getMass(3, t) for _, t in vols)

        candidates = InterfaceDetection.find_touching_surface_pairs()
        pairs = set()
        for c in candidates:
            pairs.add((min(c["volume_a"], c["volume_b"]),
                       max(c["volume_a"], c["volume_b"])))
        fused = sum(1 for a, b in KNOWN_GAPS if (min(a, b), max(a, b)) in pairs)

        flag = ""
        if len(vols) != BASELINE_VOLUMES:
            flag += f"  [volumes {len(vols)-BASELINE_VOLUMES:+d} - tags shifted, "
            flag += "gap count unreliable]"
        if abs(total_vol - BASELINE_TOTAL) > 0.5:
            flag += f"  [MASS CHANGED {total_vol-BASELINE_TOTAL:+.2f} m3]"

        print(f"{label:>44}  {len(vols):5d}  {total_vol:10.2f}  {len(pairs):6d}  "
              f"{fused:5d} / {len(KNOWN_GAPS)}{flag}")
    except Exception as e:
        print(f"{label:>44}  FAILED: {e}")
    finally:
        gmsh.finalize()

print("\nDone.")
