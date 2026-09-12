"""
Model-wide wall-to-wall connectivity audit, prompted by the user's
observation on the gmsh render: "si vede chiaramente in diversi modi che
questo muro non e' connesso a quelli ortogonali".

Every connectivity check so far in this session looked at 4 SPECIFIC
volume pairs (118-71, 118-110, 106-71, 106-92) that the localized modes
pointed at, and found genuinely shared mesh nodes each time. That says
nothing about the other ~275 volumes: a T-junction where a transverse wall
butts into a facade wall could be geometrically adjacent yet share NO mesh
nodes at all, which is exactly what an out-of-plane mode that ignores its
bracing walls would look like.

This audits ALL pairs:
  1. Bounding-box adjacency test (overlapping, or within ADJ_TOL) - cheap,
     runs over all 279*278/2 pairs.
  2. For every adjacent pair, the number of mesh nodes the two volumes
     literally share (same node tag in both volumes' tetrahedra - the same
     criterion render_volume118_check.py used, which is what actually
     decides whether the two are coupled in the stiffness matrix).
  3. Reports, in order of severity:
       - adjacent pairs sharing ZERO nodes (structurally disconnected
         despite touching/overlapping) - the case her observation predicts
       - volumes with no shared-node connection to ANY neighbour (floating)
       - adjacent pairs sharing only 1-3 nodes (point/line contact - a
         hinge, not a wall-to-wall connection)
  4. For the zero-shared-node pairs it also reports whether
     InterfaceDetection.find_touching_surface_pairs() (the fragment()-based
     shared-topology detector) sees them as touching, which separates
     "fragment() never fused them" from "fragment() fused them but the
     mesh didn't share nodes there" - two different failure modes.

Prints only, no files written.
"""
import sys
from collections import defaultdict

sys.path.insert(0, "/app")

import numpy as np
import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
GLOBAL_MESH_SIZE = 0.6
ADJ_TOL = 0.05   # m - bounding boxes within this of each other count as "adjacent"

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("audit_wall_connectivity")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

all_vols = gmsh.model.getEntities(3)
vol_tags = [t for _, t in all_vols]
print(f"{len(vol_tags)} volumes loaded.")

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)
touching_pairs = {}
for c in candidates:
    key = (min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
    touching_pairs.setdefault(key, []).append(c)
print(f"{len(candidates)} shared surfaces across {len(touching_pairs)} volume pairs "
      f"(fragment()'s own shared-topology view).")

pg_tag = gmsh.model.addPhysicalGroup(3, vol_tags)
gmsh.model.setPhysicalName(3, pg_tag, "Masonry")
gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)
gmsh.model.mesh.generate(3)

bbox = {}
vol_nodes = {}
vol_size = {}
for vol in vol_tags:
    bbox[vol] = gmsh.model.occ.getBoundingBox(3, vol)
    vol_size[vol] = gmsh.model.occ.getMass(3, vol)
    _et, _etg, enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
    if enodes and len(enodes[0]):
        vol_nodes[vol] = set(int(n) for n in enodes[0])
    else:
        vol_nodes[vol] = set()
print(f"Mesh built; {sum(len(v) for v in vol_nodes.values())} volume-node memberships.")


def bboxes_adjacent(a, b, tol=ADJ_TOL):
    axmin, aymin, azmin, axmax, aymax, azmax = a
    bxmin, bymin, bzmin, bxmax, bymax, bzmax = b
    return (axmin - tol <= bxmax and bxmin - tol <= axmax and
            aymin - tol <= bymax and bymin - tol <= aymax and
            azmin - tol <= bzmax and bzmin - tol <= azmax)


def bbox_overlap_extent(a, b):
    """Size of the bbox intersection per axis (negative = separated)."""
    axmin, aymin, azmin, axmax, aymax, azmax = a
    bxmin, bymin, bzmin, bxmax, bymax, bzmax = b
    return (
        min(axmax, bxmax) - max(axmin, bxmin),
        min(aymax, bymax) - max(aymin, bymin),
        min(azmax, bzmax) - max(azmin, bzmin),
    )


