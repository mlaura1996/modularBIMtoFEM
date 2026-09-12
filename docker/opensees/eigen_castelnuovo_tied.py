"""
Self-weight + eigenvalue analysis of the full Castelnuovo aggregate (bonded,
no Task A interfaces), rebuilt on the user's OWN established framework
(plain gmsh + external/gmsh2opensees + core/opensees_generation/
model_builder.py + openseespy, the same stack main.py/in_plane_wall.py use)
instead of apeGmsh + TclWriter + OpenSeesMP - per explicit request: "rifai
l'analisi anche solo con gmsh nel mio framework normale senza ape visto che
le eigenvalue le facciamo sequenziali" - the eigenvalue solve was already
confirmed to need N_PARTS=1 (no MPI domain decomposition) regardless of
mesh size, so there is no parallel-partitioning benefit apeGmsh's TCL
export gives up by dropping it here; this stays fully sequential/headless
(no gmsh.fltk.run() - those block for an interactive window, fine for her
local workflow, not for a Docker run) and uses openseespy directly (Python
return values for eigenvalues/eigenvectors, no TCL recorder files to
parse).

Material: the weighted average of the 4 HMO/MQI-calibrated masonry types
(docs/source/case_study/materials.md) - E = mean(1526.6, 1198.7, 987.8,
1198.7[type D=B]) = 1227.95 MPa, nu = 0.2, rho = 1450 kg/m^3 - replacing
the generic placeholder (700 MPa/0.25/2000 kg/m^3) used throughout the
apeGmsh pipeline. Equal-weighted across the 4 types since a real per-
facade material assignment needs a volume<->facade mapping that doesn't
exist yet (docs/source/case_study/open_questions.md #6).

Ground-bearing base fixity reuses core.mesh_generation.wall_interfaces.
InterfaceDetection as-is - it's written directly against gmsh.model.* calls,
with no apeGmsh dependency, so it works identically here.

Writes output/castelnuovo/recorders_castelnuovo_tied/:
  - eigenvalues.txt, modal_properties.txt (same layout/parsing as the
    apeGmsh/TCL pipeline's eigen scripts)
  - mode<k>_eigenvector.txt - node_id,ux,uy,uz per line (plain text, not
    the TCL recorder's flat single-line format - openseespy hands back
    ops.nodeEigenvector(tag, mode, dof) directly per node, no file-based
    recorder involved at all)
  - node_coords.txt - node_id,x,y,z (undeformed), so a separate plotting
    script can rebuild geometry without re-meshing
  - summary.json
"""
import json
import math
import os
import sys

sys.path.insert(0, "/app")
OUT_DIR = "output/castelnuovo/recorders_castelnuovo_tied"
os.makedirs(OUT_DIR, exist_ok=True)

import numpy as np
import gmsh
import openseespy.opensees as ops

from external.gmsh2opensees.g2o_nodes_functions import (
    get_all_nodes, add_nodes_to_ops, fix_nodes, get_eigenvector_at_nodes,
    get_displacements_at_nodes,
)
from core.opensees_generation.model_builder import ModelBuilder, Element
from core.opensees_generation.junction_ties import find_junction_ties, apply_ties
from core.mesh_generation.geometry_healing import find_open_junctions
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
GLOBAL_MESH_SIZE = 0.6
N_MODES = 10
E_MPA, NU, RHO = 1227.95, 0.2, 1450.0  # see module docstring for the weighted-average derivation
G_ACCEL = -9.81  # matches core.config.G's sign convention (negative = -z)
MAX_JUNCTION_GAP = 0.05   # m - treat solids this close as a junction that should be connected
MAX_TIE_DISTANCE = 0.10   # m - never tie a node pair further apart than this
JUNCTION_MESH_SIZE = 0.10  # m - local mesh size at the open junctions. At the
# 0.6 m global size the facing nodes sit ~0.6 m apart while the gaps are
# millimetres, so almost no node pair lands close enough to tie: the first
# attempt produced a single tie on most junctions and none at all on 11 of
# 21. Refining locally puts the facing nodes within ~0.1 m of each other,
# giving many SHORT ties instead of a few long ones - a long tie is a rigid
# link that stiffens the junction far beyond what the masonry does.
JUNCTION_REFINE_RADIUS = 0.4  # m - distance over which to blend back to the global size
MSH_PATH = f"{OUT_DIR}/castelnuovo_tied.msh"
# --mesh-only re-exports the .msh for an analysis that already ran (and
# checks it against the stored node_coords.txt) without redoing the solve.
MESH_ONLY = "--mesh-only" in sys.argv
# --ties-only stops after building and auditing the ties, without solving.
TIES_ONLY = "--ties-only" in sys.argv

