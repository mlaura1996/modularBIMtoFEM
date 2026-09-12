"""
Can the disconnected wall junctions be healed by raising gmsh's boolean
tolerance?

audit_junction_gaps.py established that ~24 wall-to-wall junctions in the
cleaned STEP have the two solids drawn 1.5 mm - 10 cm APART, so fragment()
correctly refuses to fuse them and those walls end up structurally
independent (the "questo muro non e' connesso a quelli ortogonali" the
mode shapes show). Since the gaps are a source-geometry defect, the fix has
to either heal the geometry or make the boolean operation tolerant enough
to bridge them.

gmsh exposes Geometry.ToleranceBoolean for exactly this - the tolerance OCC
uses when deciding whether two entities coincide during a boolean. This
sweeps it and reports, for each value:
  - how many volumes survive (a too-large tolerance starts merging or
    degenerating things that should stay separate - the failure mode to
    watch for)
  - total volume (must stay ~constant; a drop means solids got swallowed)
  - how many volume PAIRS fragment() now sees as sharing topology
  - specifically, how many of the 24 known near-touching junctions got
    fused, and how many of the previously-fine 657 connected pairs survived

Prints only; changes nothing permanently.
"""
import sys

sys.path.insert(0, "/app")

import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
TOLERANCES = [None, 1e-3, 5e-3, 1e-2, 2e-2, 5e-2]

# The near-touching junctions audit_junction_gaps.py measured (gap < 5 cm),
# as (volume_a, volume_b, measured gap in m). Volume tags are stable for a
# given STEP + fragment in this image (verified repeatedly this session).
KNOWN_GAPS = [
    (81, 101, 0.001555), (91, 102, 0.001555), (91, 103, 0.003320),
    (92, 102, 0.003320), (92, 103, 0.003320), (81, 102, 0.003320),
    (91, 101, 0.003320), (107, 118, 0.004050), (105, 107, 0.005875),
    (107, 110, 0.005875), (85, 111, 0.006415), (89, 111, 0.006415),
    (96, 107, 0.011580), (99, 107, 0.011580), (104, 106, 0.019117),
    (107, 281, 0.031595), (107, 280, 0.031881), (91, 107, 0.042340),
    (92, 107, 0.042340), (59, 115, 0.043694), (106, 107, 0.046853),
]

print(f"{'tolerance':>12}  {'volumes':>8}  {'total vol (m3)':>15}  "
      f"{'touching pairs':>15}  {'of the 21 gaps fused':>21}")
print("-" * 82)

for tol in TOLERANCES:
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    if tol is not None:
        gmsh.option.setNumber("Geometry.ToleranceBoolean", tol)
    gmsh.model.add(f"tol_{tol}")
    gmsh.open(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    vols = gmsh.model.getEntities(3)
    total_vol = sum(gmsh.model.occ.getMass(3, t) for _, t in vols)

    candidates = InterfaceDetection.find_touching_surface_pairs()
    pairs = set()
    for c in candidates:
        pairs.add((min(c["volume_a"], c["volume_b"]),
                   max(c["volume_a"], c["volume_b"])))

    fused = sum(1 for a, b, _g in KNOWN_GAPS if (min(a, b), max(a, b)) in pairs)

    label = "default" if tol is None else f"{tol:.0e}"
    print(f"{label:>12}  {len(vols):8d}  {total_vol:15.2f}  "
          f"{len(pairs):15d}  {fused:12d} / {len(KNOWN_GAPS)}")

    gmsh.finalize()

print("\nNote: volume tags are only comparable across runs if the tolerance "
      "change doesn't alter how OCC splits things - if 'volumes' moves away "
      "from 279, the KNOWN_GAPS tags no longer refer to the same solids and "
      "the last column stops being meaningful for that row.")
print("Done.")