disconnected = []     # adjacent bboxes, zero shared nodes
weak = []             # adjacent bboxes, 1-3 shared nodes
connected_counts = []
neighbours_by_vol = defaultdict(int)

for i, va in enumerate(vol_tags):
    for vb in vol_tags[i + 1:]:
        if not bboxes_adjacent(bbox[va], bbox[vb]):
            continue
        shared = len(vol_nodes[va] & vol_nodes[vb])
        key = (min(va, vb), max(va, vb))
        if shared == 0:
            ox, oy, oz = bbox_overlap_extent(bbox[va], bbox[vb])
            disconnected.append((va, vb, ox, oy, oz, key in touching_pairs))
        else:
            connected_counts.append(shared)
            neighbours_by_vol[va] += 1
            neighbours_by_vol[vb] += 1
            if shared <= 3:
                weak.append((va, vb, shared, key in touching_pairs))

print(f"\n{'='*72}")
print(f"ADJACENT PAIRS SHARING ZERO MESH NODES: {len(disconnected)}")
print(f"{'='*72}")
print("(bounding boxes overlap or are within "
      f"{ADJ_TOL} m, but no node is common to both volumes' tetrahedra - "
      "these two volumes are NOT coupled in the stiffness matrix)")
# Sort by how much the bounding boxes actually overlap - a big overlap with
# zero shared nodes is the most serious case (two solids occupying the same
# region yet structurally independent).
disconnected.sort(key=lambda t: -min(t[2], t[3], t[4]))
for va, vb, ox, oy, oz, in_touching in disconnected[:40]:
    overlap_min = min(ox, oy, oz)
    kind = ("OVERLAPPING" if overlap_min > 1e-9 else
            "ABUTTING/NEAR" if overlap_min > -ADJ_TOL else "NEAR")
    print(f"  vol {va:4d} <-> {vb:4d}: bbox overlap "
          f"({ox:+.4f}, {oy:+.4f}, {oz:+.4f}) m [{kind}], "
          f"fragment() sees them touching: {in_touching}")
if len(disconnected) > 40:
    print(f"  ... and {len(disconnected) - 40} more")

print(f"\n{'='*72}")
print(f"ADJACENT PAIRS SHARING ONLY 1-3 NODES (point/edge contact): {len(weak)}")
print(f"{'='*72}")
for va, vb, shared, in_touching in sorted(weak, key=lambda t: t[2])[:25]:
    print(f"  vol {va:4d} <-> {vb:4d}: {shared} shared node(s), "
          f"fragment() touching: {in_touching}")
if len(weak) > 25:
    print(f"  ... and {len(weak) - 25} more")

isolated = [v for v in vol_tags if neighbours_by_vol[v] == 0 and vol_nodes[v]]
print(f"\n{'='*72}")
print(f"VOLUMES WITH NO SHARED-NODE CONNECTION TO ANY NEIGHBOUR: {len(isolated)}")
print(f"{'='*72}")
for v in isolated[:30]:
    xmin, ymin, zmin, xmax, ymax, zmax = bbox[v]
    print(f"  vol {v:4d}: {vol_size[v]:8.3f} m^3, bbox "
          f"{xmax-xmin:.2f} x {ymax-ymin:.2f} x {zmax-zmin:.2f} m, "
          f"z from {zmin:.2f} to {zmax:.2f}")
if len(isolated) > 30:
    print(f"  ... and {len(isolated) - 30} more")

if connected_counts:
    arr = np.array(connected_counts)
    print(f"\nConnected pairs: {len(arr)}; shared nodes per pair - "
          f"min {arr.min()}, median {int(np.median(arr))}, max {arr.max()}")
print(f"Volumes with at least one connection: "
      f"{sum(1 for v in vol_tags if neighbours_by_vol[v] > 0)}/{len(vol_tags)}")

print("\nDone.")
gmsh.finalize()