# --- 1. Mesh (plain gmsh, headless - no gmsh.fltk.run()) ------------------
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("castelnuovo_tied")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()

all_vols = gmsh.model.getEntities(3)
vol_tags = [t for _, t in all_vols]
print(f"{len(vol_tags)} volumes loaded.")
total_volume = sum(gmsh.model.occ.getMass(3, t) for t in vol_tags)
print(f"Total volume: {total_volume:.2f} m^3")

pg_tag = gmsh.model.addPhysicalGroup(3, vol_tags)
gmsh.model.setPhysicalName(3, pg_tag, "Masonry")

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)

gmsh.model.mesh.setOrder(1)  # Element.create_linear_elastic_element needs Tet4, not Tet10
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)


def _bbox_adjacent(a, b, tol=MAX_JUNCTION_GAP):
    return (a[0] - tol <= b[3] and b[0] - tol <= a[3] and
            a[1] - tol <= b[4] and b[1] - tol <= a[4] and
            a[2] - tol <= b[5] and b[2] - tol <= a[5])


def _min_dist(pa, pb):
    best = np.inf
    for s_ in range(0, len(pa), 512):
        blk = pa[s_:s_ + 512]
        d2 = ((blk[:, None, :] - pb[None, :, :]) ** 2).sum(axis=2)
        best = min(best, float(np.sqrt(d2.min())))
        if best == 0.0:
            break
    return best


def _near_bbox(pts, bbox, tol):
    """Subset of `pts` lying within `tol` of an axis-aligned bounding box."""
    if len(pts) == 0:
        return pts
    lo = np.array(bbox[:3]) - tol
    hi = np.array(bbox[3:]) + tol
    m = np.all((pts >= lo) & (pts <= hi), axis=1)
    return pts[m]


def _locate_open_junctions(only_pairs=None):
    """Volume pairs closer than MAX_JUNCTION_GAP that share no mesh node -
    i.e. walls the source geometry left structurally independent.

    `only_pairs` restricts the search to known candidates. Pass it on the
    refined mesh: the full O(n^2) sweep is 38,781 volume pairs, and the
    brute-force point-to-point distance behind it is affordable at the
    0.6 m global size but not at 0.1 m, where the volumes around the
    junctions carry orders of magnitude more nodes (a first attempt sat at
    100% CPU for 20 minutes without finishing). The junction pairs are
    already known from the coarse pass and the volume tags do not change
    when only the mesh is regenerated, so re-deriving them is wasted work.
    """
    ntags_, ncoords_, _ = gmsh.model.mesh.getNodes()
    cbt = {int(t): c for t, c in zip(ntags_, ncoords_.reshape(-1, 3))}
    bbox_, nodes_, pts_ = {}, {}, {}
    for v in vol_tags:
        bbox_[v] = gmsh.model.occ.getBoundingBox(3, v)
        _e1, _e2, en = gmsh.model.mesh.getElements(dim=3, tag=v)
        st = set(int(x) for x in en[0]) if (en and len(en[0])) else set()
        nodes_[v] = st
        pts_[v] = np.array([cbt[t] for t in st]) if st else np.zeros((0, 3))
    touching_ = {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
                 for c in candidates}

    if only_pairs is not None:
        pair_iter = [(a, b) for a, b in only_pairs]
    else:
        pair_iter = [(vol_tags[i_], vb_)
                     for i_ in range(len(vol_tags))
                     for vb_ in vol_tags[i_ + 1:]]

    found = []
    for va_, vb_ in pair_iter:
        if (min(va_, vb_), max(va_, vb_)) in touching_:
            continue
        if not _bbox_adjacent(bbox_[va_], bbox_[vb_]):
            continue
        if nodes_[va_] & nodes_[vb_]:
            continue
        if len(pts_[va_]) == 0 or len(pts_[vb_]) == 0:
            continue
        # Only the nodes near the other volume can be the closest ones, and
        # on the refined mesh that prunes tens of thousands down to a few
        # hundred - without it this is the step that never finishes.
        pa_ = _near_bbox(pts_[va_], bbox_[vb_], MAX_JUNCTION_GAP)
        pb_ = _near_bbox(pts_[vb_], bbox_[va_], MAX_JUNCTION_GAP)
        if len(pa_) == 0 or len(pb_) == 0:
            continue
        d_ = _min_dist(pa_, pb_)
        if d_ <= MAX_JUNCTION_GAP:
            found.append((va_, vb_, d_))
    found.sort(key=lambda t: t[2])
    return found


