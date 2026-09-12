"""
Tag-independent verification of the healed geometry: re-runs exactly the
audit that found the problem (audit_junction_gaps.py) against the healed
.brep and reports how many open junctions remain.

Why not verify by volume tag: the bridges cut the original wall solids, so
the second fragment() renumbers them - 19 of the 21 original tags no
longer exist afterwards, which makes any tag-based before/after comparison
meaningless. Counting how many adjacent volume pairs STILL sit within
5 cm of each other while sharing no mesh node is the same question asked
geometrically, and it is the number that has to go to zero.

Baseline (original geometry): 21 such junctions.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

GEOMETRY = sys.argv[1] if len(sys.argv) > 1 else \
    "resources/ifc_examples/castelnuovo/example_clean_PRONTO_healed.brep"
# A .brep already carries shared topology, so re-fragmenting one is at best
# redundant and at worst destructive - re-running a boolean over hundreds
# of coincident faces is exactly the situation that produces slivers. Pass
# "nofragment" to skip it; the original STEP still needs the fragment.
DO_FRAGMENT = "nofragment" not in sys.argv
MAX_GAP = 0.05
MESH_SIZE = 0.6

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("verify_healed")
gmsh.open(GEOMETRY)
if DO_FRAGMENT:
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
print(f"fragment() after load: {DO_FRAGMENT}")
gmsh.model.occ.synchronize()

vols = [t for _d, t in gmsh.model.getEntities(3)]
total_vol = sum(gmsh.model.occ.getMass(3, t) for t in vols)
candidates = InterfaceDetection.find_touching_surface_pairs()
touching = {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
            for c in candidates}
print(f"{GEOMETRY}: {len(vols)} volumes, {total_vol:.4f} m^3, "
      f"{len(touching)} fused pairs")

gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", MESH_SIZE)
gmsh.model.mesh.generate(3)

ntags, ncoords, _ = gmsh.model.mesh.getNodes()
coord_by_tag = {int(t): c for t, c in zip(ntags, ncoords.reshape(-1, 3))}
bbox, nodes, pts = {}, {}, {}
for v in vols:
    bbox[v] = gmsh.model.occ.getBoundingBox(3, v)
    _et, _etg, en = gmsh.model.mesh.getElements(dim=3, tag=v)
    s = set(int(x) for x in en[0]) if (en and len(en[0])) else set()
    nodes[v] = s
    pts[v] = np.array([coord_by_tag[t] for t in s]) if s else np.zeros((0, 3))
print(f"mesh: {len(ntags)} nodes")


def adjacent(a, b, tol=MAX_GAP):
    return (a[0] - tol <= b[3] and b[0] - tol <= a[3] and
            a[1] - tol <= b[4] and b[1] - tol <= a[4] and
            a[2] - tol <= b[5] and b[2] - tol <= a[5])


def min_dist(pa, pb):
    best = np.inf
    for s in range(0, len(pa), 512):
        blk = pa[s:s + 512]
        d2 = ((blk[:, None, :] - pb[None, :, :]) ** 2).sum(axis=2)
        best = min(best, float(np.sqrt(d2.min())))
        if best == 0.0:
            break
    return best


open_junctions = []
for i, va in enumerate(vols):
    for vb in vols[i + 1:]:
        if not adjacent(bbox[va], bbox[vb]):
            continue
        if nodes[va] & nodes[vb]:
            continue
        if len(pts[va]) == 0 or len(pts[vb]) == 0:
            continue
        d = min_dist(pts[va], pts[vb])
        if d <= MAX_GAP:
            open_junctions.append((va, vb, d))

open_junctions.sort(key=lambda t: t[2])
print(f"\n{'='*66}")
print(f"OPEN JUNCTIONS REMAINING (< {MAX_GAP} m, no shared nodes): "
      f"{len(open_junctions)}   [was 21 on the original geometry]")
print(f"{'='*66}")
for va, vb, d in open_junctions[:25]:
    print(f"  vol {va:4d} <-> {vb:4d}: {d*1000:7.2f} mm")
if len(open_junctions) > 25:
    print(f"  ... and {len(open_junctions) - 25} more")

# Weakly-coupled pairs too - a junction fused through 1-3 nodes is a hinge,
# not an interlock, so it matters for the same reason.
weak = 0
for i, va in enumerate(vols):
    for vb in vols[i + 1:]:
        if not adjacent(bbox[va], bbox[vb]):
            continue
        n = len(nodes[va] & nodes[vb])
        if 0 < n <= 3:
            weak += 1
print(f"\npairs coupled through only 1-3 nodes: {weak}   [was 92]")
print("Done.")
gmsh.finalize()
