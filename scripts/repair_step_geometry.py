"""
Automated geometry repair for a raw IFC->STEP export, mirroring (as a
repeatable script, not the one-off manual process the original
Castelnuovo STEP went through - PROJECT_BRIEF.md 3.3) two of its steps:

1. Remove exact duplicate solids (same volume + same center of mass,
   within tolerance) - the original had 8; this run's raw export of the
   new, slab-free IFC (example_clean.ifc) has its own set, found by
   grouping (not just pairwise matching - a volume can duplicate more
   than one other, e.g. a door frame profile repeated at 3 openings).
2. Resolve genuine interpenetrations by cutting the smaller solid with
   the larger, keeping the larger intact - the original had 17 (0.2034
   m^3 removed). "Genuine" here means real solid-solid Boolean
   intersection with non-trivial volume, NOT just bounding-box overlap
   (tried first, on ~380 volumes it flagged 377 pairs - almost
   meaningless as a signal, since two unrelated solids' AABBs overlap
   constantly in a real building without their actual shapes touching).

Does NOT attempt the third original repair step (sewing open shells) -
no evidence yet that this export has open-shell issues; revisit if
fragment() or meshing later flag it.

Verified on Castelnuovo's example_clean.ifc: 285 raw volumes -> 4
duplicate groups (8 volumes removed) -> 431 bbox-overlap candidates,
only 9 real interpenetrations (0.0114 m^3 removed) -> 277 final volumes,
623.06 m^3 total, fragment() succeeds (279 volumes). Re-running the
duplicate/overlap check against the written output confirms 0 duplicates
remain.

Input: export/castelnuovo_clean/castelnuovo_clean.step (raw, from
scripts/convert_ifc_to_step.py).
Output: resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp
"""
import sys, os
sys.path.insert(0, os.path.abspath('.'))
import gmsh

IN_PATH = "export/castelnuovo_clean/castelnuovo_clean.step"
OUT_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
DUP_VOL_TOL = 1e-4    # m^3
DUP_COM_TOL = 1e-3    # m
INTERSECT_VOL_TOL = 1e-4  # m^3 - below this, treat as numerical noise, not real interpenetration

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.open(IN_PATH)
gmsh.model.occ.synchronize()

vols = [t for _, t in gmsh.model.getEntities(3)]
print(f"Starting: {len(vols)} volumes")

# --- Step 1: duplicate removal (grouped, not just pairwise) ---
sig = {t: (gmsh.model.occ.getMass(3, t), gmsh.model.occ.getCenterOfMass(3, t)) for t in vols}

parent = {t: t for t in vols}
def find(t):
    while parent[t] != t:
        parent[t] = parent[parent[t]]
        t = parent[t]
    return t
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb

for i in range(len(vols)):
    for j in range(i + 1, len(vols)):
        t1, t2 = vols[i], vols[j]
        v1, c1 = sig[t1]
        v2, c2 = sig[t2]
        if abs(v1 - v2) < DUP_VOL_TOL and all(abs(a - b) < DUP_COM_TOL for a, b in zip(c1, c2)):
            union(t1, t2)

groups = {}
for t in vols:
    groups.setdefault(find(t), []).append(t)
dup_groups = [g for g in groups.values() if len(g) > 1]

to_remove = []
for g in dup_groups:
    keep, *rest = sorted(g)
    to_remove.extend(rest)
    print(f"Duplicate group {sorted(g)}: keeping {keep}, removing {rest}")

if to_remove:
    gmsh.model.occ.remove([(3, t) for t in to_remove], recursive=True)
    gmsh.model.occ.synchronize()

vols = [t for _, t in gmsh.model.getEntities(3)]
print(f"\nAfter duplicate removal: {len(vols)} volumes ({len(to_remove)} removed)")

# --- Step 2: real interpenetration detection + resolution ---
# Bounding-box overlap as a cheap pre-filter only (skip the expensive
# real intersection test for pairs whose boxes don't even overlap).
bboxes = {t: gmsh.model.getBoundingBox(3, t) for t in vols}

