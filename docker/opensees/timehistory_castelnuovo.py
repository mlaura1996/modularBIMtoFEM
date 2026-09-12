"""Nonlinear time-history of the Castelnuovo aggregate: ASDConcrete3D
damage + Task A contact interfaces + the equalDOF junction ties.

This is the first script that puts all three together. Each existed on its
own - eigen_castelnuovo_tied.py has the ties (linear, modal),
full_aggregate_with_interfaces_clean.py has the contact interfaces, and
model_builder.Element.create_plastic_damage_elements has the damage
material - but nothing combined them, and they do not simply compose.

WHY THEY DO NOT SIMPLY COMPOSE
------------------------------
The ties and the interfaces are opposite operations on the same kind of
object. NodeSplitter DUPLICATES the nodes of an interface surface and
rebuilds one side's tetrahedra against the duplicates, so a
zeroLengthContactASDimplex can decouple the two walls. The junction ties
do the reverse: equalDOF between nodes that should have been one node.

Those never clash on the same PAIR of volumes - find_open_junctions skips
anything fragment() already fused, and a Task A interface is by definition
a fused pair. Measured on this model: zero pairs in common.

But they do clash on individual VOLUMES. Two volumes carry both:

    volume  91   Task A interface 58-91 (11.653 m^2, the largest selected)
                 open junctions 91-101, 91-102, 91-103, 91-107
    volume 107   Task A interface 86-107 (1.089 m^2)
                 open junctions 105-107, 106-107, 91-107, 92-107, 96-107,
                 99-107, 107-110, 107-118, 107-280, 107-281

and NodeSplitter.assign_split_side picks volume_b - which is 91 and 107 in
both cases - as the side that gets duplicated. So if any node used by a
tie also sits on one of those two interface surfaces, that node's
tetrahedra in volume 91/107 now reference orig_tag + TAG_OFFSET, while the
tie still references orig_tag. The tie would then connect the neighbouring
wall to a node its own wall no longer uses: applied without error,
carrying no load, and invisible in any output. The walls would silently be
disconnected again - the exact defect this whole exercise was about.

So the overlap is CHECKED, not assumed, and the run aborts if it exists
(see "conflict guard" below). Whether it actually occurs depends on the
mesh, which is why it is a runtime check and not a comment.

WHAT THIS COSTS
---------------
Measured on an i7-10750H (benchmark_transient.py): ~5 s per stiffness
factorisation at 101,634 free DOFs, and 499 s just to build the LINEAR
model. The damage material is far slower to build - it creates one
ASDConcrete3D per element (120k of them; autoRegularization needs each
element's own crack-band length) with a gmsh query per element. Budget
tens of minutes for setup alone, and 25-70 h for a 20 s record depending
on iterations per step. Run --smoke first.

UNITS: SI throughout (m, Pa, kg, N, s). core/config.py's STEP_UNIT='M' and
FourNodeTetrahedron takes nodal coordinates as given.

    # wiring check, coarse mesh, few steps - minutes, run this FIRST
    python docker/opensees/timehistory_castelnuovo.py --smoke

    # the real thing
    python docker/opensees/timehistory_castelnuovo.py \
        --record resources/records/<name>.AT2 --duration 20 --dt 0.005
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

from external.gmsh2opensees.g2o_nodes_functions import (
    get_all_nodes, add_nodes_to_ops, fix_nodes,
)
from core.opensees_generation.model_builder import ModelBuilder, Element
from core.opensees_generation.junction_ties import find_junction_ties, apply_ties
from core.mesh_generation.geometry_healing import find_open_junctions
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)

# --- arguments ------------------------------------------------------------
SMOKE = "--smoke" in sys.argv


def argval(flag, default=None, cast=str):
    if flag in sys.argv:
        return cast(sys.argv[sys.argv.index(flag) + 1])
    return default


STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
OUT_DIR = argval("--out-dir", "output/castelnuovo/recorders_timehistory"
                 + ("_smoke" if SMOKE else ""))
# The Chapter 6 record, already converted to m/s^2 in the repository, so the
# scale factor is 1.0 and not 9.81: applying a g-conversion on top would be
# a silent factor of 10 on the input. See the file's own header.
RECORD = argval("--record",
                "resources/records/castelnuovo/montenegro1979_run21_long.txt")
RECORD_SCALE = argval("--record-scale", 1.0, float)
# 0.005 s and ~3900 increments are Chapter 6's own setup for this record
# ("the transient analysis spans the strong motion window with a nominal
# step of the same order ... for a total of approximately 3900
# increments"), i.e. a 19.5 s window out of the record's full 38.9 s. The
# PGA falls at t = 12.345 s, well inside it.
DURATION = argval("--duration", 0.05 if SMOKE else 19.5, float)
DT = argval("--dt", 0.005, float)
# Chapter 6 applied the longitudinal component in y. Castelnuovo has its own
# orientation and its mass-carrying modes are mode 1 in X (PRMx 20.98%) and
# mode 7 in Y (PRMy 18.44%), so the direction is a parameter rather than
# inherited: 1 = X, 2 = Y.
EXC_DOF = argval("--dof", 1, int)

# The smoke run exists to test the WIRING, not the physics: a coarse mesh
# with no junction refinement builds in a couple of minutes instead of
# tens, and 10 steps is enough to prove gravity converged, the contact
# elements engage and the transient advances. It will produce fewer ties
# (the facing nodes end up ~0.6 m apart at this size - the reason the real
# run refines locally at all), so do NOT read tie counts off a smoke run.
GLOBAL_MESH_SIZE = 0.6
JUNCTION_MESH_SIZE = 0.6 if SMOKE else 0.10
JUNCTION_REFINE_RADIUS = 0.4
MAX_JUNCTION_GAP = 0.05
MAX_TIE_DISTANCE = 0.10

# --- material: the same equal-weighted average of the four HMO/MQI types
# already adopted for the modal analysis, now with the strengths
# ASDConcrete3D also needs. fm per type: 3.445 / 2.616 / 2.099 / 2.616 MPa
# (docs/source/case_study/materials.md, type D = B by construction), so the
# equal-weighted mean is 2.694 MPa. Tensile strength follows that document's
# own rule, ft = fc x (0.17/1.30), the ft/fc ratio of the Chapter 6
# SERA-AIMS reference masonry - HMO has no rule for ft.
# Gc/Gt are left at 0 so create_plastic_damage_elements applies its
# code-formula fallbacks (CEB-FIP MC90); pass measured values here if they
# ever exist for this masonry.
E_MPA = 1227.95
NU = 0.2
RHO = 1450.0
FC_MPA = 2.694
FT_MPA = FC_MPA * (0.17 / 1.30)

# --- contact interface stiffnesses. The brief's Chapter 6/7 reference
# values are Kn=69000, Kt=0.001 per unit area in the N-mm-ton system;
# 1 N/mm^3 = 1e9 N/m^3, so they are scaled by 1e9 for the SI model here -
# the same conversion test_task_ab_reconciled.py applies.
KN_NOMINAL = 69000.0 * 1e9
KT_NOMINAL = 0.001 * 1e9
MU_FRICTION = 0.6

# --- damping. Chapter 6's own convention: "The target ratio of 3% is
# imposed at the first and tenth modes" - so 3% anchored at modes 1 and 10,
# not at modes 1 and 2. Frequencies from the 80-mode tied run: mode 1 =
# 5.786 Hz, mode 10 = 10.695 Hz. That bracket happens to contain every mode
# that carries appreciable mass here (modes 1-9 hold 51.7% X / 54.8% Y),
# which is exactly why anchoring at 1 and 10 works: inside the bracket the
# damping dips below the target, outside it rises, and the mass-carrying
# modes are all inside.
F1_HZ, F2_HZ = 5.786, 10.695
XI = argval("--damping", 0.03, float)

G_ACCEL = 9.81
os.makedirs(OUT_DIR, exist_ok=True)
LOG = open(f"{OUT_DIR}/progress.log", "w", buffering=1)


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")


say(f"{'SMOKE' if SMOKE else 'FULL'} run -> {OUT_DIR}")

# --- ground motion --------------------------------------------------------
def read_record(path):
    """PEER .AT2 or a plain whitespace-separated list of accelerations.

    AT2 carries its own dt in the 4th header line ('NPTS=..., DT=...');
    a plain file does not, so --dt is used as the record's own step there.
    Returned unscaled - RECORD_SCALE is applied by the caller, and is
    9.81 by default because records are normally in g while this model is
    in m/s^2. Getting that factor wrong is a silent 10x on the input.
    """
    with open(path) as fh:
        lines = fh.readlines()
    if path.lower().endswith(".at2"):
        header = lines[3]
        rec_dt = None
        for token in header.replace(",", " ").split():
            if token.upper().startswith("DT="):
                rec_dt = float(token.split("=")[1])
        if rec_dt is None:
            parts = header.replace(",", " ").split()
            for i, t in enumerate(parts):
                if t.upper() == "DT" and i + 1 < len(parts):
                    rec_dt = float(parts[i + 1])
        if rec_dt is None:
            raise ValueError(f"could not read DT from the AT2 header: {header!r}")
        values = [float(x) for line in lines[4:] for x in line.split()]
        return np.asarray(values), rec_dt
    values = [float(x) for line in lines for x in line.split()]
    return np.asarray(values), DT


if RECORD:
    if not os.path.isfile(RECORD):
        sys.exit(f"Record not found: {RECORD}")
    accel_raw, record_dt = read_record(RECORD)
    accel = accel_raw * RECORD_SCALE
    say(f"record {os.path.basename(RECORD)}: {len(accel)} points, dt={record_dt} s, "
        f"peak {np.abs(accel).max():.3f} m/s^2 "
        f"({np.abs(accel).max()/G_ACCEL:.3f} g) after x{RECORD_SCALE}")
elif SMOKE:
    # A ramp, not a real record: the smoke run tests that the transient
    # advances and the contact engages, and inventing a synthetic
    # "earthquake" here would only invite someone to read physics off it.
    record_dt = DT
    accel = 0.5 * np.sin(2 * np.pi * F1_HZ * np.arange(0, DURATION + DT, DT))
    say(f"smoke run: synthetic {F1_HZ} Hz sine, peak {np.abs(accel).max():.3f} m/s^2 "
        f"- NOT a seismic input, do not interpret the response")
else:
    sys.exit("--record is required for a full run (no ground motion is "
             "committed in this repository). Use --smoke to test the wiring.")

# --- 1. geometry and interface selection (BEFORE meshing) ----------------
t0 = time.perf_counter()
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("castelnuovo_timehistory")
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
say(f"{len(selected)} Task A interfaces selected from {SELECTION_PATH}")
for c in selected:
    say(f"    vol {c['volume_a']}-{c['volume_b']} area {c['area_m2']:.3f} m^2 "
        f"split side {c['split_volume']} surface {c['surface']}")

# --- 2. two-pass mesh ----------------------------------------------------
gmsh.model.mesh.setOrder(1)   # Tet4: create_plastic_damage_elements builds
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)   # FourNodeTetrahedron


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

# --- 3. OpenSees model ---------------------------------------------------
ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

node_tags_all, node_coords_all = get_all_nodes(gmsh.model)
add_nodes_to_ops(node_tags_all, gmsh.model)
n_nodes = len(node_tags_all)
coord_by_tag = {int(t): c for t, c in zip(node_tags_all, node_coords_all)}
node_z = {int(t): float(c[2]) for t, c in zip(node_tags_all, node_coords_all)}
say(f"{n_nodes} nodes added")

# Duplicate nodes for the contact interfaces. Computed and created BEFORE
# the elements, because the tetrahedra of each split volume have to be
# built against the duplicates - which is what node_substitution does.
# create_duplicate_nodes does compute_node_map's work itself and returns
# the same substitution map, so calling both would recompute every
# interface's nodal tributary areas twice (a gmsh query per face element).
substitution = NodeSplitter.create_duplicate_nodes(gmsh.model, selected)
duplicated_originals = {orig for m in substitution.values() for orig in m}
say(f"{len(duplicated_originals)} interface nodes duplicated across "
    f"{len(substitution)} split volume(s)")

t0 = time.perf_counter()
material = Material(
    name="Masonry", density=RHO, young_modulus=E_MPA, poisson_ratio=NU,
    is_structural=True, material_model_type="PlasticDamage",
    compressive_strength=FC_MPA, tensile_strength=FT_MPA,
    compression_fracture_energy=0, tensile_fracture_energy=0,
    compressive_elastic_behaviour=0,
)
say("building elements with ASDConcrete3D (one material per element - "
    "this is the slow part, tens of minutes on the full mesh)...")
element_tags = Element.add_elements_to_opensees(
    gmsh.model, {"Masonry": material}, node_substitution=substitution)
say(f"{len(element_tags)} elements added ({time.perf_counter()-t0:.1f} s)")

# --- 4. base fixity ------------------------------------------------------
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
            base_ids.add(n)
base_arr = np.asarray(sorted(base_ids), dtype=np.int64)
fix_nodes(base_arr, "XYZ")
say(f"{len(base_arr)} base nodes fixed across {len(ground_volumes)} "
    f"ground-bearing volumes")

# --- 5. junction ties, with the conflict guard ---------------------------
ties, tie_counts = find_junction_ties(
    open_junctions, volume_node_ids, coord_by_tag,
    excluded_nodes=set(int(n) for n in base_arr),
    max_tie_distance=MAX_TIE_DISTANCE)

# THE GUARD. See the module docstring: a node that is both tied and
# duplicated makes its tie reference a node its own wall's elements no
# longer use. equalDOF accepts it, nothing errors, and the junction is
# silently open again.
tie_nodes = {int(m) for m, _s, _d in ties} | {int(s) for _m, s, _d in ties}
conflict = tie_nodes & duplicated_originals
if conflict:
    say(f"ABORT: {len(conflict)} node(s) are both tied and duplicated at a "
        f"contact interface: {sorted(conflict)[:20]}")
    say("Those ties would be applied and carry no load - the junction would "
        "be open again with nothing in the output to show it. Resolve by "
        "flipping the split side for the affected interface "
        "(NodeSplitter.assign_split_side picks volume_b, which is 91 and "
        "107 here - exactly the two volumes that also carry ties), or by "
        "tying the duplicate instead of the original where the node is on "
        "an interface. Not guessed at automatically: which is right depends "
        "on whether that face should transmit contact or continuity.")
    sys.exit(2)
say(f"conflict guard passed: no tied node is also an interface duplicate")

n_applied = apply_ties(ties, ops)
say(f"{n_applied} equalDOF constraints across "
    f"{sum(1 for c in tie_counts.values() if c)} of {len(open_junctions)} junctions")

# --- 6. contact elements -------------------------------------------------
contact = ContactInterfaceGenerator.generate(
    selected, Kn_nominal=KN_NOMINAL, Kt_nominal=KT_NOMINAL, mu=MU_FRICTION)
n_contact = sum(len(c["elements"]) for c in contact)
say(f"{n_contact} zeroLengthContactASDimplex elements on "
    f"{len(contact)} interfaces")

# --- 7. static gravity (nonlinear, stepped) ------------------------------
# Self-weight is already a body force on every element (rho*G baked in by
# create_plastic_damage_elements), so there is no load pattern to ramp -
# but the solve is nonlinear now, and the contact has to find its closed
# state, so it is stepped rather than solved in one go.
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")   # mandatory: Plain ignores equalDOF
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
    say("ABORT: gravity did not converge. A time-history on a model that "
        "cannot carry its own weight is meaningless - fix this first.")
    sys.exit(3)

reaction_z = 0.0
ops.reactions()
for n in base_arr:
    reaction_z += ops.nodeReaction(int(n), 3)
weight = RHO * G_ACCEL * total_volume
say(f"self-weight check: calculated {weight:,.1f} N vs reaction "
    f"{abs(reaction_z):,.1f} N -> {abs(abs(reaction_z)-weight)/weight*100:.3f} %")

# Gravity is the initial condition for the earthquake, not part of it.
ops.loadConst("-time", 0.0)

# --- 8. transient --------------------------------------------------------
# Rayleigh from the two mass-carrying modes (see F1_HZ/F2_HZ above).
w1, w2 = 2 * math.pi * F1_HZ, 2 * math.pi * F2_HZ
a0 = 2 * XI * w1 * w2 / (w1 + w2)
a1 = 2 * XI / (w1 + w2)
ops.rayleigh(a0, a1, 0.0, 0.0)
say(f"Rayleigh: {XI*100:.1f}% at {F1_HZ} and {F2_HZ} Hz -> "
    f"alphaM={a0:.5f}, betaK={a1:.6f}")

ops.timeSeries("Path", 1, "-dt", record_dt, "-values", *[float(a) for a in accel])
ops.pattern("UniformExcitation", 1, EXC_DOF, "-accel", 1)
say(f"UniformExcitation applied in dof {EXC_DOF} "
    f"({'X' if EXC_DOF == 1 else 'Y' if EXC_DOF == 2 else 'Z'})")

# --- recorders -----------------------------------------------------------
# The output quantities are the ones Chapter 6 reports, so the two chapters
# can be compared without re-deriving anything: damage pattern, roof
# displacement, base shear (for the hysteretic loops), interface opening,
# and the strain tensor from which principal strains are computed in
# post-processing.
#
# Written as the run proceeds, so an interruption loses only the tail.
#
# A caveat that has to be stated rather than hidden: the exact response
# STRINGS for ASDConcrete3D through FourNodeTetrahedron are not verified
# here, because this machine is not running the analysis. OpenSees does not
# raise on an unknown element response - it creates the recorder and writes
# an empty file - so several candidate names are registered and
# check_recorders() below reports which ones actually produced data after
# the first steps. Run --smoke on the target machine and read that report
# before launching the full analysis; a 30-hour run that turns out to have
# written empty damage files is the whole point of doing this.
recorder_files = {}


def add_recorder(label, *args):
    path = f"{OUT_DIR}/{label}.txt"
    try:
        tag = ops.recorder(*(list(args[:1]) + ["-file", path] + list(args[1:])))
        recorder_files[label] = path
        return tag
    except Exception as exc:            # noqa: BLE001 - report, do not abort
        say(f"  recorder {label!r} rejected outright: {exc}")
        return None


# Roof displacement (Rd in Chapter 6's notation): the highest nodes.
top_nodes = sorted(node_z, key=lambda n: -node_z[n])[:20]
add_recorder("roof_disp", "Node", "-time",
             "-node", *[int(n) for n in top_nodes], "-dof", 1, 2, 3, "disp")
add_recorder("roof_accel", "Node", "-time",
             "-node", *[int(n) for n in top_nodes], "-dof", 1, 2, 3, "accel")
# Base shear (BS): every fixed node's reaction, summed in post-processing.
add_recorder("base_reaction", "Node", "-time",
             "-node", *[int(n) for n in base_arr], "-dof", 1, 2, 3, "reaction")
# Interface opening (Id): both sides of every contact pair, so the relative
# displacement across the joint is a subtraction in post-processing.
if_pairs = [(o, d) for c in selected for o, d in c["node_map"].items()]
if if_pairs:
    if_nodes = sorted({int(n) for pair in if_pairs for n in pair})
    add_recorder("interface_disp", "Node", "-time",
                 "-node", *if_nodes, "-dof", 1, 2, 3, "disp")
    with open(f"{OUT_DIR}/interface_node_pairs.txt", "w") as fh:
        fh.write("# original_node,duplicate_node,interface_key\n")
        for c in selected:
            k = InterfaceSelection.key_for(c)
            for o, d in c["node_map"].items():
                fh.write(f"{o},{d},{k}\n")
    say(f"{len(if_pairs)} interface node pairs recorded for the opening (Id)")

# Contact element forces at the inter-unit joint.
contact_eles = [e for c in contact for e in c["elements"]]
if contact_eles:
    add_recorder("contact_force", "Element", "-time",
                 "-ele", *[int(e) for e in contact_eles], "force")

# Damage and strain on the solid elements. Recording all 120k elements at
# every step would write hundreds of GB, so a subset is sampled - every
# SOLID_SAMPLE-th element - plus every element of the volumes that carry a
# contact interface or a tie, which are where the damage is expected.
SOLID_SAMPLE = 1 if SMOKE else 20
interesting_vols = ({c["volume_a"] for c in selected} |
                    {c["volume_b"] for c in selected} |
                    {v for a, b, _g in open_junctions for v in (a, b)})
focus_eles = set()
for v in interesting_vols:
    _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
    for tags in etg:
        focus_eles.update(int(t) for t in tags)
sampled = set(int(e) for e in element_tags[::SOLID_SAMPLE]) | focus_eles
sampled = sorted(sampled & set(int(e) for e in element_tags))
say(f"{len(sampled)} of {len(element_tags)} solid elements recorded "
    f"(every {SOLID_SAMPLE}th, plus all {len(focus_eles)} in the "
    f"{len(interesting_vols)} volumes carrying an interface or a tie)")

# Strain tensor: 6 components per element. Principal strains are the
# eigenvalues of that tensor and are NOT an OpenSees output - they are
# computed by scripts/postprocess_timehistory.py from this file.
add_recorder("solid_strain", "Element", "-time",
             "-ele", *sampled, "material", "1", "strain")
add_recorder("solid_stress", "Element", "-time",
             "-ele", *sampled, "material", "1", "stress")
# ASDConcrete3D damage. Candidate response names, all registered: whichever
# writes a non-empty file is the right one on this build.
for cand in ("damage", "Damage", "damage_tension", "equivalent_plastic_strain",
             "crack_width"):
    add_recorder(f"solid_{cand}", "Element", "-time",
                 "-ele", *sampled, "material", "1", cand)
say(f"{len(recorder_files)} recorders registered")

ops.wipeAnalysis()
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")
# Chapter 6's setup, verbatim: "Convergence is checked with an energy
# increment criterion, using a tolerance of 1e-3 and a limit of 200
# iterations per step. The energy norm is preferred to a displacement or
# force norm because it remains more balanced in the presence of localised
# stiffness loss and distributed cracking." And "a Newton iteration
# augmented by a line search, which improves robustness when the tangent
# stiffness degrades as the masonry softens."
ops.test("EnergyIncr", 1e-3, 200, 0)
ops.algorithm("NewtonLineSearch")
# TRBDF2, not Newmark. Chapter 6 again: the composite trapezoidal/backward-
# difference scheme gives stronger numerical damping at high frequencies,
# which suppresses the spurious oscillations that contact and softening
# generate, while leaving the low-frequency response essentially
# unaffected. A model with cracking, interface opening and pounding is
# precisely the case it exists for - using Newmark here would depart from
# the chapter's own method for no reason.
ops.integrator("TRBDF2")
ops.analysis("Transient")


def check_recorders(after_what):
    """Report which recorders actually wrote data. OpenSees accepts an
    unknown element response and then writes nothing, so an empty file
    means the response string is wrong on this build - not that the
    quantity is zero."""
    say(f"--- recorder check after {after_what} ---")
    empty = []
    for label, path in sorted(recorder_files.items()):
        size = os.path.getsize(path) if os.path.exists(path) else -1
        state = ("MISSING" if size < 0 else "EMPTY" if size == 0
                 else f"{size/1024:.1f} kB")
        say(f"    {label:34s} {state}")
        if size <= 0:
            empty.append(label)
    if empty:
        say(f"    {len(empty)} recorder(s) wrote nothing: {', '.join(empty)}. "
            f"For the solid_* ones that means the response name is not valid "
            f"on this OpenSees build; keep the ones that worked and drop the "
            f"rest before the full run.")
    return empty

n_steps = int(round(DURATION / DT))
say(f"transient: {n_steps} steps of {DT} s ({DURATION} s), "
    f"nonlinear + contact")
t_start = time.perf_counter()
failures = 0
for step in range(1, n_steps + 1):
    ok = ops.analyze(1, DT)
    if ok != 0:
        # One retry at a tenth of the step. Contact and damage both cause
        # steps that Newton cannot take at full size but can at a smaller
        # one; giving up on the first failure would end most runs early,
        # and pressing on without retrying would silently drop the step.
        sub_ok = 0
        for _ in range(10):
            sub_ok = ops.analyze(1, DT / 10.0)
            if sub_ok != 0:
                break
        if sub_ok != 0:
            failures += 1
            say(f"step {step}/{n_steps} failed at DT and DT/10 "
                f"(failure {failures})")
            if failures >= 5:
                say("ABORT: 5 steps failed to converge even subdivided. "
                    "Report the response up to here and say it stopped - "
                    "do not present a truncated run as a complete one.")
                break
        else:
            say(f"step {step}/{n_steps} needed subdivision into 10")
    if step == 5:
        check_recorders("5 steps")
    if step % max(1, n_steps // 50) == 0 or step == n_steps:
        el = time.perf_counter() - t_start
        eta = el / step * (n_steps - step)
        say(f"step {step}/{n_steps}  t={ops.getTime():.3f} s  "
            f"elapsed {el/3600:.2f} h  ETA {eta/3600:.2f} h")

wall = time.perf_counter() - t_start
say(f"transient finished: {wall/3600:.2f} h, {failures} non-converged step(s)")
empty_recorders = check_recorders("the whole run")

summary = {
    "run": "smoke" if SMOKE else "full",
    "record": os.path.basename(RECORD) if RECORD else "synthetic sine (smoke)",
    "record_scale_to_m_s2": RECORD_SCALE,
    "duration_s": DURATION,
    "dt_s": DT,
    "steps_requested": n_steps,
    "steps_failed": failures,
    "final_time_s": ops.getTime(),
    "mesh_nodes": n_nodes,
    "mesh_elements": len(element_tags),
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
    "interface_nodes_duplicated": len(duplicated_originals),
    "Kn_nominal_N_m3": KN_NOMINAL,
    "Kt_nominal_N_m3": KT_NOMINAL,
    "friction": MU_FRICTION,
    "damping_ratio": XI,
    "rayleigh_anchor_Hz": [F1_HZ, F2_HZ],
    "rayleigh_alphaM": a0,
    "rayleigh_betaK": a1,
    "base_nodes_fixed": len(base_arr),
    "self_weight_N": weight,
    "base_reaction_N": abs(reaction_z),
    "wall_time_transient_h": wall / 3600.0,
    "excitation_dof": EXC_DOF,
    "integrator": "TRBDF2",
    "algorithm": "NewtonLineSearch",
    "convergence_test": "EnergyIncr 1e-3, 200 iterations",
    "solid_elements_recorded": len(sampled),
    "recorders_written": sorted(set(recorder_files) - set(empty_recorders)),
    "recorders_empty": sorted(empty_recorders),
}
with open(f"{OUT_DIR}/summary.json", "w") as fh:
    json.dump(summary, fh, indent=2)
say(f"wrote {OUT_DIR}/summary.json")

# RESTART: there is none, and it should not be improvised. ASDConcrete3D
# carries damage state per element; restoring it from recorded nodal
# displacements is not possible, and OpenSees' database save/restore does
# not cover solid-element internal state reliably. So a run that dies at
# hour 20 restarts from zero. Mitigate by preventing the interruption -
# disable automatic restarts on the machine, run detached rather than in a
# terminal that can be closed - not by trusting a restart path that has
# not been verified.
say("done.")
LOG.close()
gmsh.finalize()