# Pass 1: coarse mesh, only to find WHERE the open junctions are.
print("Meshing (pass 1, locating open junctions)...")
gmsh.model.mesh.generate(3)
open_junctions = _locate_open_junctions()
print(f"{len(open_junctions)} open junction(s) within {MAX_JUNCTION_GAP} m")

# Pass 2: refine locally around those junctions so the facing nodes end up
# close enough to tie with SHORT constraints, then re-mesh.
#
# ONLY the two faces that actually face each other across each gap. A first
# attempt fed every face of both volumes into the field, which refines
# whole walls from 0.6 m to 0.1 m - a ~200x density increase over some 40
# walls - and meshing never finished. find_open_junctions already works out
# which face pair is the junction, so reuse it.
_face_jobs = find_open_junctions(
    vol_tags,
    {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
     for c in candidates},
    max_gap=MAX_JUNCTION_GAP,
    only_pairs={(min(a, b), max(a, b)) for a, b, _g in open_junctions},
    measured_gaps={(min(a, b), max(a, b)): g for a, b, g in open_junctions},
)
junction_faces = sorted({f for j in _face_jobs
                          for f in (j["face_small"], j["face_big"])})
print(f"refining around {len(junction_faces)} facing surface(s) "
      f"from {len(_face_jobs)} junction(s)")

gmsh.model.mesh.clear()
_df = gmsh.model.mesh.field.add("Distance")
gmsh.model.mesh.field.setNumbers(_df, "SurfacesList", junction_faces)
gmsh.model.mesh.field.setNumber(_df, "Sampling", 30)
_tf = gmsh.model.mesh.field.add("Threshold")
gmsh.model.mesh.field.setNumber(_tf, "InField", _df)
gmsh.model.mesh.field.setNumber(_tf, "SizeMin", JUNCTION_MESH_SIZE)
gmsh.model.mesh.field.setNumber(_tf, "SizeMax", GLOBAL_MESH_SIZE)
gmsh.model.mesh.field.setNumber(_tf, "DistMin", 0.0)
gmsh.model.mesh.field.setNumber(_tf, "DistMax", JUNCTION_REFINE_RADIUS)
gmsh.model.mesh.field.setAsBackgroundMesh(_tf)
gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
print(f"Meshing (pass 2, {JUNCTION_MESH_SIZE} m around {len(junction_faces)} "
      f"junction faces)...")
gmsh.model.mesh.generate(3)
print("Meshing done.")

# Write the analysed mesh out so scripts/view_results_gmsh.py can load the
# results interactively without re-meshing. Written HERE, from the same
# in-memory mesh the analysis is about to use, rather than by a separate
# export script: the two-pass refinement is not something to reproduce by
# hand in a second place and then hope it matches.
gmsh.option.setNumber("Mesh.SaveAll", 1)
gmsh.write(MSH_PATH)
print(f"Wrote {MSH_PATH}")

if MESH_ONLY:
    # Re-exporting the mesh for an analysis that already ran: prove it is
    # the same mesh before overwriting the .msh the viewer will trust.
    ref = f"{OUT_DIR}/node_coords.txt"
    if os.path.exists(ref):
        ntg, ncd, _ = gmsh.model.mesh.getNodes()
        cbt = {int(t): c for t, c in zip(ntg, ncd.reshape(-1, 3))}
        dev, n_ref = 0.0, 0
        with open(ref) as fh:
            for line in fh:
                p = line.strip().split(",")
                if len(p) != 4:
                    continue
                n_ref += 1
                t = int(p[0])
                assert t in cbt, f"result node {t} absent from the re-meshed model"
                dev = max(dev, float(np.linalg.norm(
                    cbt[t] - np.array([float(p[1]), float(p[2]), float(p[3])]))))
        assert n_ref == len(ntg), f"node count differs: mesh {len(ntg)} vs results {n_ref}"
        assert dev < 1e-9, f"node coordinates differ by up to {dev:.3e} m"
        print(f"Mesh reproduced exactly: {len(ntg)} nodes, max deviation {dev:.3e} m")
    gmsh.finalize()
    sys.exit(0)

