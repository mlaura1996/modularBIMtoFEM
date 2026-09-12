"""
Decisive follow-up to audit_wall_connectivity.py, which found 132 pairs of
geometrically adjacent volumes sharing ZERO mesh nodes, several with
bounding-box overlaps the size of a wall thickness (0.2-0.5 m).

A bounding-box overlap is NOT proof the solids touch - two walls meeting in
an L share a big bbox overlap in the corner while the solids only meet on
one face. So this measures the real thing, with OCC booleans:

  1. Volume count before vs after fragment() - if fragment() had cut
     genuinely interpenetrating solids apart, it would have created extra
     volumes; if the count is unchanged, it found nothing to cut.
  2. For the worst bbox-overlapping, zero-shared-node pairs: the actual
     BOOLEAN INTERSECTION VOLUME of the two solids (occ.intersect with
     removeObject/removeTool=False, result deleted afterwards). A non-zero
     intersection volume means the two solids physically occupy the same
     space while being structurally independent in the model - mass counted
     twice, no stiffness coupling, which is what an out-of-plane mode that
     ignores its bracing walls would look like.
  3. For the same pairs, the minimum distance between the two solids
     (occ.getDistance) - distinguishes "interpenetrating" from "separated
     by a small gap" from "exactly touching but unfused".

Prints only.
"""
import sys

sys.path.insert(0, "/app")

import gmsh

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
# Worst offenders from audit_wall_connectivity.py (bbox-overlapping, zero
# shared mesh nodes), plus 118/106's own neighbours for comparison - those
# DO share nodes, so they act as a positive control for the same tests.
TEST_PAIRS = [
    (78, 93), (89, 95), (85, 94), (58, 117), (18, 101),
    (107, 110), (107, 118), (71, 168), (91, 102), (81, 101),
    (118, 110), (118, 71), (106, 92), (106, 71),   # positive controls
]

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("audit_solid_overlap")
gmsh.open(STEP_PATH)
gmsh.model.occ.synchronize()
before = gmsh.model.getEntities(3)
print(f"Volumes BEFORE fragment(): {len(before)}")

gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
after = gmsh.model.getEntities(3)
print(f"Volumes AFTER  fragment(): {len(after)}")
print("(if fragment() had cut interpenetrating solids apart, the count "
      "would have GROWN - each overlap region becomes its own volume)\n")

existing = {t for _, t in after}

print(f"{'pair':>14}  {'min distance (m)':>17}  {'intersection vol (m^3)':>23}  note")
print("-" * 80)
for a, b in TEST_PAIRS:
    if a not in existing or b not in existing:
        print(f"{a:6d} <-> {b:4d}  {'n/a':>17}  {'n/a':>23}  volume tag absent after fragment")
        continue

    try:
        d = gmsh.model.occ.getDistance(3, a, 3, b)[0]
    except Exception as e:  # older API signatures differ
        d = float("nan")
        print(f"  (getDistance failed for {a}/{b}: {e})")

    inter_vol = 0.0
    note = ""
    try:
        out, _ = gmsh.model.occ.intersect(
            [(3, a)], [(3, b)], removeObject=False, removeTool=False)
        gmsh.model.occ.synchronize()
        for dim, tag in out:
            if dim == 3:
                inter_vol += gmsh.model.occ.getMass(3, tag)
        if out:
            gmsh.model.occ.remove(out, recursive=True)
            gmsh.model.occ.synchronize()
    except Exception as e:
        note = f"intersect failed: {e}"

    if not note:
        if inter_vol > 1e-9:
            note = "SOLIDS INTERPENETRATE, not fused"
        elif d < 1e-9:
            note = "exactly touching"
        else:
            note = f"separated by {d*1000:.2f} mm"
    print(f"{a:6d} <-> {b:4d}  {d:17.6f}  {inter_vol:23.6f}  {note}")

print("\nDone.")
gmsh.finalize()
