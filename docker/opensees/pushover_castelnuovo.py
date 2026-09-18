"""Nonlinear static pushover of the Castelnuovo aggregate: same model as
timehistory_castelnuovo.py (ASDConcrete3D damage + Task A contact
interfaces + the equalDOF junction ties), but loaded with a first-mode-
proportional lateral load pattern under DisplacementControl instead of
the recorded ground motion.

Sections 1-7 (geometry, two-pass mesh, node/tie/element/contact
construction, static gravity) are copied verbatim from
timehistory_castelnuovo.py - see that file's own docstring for why the
ties and the interfaces do not simply compose, and why the invariant
check after the ties exists. Only what happens after gravity converges is
new: an eigenvalue analysis on the gravity-loaded model to find which
mode actually carries the X-direction mass (not assumed to be mode 1 on
this mesh - the tied modal analysis that found mode 1 = X-dominant,
PRMx 20.98%, ran on a different, coarser mesh; this script re-derives it
on its own mesh rather than trust that carries over), a mass x eigenvector
load pattern from that mode, and a DisplacementControl loop at a fixed
control node with the same adaptive step-halving fallback used in the
Chapter 4/6-era in_plane_wall.py pushover, generalised from a single wall
to this aggregate's contact+damage model.

CONTROL NODE: NOT the same one scripts/postprocess_timehistory.py picks
for Rd (the time-history's highest-|disp| roof node) - tried that first,
on the real desktop smoke test, and it diverged on the very first
pushover step (load factor in the tens of millions), twice, including
after also excluding tied nodes. The time-history's Rd criterion answers
a different question (which point moved most under the actual, broadband
earthquake record) than a modal pushover needs (which point the load
PATTERN itself - built from a single mode shape - actually moves), and a
point that is a near-node of that mode's own shape needs an enormous load
factor to displace at all under a pattern proportional to it. The control
node here is instead the untied, upper-half-of-the-building node where
the chosen mode's own eigenvector is largest in magnitude - the
conventional choice for a modal pushover control point, and one that by
construction cannot be a near-node of the pattern driving it.

STOPPING CRITERION: the loop also stops once the base shear has dropped
below STRENGTH_DROP_FRACTION of its own running peak - the standard
"near-collapse" pushover criterion - so it does not grind on into a
regime with no structural meaning once the capacity curve has clearly
peaked and softened.

UNITS: SI throughout (m, Pa, kg, N, s), matching timehistory_castelnuovo.py.

    # wiring check, coarse mesh, few steps - minutes
    python docker/opensees/pushover_castelnuovo.py --smoke

    # the real thing, same mesh as the completed time-history run
    python docker/opensees/pushover_castelnuovo.py --mesh-size 0.3 \
        --solid-sample 1 --out-dir output/castelnuovo/pushover_mesh03
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, "/app")

import numpy as np
import gmsh
import openseespy.opensees as ops

from external.gmsh2opensees.g2o_nodes_functions import get_all_nodes, add_nodes_to_ops
from core.opensees_generation.model_builder import ModelBuilder, Element
from core.opensees_generation.junction_ties import find_junction_ties, apply_ties
from core.opensees_generation.element_sampling import select_recorded_elements
from core.mesh_generation.geometry_healing import find_open_junctions
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)

# --- arguments --------------------------------------------------------------
SMOKE = "--smoke" in sys.argv


def argval(flag, default=None, cast=str):
    if flag in sys.argv:
        return cast(sys.argv[sys.argv.index(flag) + 1])
    return default


STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
OUT_DIR = argval("--out-dir", "output/castelnuovo/pushover" + ("_smoke" if SMOKE else ""))
EXC_DOF = argval("--dof", 1, int)   # 1 = X, matching the time-history's default

GLOBAL_MESH_SIZE = 0.6 if SMOKE else argval("--mesh-size", 0.6, float)
JUNCTION_MESH_SIZE = 0.6 if SMOKE else 0.10
JUNCTION_REFINE_RADIUS = 0.4
MAX_JUNCTION_GAP = 0.05
MAX_TIE_DISTANCE = 0.10

# --- material: identical to timehistory_castelnuovo.py ---------------------
E_MPA = 1227.95
NU = 0.2
RHO = 1450.0
FC_MPA = 2.694
FT_MPA = FC_MPA * (0.17 / 1.30)

KN_NOMINAL = 69000.0 * 1e9
KT_NOMINAL = 0.001 * 1e9
MU_FRICTION = 0.6

# --- pushover-specific parameters -------------------------------------------
N_MODES_SCAN = argval("--n-modes-scan", 10, int)   # how many modes to check
                                                     # for X-mass participation
DU = argval("--du", 0.001 if not SMOKE else 0.01, float)          # m per step
TARGET_DRIFT = argval("--target-drift", 0.02, float)               # 2% default
STRENGTH_DROP_FRACTION = argval("--strength-drop", 0.6, float)     # stop once
                                                                     # BS < 60% of
                                                                     # its own peak
STEP_FACTORS = (1.0, 0.5, 0.2, 0.1, 0.05, 0.01)   # subdivision fallback,
                                                    # matches in_plane_wall.py's
                                                    # philosophy, finer floor

G_ACCEL = 9.81
os.makedirs(OUT_DIR, exist_ok=True)
LOG = open(f"{OUT_DIR}/progress.log", "w", buffering=1)


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")


say(f"{'SMOKE' if SMOKE else 'FULL'} pushover run -> {OUT_DIR}")

# --- 1. geometry and interface selection (BEFORE meshing) ------------------
t0 = time.perf_counter()
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("castelnuovo_pushover")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
vol_tags = [t for _d, t in gmsh.model.getEntities(3)]
total_volume = sum(gmsh.model.occ.getMass(3, t) for t in vol_tags)
say(f"{len(vol_tags)} volumes, {total_volume:.2f} m^3 ({time.perf_counter()-t0:.1f} s)")

pg_tag = gmsh.model.addPhysicalGroup(3, vol_tags)
gmsh.model.setPhysicalName(3, pg_tag, "Masonry")

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)
touching = {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
            for c in candidates}
say(f"{len(candidates)} touching surface pairs detected")

selected = InterfaceSelection.load_selected(SELECTION_PATH, candidates)
NodeSplitter.assign_split_side(selected)
ContactInterfaceGenerator.tag_physical_groups(selected)
say(f"{len(selected)} contact interfaces selected from {SELECTION_PATH}")

# --- 2. two-pass mesh (identical logic to timehistory_castelnuovo.py) ------
gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)


def bbox_adjacent(a, b, tol=MAX_JUNCTION_GAP):
    return (a[0] - tol <= b[3] and b[0] - tol <= a[3] and
            a[1] - tol <= b[4] and b[1] - tol <= a[4] and
            a[2] - tol <= b[5] and b[2] - tol <= a[5])


def min_dist(pa, pb):
    best = np.inf
    for s in range(0, len(pa), 512):
        blk = pa[s:s + 512]
        best = min(best, float(np.sqrt(((blk[:, None, :] - pb[None, :, :]) ** 2)
                                       .sum(axis=2).min())))
        if best == 0.0:
            break
    return best


def near_bbox(pts, bbox, tol):
    if len(pts) == 0:
        return pts
    lo, hi = np.array(bbox[:3]) - tol, np.array(bbox[3:]) + tol
    return pts[np.all((pts >= lo) & (pts <= hi), axis=1)]


def locate_open_junctions(only_pairs=None):
    ntags, ncoords, _ = gmsh.model.mesh.getNodes()
    cbt = {int(t): c for t, c in zip(ntags, ncoords.reshape(-1, 3))}
    bbox, nodes, pts = {}, {}, {}
    for v in vol_tags:
        bbox[v] = gmsh.model.occ.getBoundingBox(3, v)
        _e1, _e2, en = gmsh.model.mesh.getElements(dim=3, tag=v)
        st = set(int(x) for x in en[0]) if (en and len(en[0])) else set()
        nodes[v] = st
        pts[v] = np.array([cbt[t] for t in st]) if st else np.zeros((0, 3))
    pair_iter = (list(only_pairs) if only_pairs is not None else
                 [(vol_tags[i], vb) for i in range(len(vol_tags))
                  for vb in vol_tags[i + 1:]])
    found = []
    for va, vb in pair_iter:
        if (min(va, vb), max(va, vb)) in touching:
            continue
        if not bbox_adjacent(bbox[va], bbox[vb]) or (nodes[va] & nodes[vb]):
            continue
        pa = near_bbox(pts[va], bbox[vb], MAX_JUNCTION_GAP)
        pb = near_bbox(pts[vb], bbox[va], MAX_JUNCTION_GAP)
        if len(pa) == 0 or len(pb) == 0:
            continue
        d = min_dist(pa, pb)
        if d <= MAX_JUNCTION_GAP:
            found.append((va, vb, d))
    found.sort(key=lambda t: t[2])
    return found


t0 = time.perf_counter()
say("meshing (pass 1, locating open junctions)...")
gmsh.model.mesh.generate(3)
open_junctions = locate_open_junctions()
say(f"{len(open_junctions)} open junctions ({time.perf_counter()-t0:.1f} s)")

if not SMOKE:
    face_jobs = find_open_junctions(
        vol_tags, touching, max_gap=MAX_JUNCTION_GAP,
        only_pairs={(min(a, b), max(a, b)) for a, b, _g in open_junctions},
        measured_gaps={(min(a, b), max(a, b)): g for a, b, g in open_junctions})
    junction_faces = sorted({f for j in face_jobs
                             for f in (j["face_small"], j["face_big"])})
    say(f"refining to {JUNCTION_MESH_SIZE} m around {len(junction_faces)} "
        f"facing surfaces from {len(face_jobs)} junctions")
    gmsh.model.mesh.clear()
    df = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(df, "SurfacesList", junction_faces)
    gmsh.model.mesh.field.setNumber(df, "Sampling", 30)
    tf = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(tf, "InField", df)
    gmsh.model.mesh.field.setNumber(tf, "SizeMin", JUNCTION_MESH_SIZE)
    gmsh.model.mesh.field.setNumber(tf, "SizeMax", GLOBAL_MESH_SIZE)
    gmsh.model.mesh.field.setNumber(tf, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(tf, "DistMax", JUNCTION_REFINE_RADIUS)
    gmsh.model.mesh.field.setAsBackgroundMesh(tf)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    t0 = time.perf_counter()
    say("meshing (pass 2)...")
    gmsh.model.mesh.generate(3)
    say(f"meshing done ({time.perf_counter()-t0:.1f} s)")
    open_junctions = locate_open_junctions(
        only_pairs=[(a, b) for a, b, _g in open_junctions])
    say(f"{len(open_junctions)} open junctions on the refined mesh")

gmsh.option.setNumber("Mesh.SaveAll", 1)
gmsh.write(f"{OUT_DIR}/mesh.msh")
say(f"wrote {OUT_DIR}/mesh.msh")

n_mesh_nodes = len(gmsh.model.mesh.getNodes()[0])
n_mesh_elements = 0
for v in vol_tags:
    _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
    if etg:
        n_mesh_elements += len(etg[0])
say(f"mesh: {n_mesh_nodes} nodes, {n_mesh_elements} elements "
    f"(global size {GLOBAL_MESH_SIZE} m)")

if "--mesh-only" in sys.argv:
    say("--mesh-only: stopping before element/material construction.")
    gmsh.finalize()
    sys.exit(0)

# --- 3. OpenSees model -------------------------------------------------------
ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

node_tags_all, node_coords_all = get_all_nodes(gmsh.model)
add_nodes_to_ops(node_tags_all, gmsh.model)
n_nodes = len(node_tags_all)
coord_by_tag = {int(t): c for t, c in zip(node_tags_all, node_coords_all)}
node_z = {int(t): float(c[2]) for t, c in zip(node_tags_all, node_coords_all)}
say(f"{n_nodes} nodes added")

substitution = NodeSplitter.create_duplicate_nodes(gmsh.model, selected)
duplicated_originals = {orig for m in substitution.values() for orig in m}
say(f"{len(duplicated_originals)} interface nodes duplicated across "
    f"{len(substitution)} split volume(s)")

# --- 4. base fixity, junction ties and the invariant check ------------------
def element_node(vol, n):
    return substitution.get(vol, {}).get(n, n)


volume_node_ids, volume_z_ranges = {}, {}
for vol in vol_tags:
    _et, _etg, en = gmsh.model.mesh.getElements(dim=3, tag=vol)
    if not en or len(en[0]) == 0:
        continue
    vn = sorted(set(int(n) for n in en[0]))
    zs = [node_z[n] for n in vn if n in node_z]
    if not zs:
        continue
    volume_node_ids[vol] = vn
    volume_z_ranges[vol] = (min(zs), max(zs))

ground_volumes = InterfaceDetection.find_ground_bearing_volumes(
    candidates, volume_z_ranges)
BASE_TOL = 0.05
base_ids = set()
for vol in ground_volumes:
    zmin = volume_z_ranges[vol][0]
    for n in volume_node_ids[vol]:
        if node_z[n] <= zmin + BASE_TOL:
            base_ids.add(element_node(vol, n))
base_arr = np.asarray(sorted(base_ids), dtype=np.int64)
for n in base_arr:
    ops.fix(int(n), 1, 1, 1)
n_base_dups = int(sum(1 for n in base_arr if n >= NodeSplitter.TAG_OFFSET))
say(f"{len(base_arr)} base nodes fixed across {len(ground_volumes)} "
    f"ground-bearing volumes ({n_base_dups} of them interface duplicates)")

ties, tie_counts, tie_vols = find_junction_ties(
    open_junctions, volume_node_ids, coord_by_tag,
    excluded_nodes=base_ids,
    max_tie_distance=MAX_TIE_DISTANCE,
    node_substitution=substitution, return_volumes=True)

elem_nodes = {v: {element_node(v, n) for n in ns}
              for v, ns in volume_node_ids.items()}
dangling = [(m, s, va, vb) for (m, s, _d), (va, vb) in zip(ties, tie_vols)
            if m not in elem_nodes.get(va, ()) or s not in elem_nodes.get(vb, ())]
if dangling:
    say(f"ABORT: {len(dangling)} tie(s) reference a node that the elements of "
        f"their own volume do not use: {dangling[:10]}")
    sys.exit(2)
say("invariant check passed: every tie endpoint belongs to its volume's elements")

n_applied = apply_ties(ties, ops)
say(f"{n_applied} equalDOF constraints across "
    f"{sum(1 for c in tie_counts.values() if c)} of {len(open_junctions)} junctions")

# --- 5. elements (the slow stage) -------------------------------------------
t0 = time.perf_counter()
material = Material(
    name="Masonry", density=RHO, young_modulus=E_MPA, poisson_ratio=NU,
    is_structural=True, material_model_type="PlasticDamage",
    compressive_strength=FC_MPA, tensile_strength=FT_MPA,
    compression_fracture_energy=0, tensile_fracture_energy=0,
    compressive_elastic_behaviour=0,
)
say("building elements with ASDConcrete3D...")
element_tags = Element.add_elements_to_opensees(
    gmsh.model, {"Masonry": material}, node_substitution=substitution)
say(f"{len(element_tags)} elements added ({time.perf_counter()-t0:.1f} s)")

# --- 6. contact elements ------------------------------------------------------
contact = ContactInterfaceGenerator.generate(
    selected, Kn_nominal=KN_NOMINAL, Kt_nominal=KT_NOMINAL, mu=MU_FRICTION)
n_contact = sum(len(c["elements"]) for c in contact)
say(f"{n_contact} zeroLengthContactASDimplex elements on "
    f"{len(contact)} interfaces")

# --- 7. static gravity --------------------------------------------------------
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")
ops.test("EnergyIncr", 1e-3, 200, 1)
ops.algorithm("NewtonLineSearch")
GRAVITY_STEPS = 2 if SMOKE else 10
ops.integrator("LoadControl", 1.0 / GRAVITY_STEPS)
ops.analysis("Static")
t0 = time.perf_counter()
say(f"static gravity in {GRAVITY_STEPS} steps...")
ok = ops.analyze(GRAVITY_STEPS)
say(f"static gravity returned {ok} ({time.perf_counter()-t0:.1f} s)")
if ok != 0:
    say("ABORT: gravity did not converge.")
    sys.exit(3)

reaction_z = 0.0
ops.reactions()
for n in base_arr:
    reaction_z += ops.nodeReaction(int(n), 3)
weight = RHO * G_ACCEL * total_volume
say(f"self-weight check: calculated {weight:,.1f} N vs reaction "
    f"{abs(reaction_z):,.1f} N -> {abs(abs(reaction_z)-weight)/weight*100:.3f} %")

ops.loadConst("-time", 0.0)

# --- 8. eigenvalue analysis on the gravity-loaded model, to find the mode ---
# that actually carries the X-direction mass on THIS mesh. Not assumed to
# be mode 1: the tied modal analysis that found mode 1 = X-dominant (PRMx
# 20.98%) ran on a different, coarser mesh with junction ties but no
# contact interfaces or damage material - not verified to transfer here.
t0 = time.perf_counter()
say(f"eigenvalue analysis, first {N_MODES_SCAN} modes, to find the "
    f"X-dominant mode for the load pattern...")
eigenvalues = ops.eigen(N_MODES_SCAN)
say(f"eigen done ({time.perf_counter()-t0:.1f} s)")

all_node_tags = [int(t) for t in node_tags_all]

# Nodal mass, computed directly from element geometry (tributary volume x
# RHO / 4 per tetrahedron corner) rather than queried via ops.nodeMass().
# ops.nodeMass() only reports mass assigned through an explicit `mass`
# command - it does NOT reflect the mass contribution FourNodeTetrahedron
# + ASDConcrete3D's own `-rho` bakes into the assembled mass matrix (the
# same mass UniformExcitation's -M*ag(t) and Rayleigh's alphaM*M actually
# use). Querying it here returned exactly 0.0 for every node on the real
# desktop run (confirmed: 0.00% X participating mass on all 10 scanned
# modes, and a load pattern with 0 nodes loaded) - not a subtle numerical
# issue, ops.nodeMass() simply is not the right query for element-implied
# mass. Recomputed independently here so it never depends on that guess
# again; checked against the known total (RHO * total_volume, already
# verified via the gravity self-weight check above).
coord_by_tag_full = dict(coord_by_tag)
for vol_map in substitution.values():
    for orig, dup in vol_map.items():
        if orig in coord_by_tag_full:
            coord_by_tag_full[dup] = coord_by_tag_full[orig]

node_mass_x = {n: 0.0 for n in all_node_tags}
n_mass_warnings = 0
for tag in element_tags:
    try:
        ele_nodes = ops.eleNodes(int(tag))
    except Exception:
        n_mass_warnings += 1
        continue
    if len(ele_nodes) != 4:
        n_mass_warnings += 1
        continue
    try:
        p = np.array([coord_by_tag_full[int(n)] for n in ele_nodes], dtype=float)
    except KeyError:
        n_mass_warnings += 1
        continue
    vol = abs(np.dot(p[1] - p[0], np.cross(p[2] - p[0], p[3] - p[0]))) / 6.0
    m_corner = RHO * vol / 4.0
    for n in ele_nodes:
        n = int(n)
        node_mass_x[n] = node_mass_x.get(n, 0.0) + m_corner
if n_mass_warnings:
    say(f"  WARNING: {n_mass_warnings} element(s) skipped while computing "
        f"nodal mass (unexpected node count or missing coordinates)")
total_mass_x = sum(node_mass_x.values())
say(f"  computed total mass {total_mass_x:,.1f} kg vs RHO*total_volume "
    f"{RHO*total_volume:,.1f} kg (should match closely)")

best_mode, best_participation, best_phi = None, -1.0, None
for mode in range(1, N_MODES_SCAN + 1):
    phi = {}
    for n in all_node_tags:
        try:
            phi[n] = ops.nodeEigenvector(n, mode, EXC_DOF)
        except Exception:
            phi[n] = 0.0
    num = sum(node_mass_x[n] * phi[n] for n in all_node_tags)
    den = sum(node_mass_x[n] * phi[n] ** 2 for n in all_node_tags)
    participation_mass = (num ** 2 / den / total_mass_x) if den > 0 else 0.0
    freq_hz = math.sqrt(max(eigenvalues[mode - 1], 0.0)) / (2 * math.pi)
    say(f"  mode {mode}: {freq_hz:.3f} Hz, X participating mass "
        f"{participation_mass*100:.2f}%")
    if participation_mass > best_participation:
        best_mode, best_participation, best_phi = mode, participation_mass, phi

say(f"using mode {best_mode} ({best_participation*100:.2f}% X mass) for the "
    f"first-mode-proportional load pattern")

# --- 9. control node - chosen from where MODE `best_mode` ITSELF displaces
# most, not from the time-history's own criterion (highest node, biggest
# peak displacement during the earthquake). Those are different questions:
# the time-history's response is broadband, so a roof point can show a
# large peak there even if mode 1 specifically has almost no displacement
# at that exact point (a near-node of that mode's shape) - and a
# DisplacementControl pushover under a mode-1-proportional pattern IS
# entirely governed by mode 1's own shape, so commanding a displacement
# at a point the pattern barely moves needs an enormous load factor to
# produce ANY response there at all. This is the second, more likely
# explanation for the divergence seen on the real desktop smoke test
# (load factor in the tens of millions, unchanged in order of magnitude
# after excluding tied nodes - so that fix, while still worth keeping,
# was not the actual cause). Also excludes tied nodes (a master/slave in
# a junction tie has its DOF partly eliminated by the Transformation
# constraint handler - see the tie note kept below) and restricts the
# search to the upper half of the building by elevation, since a roof-
# level control point is still what a pushover capacity curve is
# conventionally reported against.
tied_node_tags = {int(m) for m, s, _d in ties} | {int(s) for m, s, _d in ties}
z_values = list(node_z.values())
z_mid = (max(z_values) + min(z_values)) / 2.0
upper_untied = [n for n in all_node_tags
               if node_z[n] >= z_mid and n not in tied_node_tags]
if not upper_untied:
    say("  no untied node in the upper half - falling back to all untied nodes")
    upper_untied = [n for n in all_node_tags if n not in tied_node_tags]

# Further restrict to the volumes that belong to the SAME connected
# component in the equalDOF tie graph as the largest such component (the
# building's "main body"). A volume that only touches its neighbours
# through the unilateral contact interfaces (no equalDOF tie - some
# open_junctions never qualify for one, see "n_applied ... of {len(open_
# junctions)} junctions" above) offers little resistance in some
# directions, so a control node picked there needs a disproportionate
# global force to move by even a small amount - the same failure mode as
# the earlier "highest untied node" bug, one level deeper. This is checked
# even for the reference-step-selected "mass" control node above (recomputed
# there too), since a locally-weak point can still look like "the biggest
# response" to a tiny reference load without being a structurally sound
# place to drive a whole pushover from.
vol_adjacency = {}
for va, vb in tie_vols:
    vol_adjacency.setdefault(va, set()).add(vb)
    vol_adjacency.setdefault(vb, set()).add(va)
visited_vols, components = set(), []
for v in volume_node_ids:
    if v in visited_vols:
        continue
    comp, stack = set(), [v]
    while stack:
        cur = stack.pop()
        if cur in comp:
            continue
        comp.add(cur)
        visited_vols.add(cur)
        stack.extend(vol_adjacency.get(cur, set()) - comp)
    components.append(comp)
main_component = max(
    components, key=lambda c: sum(len(volume_node_ids[v]) for v in c))
say(f"  {len(components)} volume cluster(s) by tie connectivity - main "
    f"cluster has {len(main_component)} of {len(volume_node_ids)} volumes")
main_component_nodes = {element_node(v, n) for v in main_component
                        for n in volume_node_ids[v]}
upper_untied_main = [n for n in upper_untied if n in main_component_nodes]
if upper_untied_main:
    upper_untied = upper_untied_main
else:
    say("  no untied upper candidate in the main tie-connected cluster - "
        "keeping the unrestricted candidate list")

# LOAD_PATTERN_TYPE: "mode1" (default) failed to converge on the real
# desktop smoke test even after the mass and tied-node fixes - load
# factor still in the millions on every step-size fallback, unchanged in
# order of magnitude regardless of which node was tried. "mass" is a
# deliberately simpler, diagnostic alternative (uniform mass-proportional
# pattern, F_i = m_i - NTC18/EC8's "uniform" pattern, not the first-mode
# one originally requested) to isolate whether the problem is specific to
# the eigenvector-based pattern/control-node construction or is more
# fundamental to a static DisplacementControl push on this contact+damage
# model (which so far has only ever been solved with LoadControl, for
# gravity, or Transient, for the earthquake - never a static
# DisplacementControl push, so this combination is genuinely unverified
# regardless of pattern shape).
LOAD_PATTERN_TYPE = argval("--load-pattern", "mode1")
model_height = max(node_z.values()) - min(node_z.values())

ops.wipeAnalysis()
ops.timeSeries("Linear", 2)
ops.pattern("Plain", 2, 2)
n_loaded = 0

if LOAD_PATTERN_TYPE == "mass":
    # eleLoad -selfWeight, not nodal ops.load() with the hand-computed
    # tributary mass: this is the SAME mechanism gravity already uses
    # successfully (Element.create_plastic_damage_elements bakes rho*G into
    # every element's own body force; this is that same body-force command,
    # horizontal instead of vertical, at unit "acceleration" so the
    # DisplacementControl load factor is a physically legible multiple of
    # g). Reuses proven code instead of the custom per-node mass computed
    # above (which stays in use for the mode1 pattern below, since a modal
    # shape varies per node and -selfWeight can only apply one uniform
    # acceleration to a whole element set).
    body_force = [0.0, 0.0, 0.0]
    body_force[EXC_DOF - 1] = 1.0
    ops.eleLoad("-ele", *[int(e) for e in element_tags], "-type", "-selfWeight",
               *body_force)
    n_loaded = len(element_tags)
    say(f"mass-proportional (uniform) load pattern applied via eleLoad "
        f"-selfWeight to {n_loaded} elements - the same body-force "
        f"mechanism gravity uses, horizontal instead of vertical")

    # Control node: NOT simply the highest untied node (tried that on the
    # real desktop full run - it converged, but produced a vertical
    # displacement 2.6-3x larger than the horizontal one it was supposed to
    # be controlling, consistently from the very first step, not something
    # that developed alongside the later base-shear jump). That means the
    # chosen point responds poorly to THIS pattern in the X direction, so
    # reaching even a small target displacement there needs a
    # disproportionately large load factor, which then over-drives the
    # rest of the structure. Fixed the same way as the mode1 pattern's own
    # control-node problem: measure the actual response to the pattern
    # rather than guess from height alone - here, empirically, with a
    # small real reference step under LoadControl before switching to
    # DisplacementControl, since a uniform pattern has no eigenvector to
    # consult instead.
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    ops.test("EnergyIncr", 1e-3, 200, 0)
    ops.algorithm("NewtonLineSearch")
    REFERENCE_LOAD_FACTOR = 0.01
    ops.integrator("LoadControl", REFERENCE_LOAD_FACTOR)
    ops.analysis("Static")
    ref_ok = ops.analyze(1)
    if ref_ok != 0:
        say("ABORT: the small reference LoadControl step (to calibrate the "
            "control node) did not even converge - the mass pattern itself "
            "cannot be carried, independent of which node controls it.")
        sys.exit(4)
    control_node = max(upper_untied, key=lambda n: abs(ops.nodeDisp(n, EXC_DOF)))
    say(f"control node: {control_node} (z={node_z[control_node]:.3f} m, "
        f"X-disp under the {REFERENCE_LOAD_FACTOR} reference load factor = "
        f"{ops.nodeDisp(control_node, EXC_DOF)*1000:.4f} mm) - the untied "
        f"candidate that actually responds most to this pattern in X, not "
        f"just the tallest one")
else:
    control_node = max(upper_untied, key=lambda n: abs(best_phi.get(n, 0.0)))
    say(f"control node: {control_node} (z={node_z[control_node]:.3f} m, "
        f"|phi_mode{best_mode}|={abs(best_phi[control_node]):.4e} - the largest "
        f"mode-{best_mode} displacement among {len(upper_untied)} untied "
        f"candidates in the upper half of the building)")
    for n in all_node_tags:
        fx = node_mass_x[n] * best_phi[n]
        if fx != 0.0:
            load_vec = [0.0, 0.0, 0.0]
            load_vec[EXC_DOF - 1] = fx
            ops.load(n, *load_vec)
            n_loaded += 1
    say(f"first-mode-proportional load pattern applied to {n_loaded} nodes")

# --- 11. pushover analysis settings - same robustness as the time-history's -
# transient phase (EnergyIncr/NewtonLineSearch): this is the same contact +
# damage model, and it needs the same convergence machinery, not the
# looser NormDispIncr the single-wall in_plane_wall.py used.
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")
ops.test("EnergyIncr", 1e-3, 200, 0)
ops.algorithm("NewtonLineSearch")
ops.integrator("DisplacementControl", control_node, EXC_DOF, DU)
ops.analysis("Static")

target_disp = TARGET_DRIFT * model_height
n_steps = int(round(target_disp / DU))
say(f"pushover: target drift {TARGET_DRIFT*100:.2f}% = {target_disp*1000:.1f} mm "
    f"at control node {control_node}, dU={DU*1000:.2f} mm, up to {n_steps} steps, "
    f"stop if base shear < {STRENGTH_DROP_FRACTION*100:.0f}% of its own peak")

# --- 12. element sampling for damage/strain snapshots per step -------------
# A pushover has far fewer steps than the transient (tens-hundreds, not
# 3900), so recording every element at every step is tractable here even
# without stride-sampling - pass --solid-sample to override if the mesh
# is large enough that this stops being true.
SOLID_SAMPLE = 1 if SMOKE else argval("--solid-sample", 1, int)
sampled, interesting_vols, focus_eles = select_recorded_elements(
    element_tags, selected, open_junctions, SOLID_SAMPLE)
say(f"{len(sampled)} of {len(element_tags)} solid elements recorded "
    f"(every {SOLID_SAMPLE}th, plus all {len(focus_eles)} in the "
    f"{len(interesting_vols)} volumes carrying an interface or a tie)")
with open(f"{OUT_DIR}/sampled_elements.txt", "w") as fh:
    fh.write("# element_index,element_tag\n")
    for i, tag in enumerate(sampled):
        fh.write(f"{i},{tag}\n")

recorder_files = {}


def add_recorder(label, *args):
    path = f"{OUT_DIR}/{label}.txt"
    try:
        tag = ops.recorder(*(list(args[:1]) + ["-file", path] + list(args[1:])))
        recorder_files[label] = path
        return tag
    except Exception as exc:            # noqa: BLE001
        say(f"  recorder {label!r} rejected outright: {exc}")
        return None


add_recorder("control_disp", "Node", "-time", "-node", control_node,
             "-dof", 1, 2, 3, "disp")
add_recorder("base_reaction", "Node", "-time",
             "-node", *[int(n) for n in base_arr], "-dof", 1, 2, 3, "reaction")
# Full-field nodal displacement - every node, all 3 DOFs, every step. Not
# recorded in timehistory_castelnuovo.py at all (only roof_disp's 20-node
# subset, per-step there was already the bottleneck at 3900 steps) - a
# pushover has far fewer steps (tens, not thousands), so recording every
# node is tractable here, and this is what a deformed-shape view in gmsh
# actually needs: per-node displacement, not the per-element strain/damage
# fields the time-history's viewer scripts use.
add_recorder("node_disp", "Node", "-time",
             "-node", *all_node_tags, "-dof", 1, 2, 3, "disp")
add_recorder("solid_strain", "Element", "-time",
             "-ele", *sampled, "material", "1", "strain")
for cand in ("damage", "Damage", "damage_tension"):
    add_recorder(f"solid_{cand}", "Element", "-time",
                 "-ele", *sampled, "material", "1", cand)

weight_n = weight

# --- 13. pushover loop, with the adaptive step-halving fallback ------------
csv_path = f"{OUT_DIR}/pushover_curve.csv"
csv_fh = open(csv_path, "w", buffering=1)
csv_fh.write("step,disp_m,drift_ratio,base_shear_N,base_shear_over_W\n")

d0 = ops.nodeDisp(control_node, EXC_DOF)
peak_bs = 0.0
t_start = time.perf_counter()
step = 0
stopped_reason = None
while step < n_steps:
    step += 1
    ok = None
    for factor in STEP_FACTORS:
        ops.integrator("DisplacementControl", control_node, EXC_DOF, DU * factor)
        ok = ops.analyze(1)
        if ok == 0:
            break
        say(f"  step {step}, dU factor {factor} failed, trying smaller")
    if ok != 0:
        stopped_reason = f"step {step} failed to converge even at the smallest step factor"
        say(f"ABORT: {stopped_reason}")
        break

    ops.reactions()
    disp = ops.nodeDisp(control_node, EXC_DOF) - d0
    bs = -sum(ops.nodeReaction(int(n), EXC_DOF) for n in base_arr)
    drift = disp / model_height
    csv_fh.write(f"{step},{disp:.8e},{drift:.8e},{bs:.6e},{bs/weight_n:.6e}\n")

    peak_bs = max(peak_bs, abs(bs))
    if peak_bs > 0 and abs(bs) < STRENGTH_DROP_FRACTION * peak_bs and step > 10:
        stopped_reason = (f"base shear ({abs(bs):.1f} N) dropped below "
                          f"{STRENGTH_DROP_FRACTION*100:.0f}% of its own peak "
                          f"({peak_bs:.1f} N) - near-collapse criterion reached")
        say(f"stopping: {stopped_reason}")
        break

    if step % max(1, n_steps // 50) == 0 or step == n_steps:
        el = time.perf_counter() - t_start
        say(f"step {step}/{n_steps}  disp={disp*1000:.2f} mm  "
            f"drift={drift*100:.3f}%  BS={bs:.1f} N ({bs/weight_n:.3f} W)  "
            f"elapsed {el/3600:.2f} h")

csv_fh.close()
wall = time.perf_counter() - t_start
say(f"pushover finished: {wall/3600:.2f} h, {step} step(s) run, "
    f"stopped because: {stopped_reason or 'target drift reached'}")

ops.remove("recorders")

summary = {
    "run": "smoke" if SMOKE else "full",
    "analysis_type": "pushover",
    "mesh_nodes": n_nodes,
    "mesh_elements": len(element_tags),
    "global_mesh_size_m": GLOBAL_MESH_SIZE,
    "solid_sample_stride": SOLID_SAMPLE,
    "total_volume_m3": total_volume,
    "young_modulus_MPa": E_MPA,
    "poisson_ratio": NU,
    "density_kg_m3": RHO,
    "compressive_strength_MPa": FC_MPA,
    "tensile_strength_MPa": FT_MPA,
    "material_model": "ASDConcrete3D (implex, autoRegularization)",
    "equaldof_constraints": n_applied,
    "open_junctions": len(open_junctions),
    "contact_elements": n_contact,
    "contact_interfaces": len(contact),
    "base_nodes_fixed": len(base_arr),
    "self_weight_N": weight,
    "base_reaction_N": abs(reaction_z),
    "excitation_dof": EXC_DOF,
    "eigen_modes_scanned": N_MODES_SCAN,
    "load_pattern_type": LOAD_PATTERN_TYPE,
    "load_pattern_mode": best_mode,
    "load_pattern_mode_X_participating_mass": best_participation,
    "control_node": control_node,
    "control_node_z_m": node_z[control_node],
    "control_node_mode_phi": best_phi[control_node],
    "model_height_m": model_height,
    "du_m": DU,
    "target_drift_ratio": TARGET_DRIFT,
    "strength_drop_fraction": STRENGTH_DROP_FRACTION,
    "steps_run": step,
    "stopped_reason": stopped_reason or "target drift reached",
    "peak_base_shear_N": peak_bs,
    "peak_base_shear_over_W": peak_bs / weight_n,
    "wall_time_h": wall / 3600.0,
    "integrator": "DisplacementControl",
    "algorithm": "NewtonLineSearch",
    "convergence_test": "EnergyIncr 1e-3, 200 iterations",
    "solid_elements_recorded": len(sampled),
}
with open(f"{OUT_DIR}/summary.json", "w") as fh:
    json.dump(summary, fh, indent=2)
say(f"wrote {OUT_DIR}/summary.json")

say("done.")
LOG.close()
gmsh.finalize()