# --- 2. OpenSees model (her framework: ModelBuilder + Element + g2o) -----
ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

node_tags_all, node_coords_all = get_all_nodes(gmsh.model)
add_nodes_to_ops(node_tags_all, gmsh.model)
print(f"{len(node_tags_all)} nodes added to OpenSees.")

# g2o's get_displacements_at_nodes/get_eigenvector_at_nodes both call
# numpy.unique() on the node-tag list internally, which SORTS it - fix the
# canonical node order to that same sorted order everywhere below (coords,
# self-weight displacement, every mode's eigenvector), so row i means the
# same node in every one of these files without relying on get_all_nodes's
# own (not guaranteed sorted) return order.
node_tags_sorted = np.array(sorted(int(t) for t in node_tags_all), dtype=np.int64)
coord_by_tag = {int(t): c for t, c in zip(node_tags_all, node_coords_all)}
node_coords_sorted = np.array([coord_by_tag[int(t)] for t in node_tags_sorted])

material = Material(
    name="Masonry", density=RHO, young_modulus=E_MPA, poisson_ratio=NU,
    is_structural=True, material_model_type="LinearElastic",
    compressive_strength=0, tensile_strength=0,
    compression_fracture_energy=0, tensile_fracture_energy=0,
    compressive_elastic_behaviour=0,
)
element_tags = Element.add_elements_to_opensees(gmsh.model, {"Masonry": material})
print(f"{len(element_tags)} elements added to OpenSees "
      f"(self-weight body force baked directly into each element - "
      f"bx=by=0, bz=rho*G - same convention the apeGmsh/TCL pipeline used, "
      f"no separate eleLoad/pattern needed).")

# --- 3. Ground-bearing base fixity (reuses InterfaceDetection as-is) -----
node_z_by_tag = {int(t): float(c[2]) for t, c in zip(node_tags_all, node_coords_all)}

volume_node_ids = {}
volume_z_ranges = {}
for vol in vol_tags:
    _etypes, _etags, enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
    if not enodes or len(enodes[0]) == 0:
        continue
    vol_nodes = sorted(set(int(n) for n in enodes[0]))
    zs = [node_z_by_tag[n] for n in vol_nodes if n in node_z_by_tag]
    if not zs:
        continue
    volume_node_ids[vol] = vol_nodes
    volume_z_ranges[vol] = (min(zs), max(zs))

ground_volumes = InterfaceDetection.find_ground_bearing_volumes(candidates, volume_z_ranges)
print(f"{len(ground_volumes)}/{len(volume_z_ranges)} volumes identified as ground-bearing")

BASE_TOL = 0.05
base_ids_set = set()
for vol in ground_volumes:
    local_zmin = volume_z_ranges[vol][0]
    for n in volume_node_ids[vol]:
        if node_z_by_tag[n] <= local_zmin + BASE_TOL:
            base_ids_set.add(n)
base_ids_all = np.asarray(sorted(base_ids_set), dtype=np.int64)
print(f"{len(base_ids_all)} nodes fixed, across {len(ground_volumes)} ground-bearing volumes")
assert len(base_ids_all) > 0
fix_nodes(base_ids_all, "XYZ")

# --- 3b. Tie the walls the source geometry left disconnected --------------
# ~21 junctions have their two solids drawn 1.5-47 mm apart, so fragment()
# never fused them and those walls brace nothing. See
# core.opensees_generation.junction_ties for why this is done with MPCs
# rather than by healing the geometry (every geometric route was tried and
# either failed or made the topology worse).
# Re-locate on the REFINED mesh: the volume tags are the same (only the
# mesh was regenerated in pass 2), but node membership is entirely new, so
# the pass-1 node sets cannot be reused for tie-building. The PAIRS are
# still valid though, so restrict the search to them.
print("\n--- open junctions on the refined mesh ---")
open_junctions = _locate_open_junctions(
    only_pairs=[(a, b) for a, b, _g in open_junctions])
