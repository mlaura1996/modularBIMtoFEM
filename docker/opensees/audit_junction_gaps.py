"""
Third and decisive step of the connectivity investigation.

So far:
  - audit_wall_connectivity.py: 132 adjacent volume pairs share ZERO mesh
    nodes; fragment() reports all of them as not touching.
  - audit_solid_overlap.py: none of them interpenetrate (boolean
    intersection volume = 0 for every pair tested, including the
    positive controls), and fragment() only created 2 new volumes out of
    277 - so it found almost nothing to cut.

That leaves exactly two possible explanations for a pair that is adjacent
but unfused, and they have opposite implications:

  (a) the two solids TOUCH (coincident faces) and fragment() failed to
      fuse them -> a boolean/tolerance failure in our pipeline, our bug to
      fix; or
  (b) the two solids are SEPARATED BY A REAL GAP in the source geometry
      -> the STEP/IFC model itself never had them in contact, so no
      meshing or boolean setting can connect them, and the fix belongs in
      the geometry preparation step.

This measures the gap directly, per pair, as the minimum distance between
the two volumes' boundary mesh nodes (scipy cKDTree). The mesh samples
each solid's surface at ~0.6 m spacing, so:
  - distance ~0 (< a few mm)  -> the surfaces coincide: case (a)
  - distance of cm            -> a real gap: case (b)
Connected pairs (which share nodes) are included as positive controls and
must come out at exactly 0.

Prints only.
"""
import sys
from collections import defaultdict

sys.path.insert(0, "/app")

import numpy as np
import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
GLOBAL_MESH_SIZE = 0.6
ADJ_TOL = 0.05
MAX_REPORT = 30

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("audit_junction_gaps")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

all_vols = gmsh.model.getEntities(3)
vol_tags = [t for _, t in all_vols]

candidates = InterfaceDetection.find_touching_surface_pairs()
touching_pairs = set()
for c in candidates:
    touching_pairs.add((min(c["volume_a"], c["volume_b"]),
                        max(c["volume_a"], c["volume_b"])))

gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)
gmsh.model.mesh.generate(3)

node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
coord_by_tag = {int(t): c for t, c in zip(node_tags, node_coords.reshape(-1, 3))}

bbox, vol_nodes, vol_pts = {}, {}, {}
for vol in vol_tags:
    bbox[vol] = gmsh.model.occ.getBoundingBox(3, vol)
    _et, _etg, enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
    tags = set(int(n) for n in enodes[0]) if (enodes and len(enodes[0])) else set()
    vol_nodes[vol] = tags
    vol_pts[vol] = np.array([coord_by_tag[t] for t in tags]) if tags else np.zeros((0, 3))
print(f"{len(vol_tags)} volumes meshed.")


def bboxes_adjacent(a, b, tol=ADJ_TOL):
    return (a[0] - tol <= b[3] and b[0] - tol <= a[3] and
            a[1] - tol <= b[4] and b[1] - tol <= a[4] and
            a[2] - tol <= b[5] and b[2] - tol <= a[5])


def min_distance(va, vb):
    """Minimum distance between the two volumes' mesh nodes - brute force
    in chunks (no scipy in this image; node counts here are a few hundred
    to a few thousand per volume, so this is cheap enough)."""
    pa, pb = vol_pts[va], vol_pts[vb]
    if len(pa) == 0 or len(pb) == 0:
        return float("nan")
    best = np.inf
    chunk = 512
    for start in range(0, len(pa), chunk):
        block = pa[start:start + chunk]
        d2 = ((block[:, None, :] - pb[None, :, :]) ** 2).sum(axis=2)
        best = min(best, float(np.sqrt(d2.min())))
        if best == 0.0:
            break
    return best


disconnected, connected = [], []
for i, va in enumerate(vol_tags):
    for vb in vol_tags[i + 1:]:
        if not bboxes_adjacent(bbox[va], bbox[vb]):
            continue
        shared = len(vol_nodes[va] & vol_nodes[vb])
        if shared > 0:
            connected.append((va, vb, shared, 0.0))  # shared node => distance is 0 by definition
        else:
            disconnected.append((va, vb, shared, min_distance(va, vb)))

print(f"\n{len(disconnected)} adjacent pairs with ZERO shared nodes; "
      f"{len(connected)} adjacent pairs that share nodes.")

# Positive control: a few pairs that DO share nodes, distance measured the
# same way, must come out at exactly 0.
for va, vb, shared, _ in connected[:3]:
    print(f"  control: vol {va} <-> {vb} shares {shared} nodes, "
          f"measured min distance {min_distance(va, vb):.6f} m")

print(f"\n{'='*78}")
print("ZERO-SHARED-NODE PAIRS, BY HOW FAR APART THE SOLIDS ACTUALLY ARE")
print(f"{'='*78}")
disconnected.sort(key=lambda t: t[3])
print(f"{'pair':>14}  {'min node dist (m)':>18}  interpretation")
print("-" * 78)
for va, vb, shared, d in disconnected[:MAX_REPORT]:
    if d < 0.002:
        interp = "SURFACES COINCIDE -> fragment() failed to fuse"
    elif d < 0.02:
        interp = f"gap of {d*1000:.1f} mm in the source geometry"
    else:
        interp = f"real gap of {d*100:.1f} cm - never in contact"
    print(f"{va:6d} <-> {vb:4d}  {d:18.6f}  {interp}")
if len(disconnected) > MAX_REPORT:
    print(f"  ... and {len(disconnected) - MAX_REPORT} more")

if disconnected:
    dd = np.array([d for *_x, d in disconnected])
    print(f"\nDistribution over all {len(dd)} zero-shared-node pairs:")
    for lo, hi, label in [(0, 0.002, "< 2 mm  (surfaces coincide)"),
                           (0.002, 0.02, "2-20 mm (small gap)"),
                           (0.02, 0.10, "2-10 cm (clear gap)"),
                           (0.10, 1e9, "> 10 cm (far apart)")]:
        n = int(((dd >= lo) & (dd < hi)).sum())
        print(f"  {label:32s}: {n:4d} pairs")

print("\nDone.")
gmsh.finalize()
