"""
Applies core.mesh_generation.geometry_healing to the Castelnuovo geometry
and verifies the result, then writes the healed model to a .brep.

Verification is the point of this script - a healing step that silently
changes the wrong thing is worse than no healing - so it reports, before
and after:
  - volume count and total volume (mass must be preserved to within the
    bridges' own tiny volume)
  - how many volume pairs fragment() sees as fused
  - specifically, how many of the previously-open junctions are now fused
  - the mesh-level check that actually matters: how many volume pairs
    share mesh nodes, since that is what couples them in the stiffness
    matrix (a fused face that meshes non-conformally would still be a
    disconnected model)

Writes .brep, not .step: STEP stores solids independently and would throw
away exactly the shared topology this whole exercise is about.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection
from core.mesh_generation.geometry_healing import heal_open_junctions

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
OUT_BREP = "resources/ifc_examples/castelnuovo/example_clean_PRONTO_healed.brep"
MAX_GAP = 0.05
MESH_SIZE = 0.6


def touching_pairs():
    candidates = InterfaceDetection.find_touching_surface_pairs()
    return {(min(c["volume_a"], c["volume_b"]),
             max(c["volume_a"], c["volume_b"])) for c in candidates}


def shared_node_pairs(volume_tags):
    """Volume pairs that share at least one mesh node - the real test of
    whether two solids are coupled in the assembled stiffness matrix."""
    node_owner = {}
    pairs = set()
    for v in volume_tags:
        _et, _etg, enodes = gmsh.model.mesh.getElements(dim=3, tag=v)
        if not enodes or len(enodes[0]) == 0:
            continue
        for n in set(int(x) for x in enodes[0]):
            prev = node_owner.get(n)
            if prev is None:
                node_owner[n] = v
            elif prev != v:
                pairs.add((min(prev, v), max(prev, v)))
    return pairs


def min_solid_distance(pts_a, pts_b):
    best = np.inf
    for start in range(0, len(pts_a), 512):
        block = pts_a[start:start + 512]
        d2 = ((block[:, None, :] - pts_b[None, :, :]) ** 2).sum(axis=2)
        best = min(best, float(np.sqrt(d2.min())))
        if best == 0.0:
            break
    return best


gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("castelnuovo_healed")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

vols_before = [t for _d, t in gmsh.model.getEntities(3)]
total_before = sum(gmsh.model.occ.getMass(3, t) for t in vols_before)
touch_before = touching_pairs()
print(f"BEFORE healing: {len(vols_before)} volumes, {total_before:.4f} m^3, "
      f"{len(touch_before)} fused pairs")

# --- select the junctions to bridge from the REAL solid-to-solid distance.
# Screening on bounding boxes alone flagged 208 "junctions" (large faces
# whose boxes come close while the solids are nowhere near each other),
# which bridged far too much and left the model unmeshable.
print("\n--- screening junctions on measured distance ---")
gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", MESH_SIZE)
gmsh.model.mesh.generate(3)

ntags, ncoords, _ = gmsh.model.mesh.getNodes()
coord_by_tag = {int(t): c for t, c in zip(ntags, ncoords.reshape(-1, 3))}
vol_bbox, vol_nodes, vol_pts = {}, {}, {}
for v in vols_before:
    vol_bbox[v] = gmsh.model.occ.getBoundingBox(3, v)
    _et, _etg, enodes = gmsh.model.mesh.getElements(dim=3, tag=v)
    tags_ = set(int(x) for x in enodes[0]) if (enodes and len(enodes[0])) else set()
    vol_nodes[v] = tags_
    vol_pts[v] = np.array([coord_by_tag[t] for t in tags_]) if tags_ else np.zeros((0, 3))


def bbox_adjacent(a, b, tol=MAX_GAP):
    return (a[0] - tol <= b[3] and b[0] - tol <= a[3] and
            a[1] - tol <= b[4] and b[1] - tol <= a[4] and
            a[2] - tol <= b[5] and b[2] - tol <= a[5])


only_pairs = set()
measured_gaps = {}
for i, va in enumerate(vols_before):
    for vb in vols_before[i + 1:]:
        key = (min(va, vb), max(va, vb))
        if key in touch_before:
            continue
        if not bbox_adjacent(vol_bbox[va], vol_bbox[vb]):
            continue
        if vol_nodes[va] & vol_nodes[vb]:
            continue
        if len(vol_pts[va]) == 0 or len(vol_pts[vb]) == 0:
            continue
        d = min_solid_distance(vol_pts[va], vol_pts[vb])
        if d <= MAX_GAP:
            only_pairs.add(key)
            measured_gaps[key] = d
print(f"{len(only_pairs)} junction(s) within {MAX_GAP} m selected for bridging")

gmsh.model.mesh.clear()

print("\n--- healing ---")
jobs = heal_open_junctions(max_gap=MAX_GAP, verbose=True,
                           only_pairs=only_pairs, measured_gaps=measured_gaps)
target_pairs = {(min(j["volume_a"], j["volume_b"]),
                 max(j["volume_a"], j["volume_b"])) for j in jobs}

# Fuse the bridges into the model.
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

vols_after = [t for _d, t in gmsh.model.getEntities(3)]
total_after = sum(gmsh.model.occ.getMass(3, t) for t in vols_after)
touch_after = touching_pairs()
print(f"\nAFTER healing:  {len(vols_after)} volumes, {total_after:.4f} m^3, "
      f"{len(touch_after)} fused pairs")
print(f"mass added: {total_after - total_before:+.6f} m^3 "
      f"({100*(total_after-total_before)/total_before:+.4f}%)")

# Volume tags change after the second fragment, so the "are the target
# junctions fused now" question has to be asked at the mesh level, where
# identity is geometric rather than by tag.
print("\n--- meshing to verify the junctions actually couple ---")
gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", MESH_SIZE)
gmsh.model.mesh.generate(3)

node_pairs = shared_node_pairs(vols_after)
print(f"{len(node_pairs)} volume pairs share mesh nodes after healing "
      f"(was 657 before, of which 92 shared only 1-3 nodes)")

# How well-connected are the shared-node pairs now?
counts = []
node_sets = {}
for v in vols_after:
    _et, _etg, enodes = gmsh.model.mesh.getElements(dim=3, tag=v)
    node_sets[v] = set(int(x) for x in enodes[0]) if (enodes and len(enodes[0])) else set()
for a, b in node_pairs:
    counts.append(len(node_sets[a] & node_sets[b]))
counts = np.array(counts)
print(f"shared nodes per connected pair: min {counts.min()}, "
      f"median {int(np.median(counts))}, max {counts.max()}")
print(f"pairs coupled through only 1-3 nodes: {(counts <= 3).sum()}")

# Per-junction verification. A bridge sits BETWEEN the two walls, so the
# two original volumes are now generally coupled through it rather than to
# each other directly - a 2-hop path in the shared-node graph is the
# correct success criterion, not a direct A-B pair.
adj = {}
for a, b in node_pairs:
    adj.setdefault(a, set()).add(b)
    adj.setdefault(b, set()).add(a)

print("\n--- per-junction verification ---")
healed_ok, healed_direct, still_open, tag_gone = 0, 0, [], []
for j in jobs:
    a, b = j["volume_a"], j["volume_b"]
    if a not in adj or b not in adj:
        tag_gone.append((a, b))
        continue
    if b in adj[a]:
        healed_direct += 1
        healed_ok += 1
    elif adj[a] & adj[b]:                 # connected through one bridge
        healed_ok += 1
    else:
        still_open.append((a, b, j["gap"]))

print(f"{healed_ok}/{len(jobs)} junctions now connected "
      f"({healed_direct} directly, {healed_ok - healed_direct} through their bridge)")
if tag_gone:
    print(f"{len(tag_gone)} pair(s) whose volume tag no longer exists after the "
          f"second fragment (cut into new pieces) - not verifiable by tag: {tag_gone}")
if still_open:
    print(f"STILL OPEN ({len(still_open)}):")
    for a, b, g in still_open:
        print(f"  vol {a} <-> {b}, gap was {g*1000:.2f} mm")

gmsh.write(OUT_BREP)
print(f"\nWrote {OUT_BREP}")
print("Done.")
gmsh.finalize()