print(f"{len(open_junctions)} open junction(s) within {MAX_JUNCTION_GAP} m")

ties, tie_counts = find_junction_ties(
    open_junctions, volume_node_ids, coord_by_tag,
    excluded_nodes=set(int(n) for n in base_ids_all),
    max_tie_distance=MAX_TIE_DISTANCE,
)
for va, vb, gap in open_junctions:
    print(f"  vol {va:4d} <-> {vb:4d}: gap {gap*1000:6.2f} mm -> "
          f"{tie_counts.get((va, vb), 0)} tie(s)")
n_applied = apply_ties(ties, ops)
print(f"{n_applied} equalDOF constraint(s) applied across "
      f"{sum(1 for c in tie_counts.values() if c)} of {len(open_junctions)} junctions")
untied = [(va, vb) for (va, vb), c in tie_counts.items() if c == 0]
if untied:
    print(f"WARNING: {len(untied)} junction(s) got NO tie (no node pair within "
          f"{MAX_TIE_DISTANCE} m): "
          f"{', '.join(f'{a}-{b}' for a, b in untied)}")

with open(f"{OUT_DIR}/junction_ties.txt", "w") as fh:
    fh.write("# master_node,slave_node,distance_m\n")
    for _m, _s, _d in ties:
        fh.write(f"{_m},{_s},{_d:.6f}\n")

# A junction with no tie of its own is only a problem if its two walls end
# up in different pieces of the structure. Asking that pair-by-pair is the
# wrong question: these junctions come in clusters (several volumes meeting
# at one corner), and a greedy tie-builder that uses each node once can
# legitimately leave pair A-B untied while connecting both A and B through
# a third volume at the same corner. So check CONNECTIVITY, not pairing:
# build the graph of volumes joined either by shared mesh nodes (fragment()
# fused them) or by a tie, and see whether the untied pairs are connected
# in it anyway.
_owner = {}
_adj = {}


def _link(a, b):
    if a != b:
        _adj.setdefault(a, set()).add(b)
        _adj.setdefault(b, set()).add(a)


for _v, _ns in volume_node_ids.items():
    _adj.setdefault(_v, set())
    for _n in _ns:
        _prev = _owner.get(_n)
        if _prev is None:
            _owner[_n] = _v
        else:
            _link(_prev, _v)
_adj_geom = {k: set(v) for k, v in _adj.items()}  # before the ties
for _m, _s, _d in ties:
    if _m in _owner and _s in _owner:
        _link(_owner[_m], _owner[_s])


def _connected(a, b, max_hops=4):
    seen, frontier = {a}, {a}
    for _ in range(max_hops):
        frontier = {n for f in frontier for n in _adj.get(f, ())} - seen
        if b in frontier:
            return True
        if not frontier:
            return False
        seen |= frontier
    return False


if untied:
    print("\n--- are the untied junctions connected some other way? ---")
    isolated = []
    for va, vb in untied:
        ok_conn = _connected(va, vb)
        print(f"  vol {va:4d} <-> {vb:4d}: "
              f"{'connected through the cluster' if ok_conn else 'NOT CONNECTED'}")
        if not ok_conn:
            isolated.append((va, vb))
    print(f"{len(untied) - len(isolated)}/{len(untied)} untied junction(s) are "
          f"connected anyway; {len(isolated)} genuinely isolated")

# The same question asked globally. Reported BOTH with and without the
# ties on purpose: the aggregate is already one connected piece through the
# 600+ fused pairs, so a post-tie count of 1 on its own would prove nothing
# about the ties. The open junctions are a LOCAL bracing defect (a wall
# attached to the block at one end and free where it should abut its
# orthogonals), not a global disconnection, and the evidence that the ties
# fixed it is the modal reordering, not this number. It is here to keep
# that distinction visible rather than to be quoted as the success metric.
def _components(graph):
    n, seen = 0, set()
    for v in graph:
        if v in seen:
            continue
        n += 1
        stack = [v]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            stack.extend(graph.get(c, ()))
    return n


print(f"\nstructure connectivity over {len(_adj)} volumes: "
      f"{_components(_adj_geom)} component(s) from shared mesh nodes alone, "
      f"{_components(_adj)} with the ties")