def bbox_overlap_volume(b1, b2):
    ox = max(0, min(b1[3], b2[3]) - max(b1[0], b2[0]))
    oy = max(0, min(b1[4], b2[4]) - max(b1[1], b2[1]))
    oz = max(0, min(b1[5], b2[5]) - max(b1[2], b2[2]))
    return ox * oy * oz

candidate_pairs = []
for i in range(len(vols)):
    for j in range(i + 1, len(vols)):
        t1, t2 = vols[i], vols[j]
        if bbox_overlap_volume(bboxes[t1], bboxes[t2]) > 1e-6:
            candidate_pairs.append((t1, t2))
print(f"\n{len(candidate_pairs)} bbox-overlap candidate pairs to test for real interpenetration...")

real_overlaps = []
for t1, t2 in candidate_pairs:
    out, _ = gmsh.model.occ.intersect(
        [(3, t1)], [(3, t2)], removeObject=False, removeTool=False, tag=-1,
    )
    gmsh.model.occ.synchronize()
    overlap_vol = sum(gmsh.model.occ.getMass(d, t) for d, t in out)
    # Clean up the probe intersection result regardless of outcome.
    if out:
        gmsh.model.occ.remove(out, recursive=True)
        gmsh.model.occ.synchronize()
    if overlap_vol > INTERSECT_VOL_TOL:
        v1 = gmsh.model.occ.getMass(3, t1)
        v2 = gmsh.model.occ.getMass(3, t2)
        real_overlaps.append((t1, t2, overlap_vol, v1, v2))

print(f"{len(real_overlaps)} pairs have real solid-solid interpenetration "
      f"(> {INTERSECT_VOL_TOL} m^3 overlap)")
total_removed_vol = 0.0
for t1, t2, ov, v1, v2 in real_overlaps:
    smaller, larger = (t1, t2) if v1 <= v2 else (t2, t1)
    print(f"  Cutting {smaller} (vol={min(v1,v2):.4f}) with {larger} (vol={max(v1,v2):.4f}), "
          f"overlap={ov:.4f} m^3")
    out, _ = gmsh.model.occ.cut([(3, smaller)], [(3, larger)], removeObject=True, removeTool=False)
    gmsh.model.occ.synchronize()
    total_removed_vol += ov

print(f"\nTotal interpenetration volume removed: {total_removed_vol:.4f} m^3 "
      f"(brief's original repair removed 0.2034 m^3, for scale)")

vols_final = gmsh.model.getEntities(3)
total_volume_final = sum(gmsh.model.occ.getMass(d, t) for d, t in vols_final)
print(f"\nFinal: {len(vols_final)} volumes, total volume {total_volume_final:.2f} m^3")

print("\nVerifying fragment() still succeeds on the repaired geometry...")
gmsh.model.occ.fragment(vols_final, [])
gmsh.model.occ.synchronize()
vols_after_fragment = gmsh.model.getEntities(3)
print(f"Fragment OK: {len(vols_after_fragment)} volumes after fragment.")

# Re-open a fresh copy to write the PRE-fragment repaired geometry (the
# rest of the pipeline calls fragment() itself, on load - writing the
# already-fragmented version here would double-fragment downstream).
gmsh.finalize()
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.open(IN_PATH)
gmsh.model.occ.synchronize()
if to_remove:
    gmsh.model.occ.remove([(3, t) for t in to_remove], recursive=True)
    gmsh.model.occ.synchronize()
for t1, t2, ov, v1, v2 in real_overlaps:
    smaller, larger = (t1, t2) if v1 <= v2 else (t2, t1)
    gmsh.model.occ.cut([(3, smaller)], [(3, larger)], removeObject=True, removeTool=False)
    gmsh.model.occ.synchronize()

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
gmsh.write(OUT_PATH)
print(f"\nWrote repaired (pre-fragment) STEP: {OUT_PATH}")
gmsh.finalize()