_comp = _components(_adj)

if TIES_ONLY:
    gmsh.finalize()
    sys.exit(0)

# --- 4. Static self-weight solve ------------------------------------------
# Self-weight is already baked into every element's body force (step 2) -
# no load pattern needed, a single equilibrium solve is enough (there is no
# incremental/ramped load to step through, unlike a pattern-based load).
ops.system("UmfPack")
ops.numberer("RCM")
# Transformation, NOT Plain: Plain silently ignores multi-point
# constraints, so every equalDOF above would be applied and do nothing.
ops.constraints("Transformation")
ops.test("NormDispIncr", 1e-6, 30, 1)
ops.algorithm("Newton")
ops.integrator("LoadControl", 1.0)
ops.analysis("Static")
ok = ops.analyze(1)
print(f"Static self-weight analysis returned: {ok}")
assert ok == 0, f"static analysis did not converge (ok={ok})"

ops.reactions()
total_reaction = sum(ops.nodeReaction(int(n), 3) for n in base_ids_all)
total_weight = RHO * (-G_ACCEL) * total_volume
err_pct = 100.0 * (total_reaction - total_weight) / total_weight
print(f"Self-weight calculated (rho*g*V): {total_weight:.1f} N")
print(f"Total vertical base reaction:      {total_reaction:.1f} N")
print(f"Difference: {err_pct:.3f}%")

selfweight_disp = get_displacements_at_nodes(node_tags_sorted)  # (N,3), rows match node_tags_sorted
with open(f"{OUT_DIR}/selfweight_displacement.txt", "w") as f:
    for tag, d in zip(node_tags_sorted, selfweight_disp):
        f.write(f"{int(tag)},{float(d[0])!r},{float(d[1])!r},{float(d[2])!r}\n")
print(f"Wrote {OUT_DIR}/selfweight_displacement.txt")

# --- 5. Eigenvalue analysis ------------------------------------------------
eigenvalues = ops.eigen(N_MODES)
print(f"Eigenvalues: {eigenvalues}")
with open(f"{OUT_DIR}/eigenvalues.txt", "w") as f:
    for lam in eigenvalues:
        f.write(f"{lam}\n")

modal_props_path = os.path.abspath(f"{OUT_DIR}/modal_properties.txt")
ops.modalProperties("-print", "-file", modal_props_path)
print(f"Wrote {modal_props_path}")

# Undeformed node coordinates, for a separate plotting script - sorted
# order, matching get_displacements_at_nodes/get_eigenvector_at_nodes's own
# internal numpy.unique() sort (see the node_tags_sorted comment above).
with open(f"{OUT_DIR}/node_coords.txt", "w") as f:
    for tag, coord in zip(node_tags_sorted, node_coords_sorted):
        f.write(f"{int(tag)},{float(coord[0])!r},{float(coord[1])!r},{float(coord[2])!r}\n")

for mode in range(1, N_MODES + 1):
    disp = get_eigenvector_at_nodes(node_tags_sorted, mode=mode)
    path = f"{OUT_DIR}/mode{mode}_eigenvector.txt"
    with open(path, "w") as f:
        for tag, d in zip(node_tags_sorted, disp):
            f.write(f"{int(tag)},{float(d[0])!r},{float(d[1])!r},{float(d[2])!r}\n")
    print(f"Wrote {path}")

summary = {
    "framework": "native gmsh + external.gmsh2opensees + openseespy (sequential)",
    "young_modulus_MPa": E_MPA,
    "poisson_ratio": NU,
    "density_kg_m3": RHO,
    "total_volume_m3": total_volume,
    "self_weight_calculated_N": total_weight,
    "total_base_reaction_N": total_reaction,
    "weight_reaction_diff_pct": err_pct,
    "n_modes": N_MODES,
    "open_junctions": len(open_junctions),
    "equaldof_constraints": n_applied,
    "junctions_without_own_tie": [f"{a}-{b}" for a, b in untied],
    "disconnected_components": _comp,
    "mesh_nodes": len(node_tags_all),
    "mesh_elements": len(element_tags),
    "global_mesh_size_m": GLOBAL_MESH_SIZE,
}
with open(f"{OUT_DIR}/summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"Wrote {OUT_DIR}/summary.json")

print("\nDone.")
