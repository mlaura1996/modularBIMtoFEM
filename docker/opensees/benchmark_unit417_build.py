"""Scalability benchmark on structural unit 417: builds the model and writes
the OpenSeesMP input for every process count.

WHAT IS MEASURED
----------------
How the wall time of a nonlinear time-history of a masonry building from
the pipeline changes with the number of MPI processes, on the same model,
the same ground motion and the same solver settings. The building is unit
417 of the Castelnuovo aggregate (the corner building on Vicolo del
Cabalino), extracted from the same cleaned STEP geometry as the Chapter 8
model, with the same materials, mesh size, damage model, integrator and
convergence test. Only the parallel layout changes between runs.

THE MODEL
---------
* Volumes: those whose centroid falls in the plan box of unit 417
  (x 13.8-21.3 m, y -17.3 to -7.4 m in the STEP frame), i.e. the walls of
  the three storeys, the wall shared with unit 418 and every opening
  element inside them.
* The shared wall followed the roof and the foundation of unit 418. It is
  cut to the eaves line of the other walls of unit 417 (z = 12.27 m at
  x = 14.09 m, 10.00 m at x = 21.09 m) and to the ground level z = 0 the
  other walls stand on, so the unit is a box of uniform height.
* Every junction is continuous. Walls fused by fragment() share nodes; the
  junctions the geometry leaves open (gaps of a few mm, see
  core/opensees_generation/junction_ties.py) are tied node to node, as in
  Chapter 8. No contact interface is modelled: a contact element is a
  modelling choice to be studied on its own, and here it would only add a
  source of convergence differences between runs.
* All nodes at z <= 0.01 m are fixed.
* Materials, ASDConcrete3D with one regularised material per element,
  self-weight as a body force, Rayleigh 3 % on modes 1 and 10 of the unit
  itself (computed here, linear elastic, with the same mesh and ties).

THE GROUND MOTION
-----------------
The Chapter 8 record, brought back to the time of the earthquake (time x
sqrt 2), restricted to a window around the peak: by default 15.0-18.0 s,
which contains the PGA (17.46 s) and the peak roof displacement of the
aggregate (17.95 s), so the steps measured are the ones where damage
develops and Newton needs the most iterations. The window starts with a
0.5 s cosine taper so the analysis does not begin with an acceleration
jump. 424 steps of 0.00707 s, the Chapter 8 step.

THE PARALLEL LAYOUT
-------------------
For every process count N the mesh is partitioned with METIS (gmsh's own
partitioner, the one apeGmsh calls) into N parts. Every rank defines every
node, the fixities and the ties (the standard OpenSeesMP idiom also used by
core/opensees_generation/tcl_export.py); each rank builds only the
elements of its own part and their materials. One Tcl file per rank, so a
rank does not parse the other ranks' materials.

The ties are equalDOF constraints by default, as in Chapter 8
(--ties equaldof). --ties penalty replaces each by a stiff twoNodeLink
instead, owned by one rank like an element - the fallback if the
transformation of constraints across subdomains turns out not to work on
the target build. On unit 417 the question does not arise: at 0.3 m the
mesh of the unit has no open junction (measured, 9 Nov 2026: 17,227 nodes,
60,977 elements, 0 ties), every junction of the unit is fused by
fragment(), and the model has no constraint besides the base fixity.

Measured on the laptop (i7-10750H, Docker on WSL2), 14 steps of the full
model: 7.3 s per step with MUMPS on 1 process, 4.4 s on 2, the same roof
displacement to every digit written. Each step converges in one iteration
(ASDConcrete3D with IMPL-EX is linear within the step), so the time per
step is one state determination plus one factorisation.

OUTPUT
------
<out-dir>/model/      common.tcl, analysis.tcl, accel_window.txt, mesh.msh
<out-dir>/model/np<N>/rank<r>.tcl
<out-dir>/run_<label>.tcl   one driver per run (sets the solver and N)
<out-dir>/build_summary.json

    # wiring check, coarse mesh, 2 processes, 20 steps - minutes
    python docker/opensees/benchmark_unit417_build.py --smoke --out-dir output/castelnuovo/benchmark_unit417_smoke

    # the benchmark model
    python docker/opensees/benchmark_unit417_build.py --out-dir /app_output/benchmark_unit417

docker/opensees/run_benchmark_unit417.sh runs the build and then every
configuration in sequence.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import gmsh

from core.mesh_generation.geometry_healing import find_open_junctions
from core.mesh_generation.wall_interfaces import InterfaceDetection
from core.opensees_generation.junction_ties import find_junction_ties
from core.opensees_generation.volume_materials import (
    load as load_volume_materials, add_physical_groups, materials_from_ifc, total_weight,
    summary as materials_summary)
from models.damage_law import ConstitutiveLaws

SMOKE = "--smoke" in sys.argv


def argval(flag, default=None, cast=str):
    if flag in sys.argv:
        return cast(sys.argv[sys.argv.index(flag) + 1])
    return default


STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
VOLUME_MATERIALS_PATH = "resources/survey_data/castelnuovo/volume_materials.json"
MATERIALS_IFC_PATH = "output/castelnuovo/castelnuovo_case.ifc"
RECORD = argval("--record", "resources/records/castelnuovo/montenegro1979_run21_long.txt")
TIME_SCALE = math.sqrt(2.0)          # Cauchy-Froude, as the Chapter 8 de-scaled run

OUT_DIR = os.path.abspath(argval("--out-dir", "output/castelnuovo/benchmark_unit417"
                                 + ("_smoke" if SMOKE else "")))
MODEL_DIR = os.path.join(OUT_DIR, "model")
NPARTS = [int(v) for v in argval("--nparts", "1,2" if SMOKE else "1,2,4,6,8").split(",")]
TIES = argval("--ties", "equaldof")
assert TIES in ("equaldof", "penalty"), "--ties is equaldof or penalty"

# plan box of unit 417 in the STEP frame (centroids), and the cut of the
# wall shared with unit 418
BOX = (13.8, 21.3, -17.3, -7.4)
EAVES = ((14.09, 12.27), (21.09, 10.00))     # (x, z) of the eaves line of unit 417


def z_eaves(x):
    (x0, z0), (x1, z1) = EAVES
    return z0 + (z1 - z0) * (x - x0) / (x1 - x0)


GLOBAL_MESH_SIZE = 0.6 if SMOKE else argval("--mesh-size", 0.3, float)
JUNCTION_MESH_SIZE = 0.10
JUNCTION_REFINE_RADIUS = 0.4
MAX_JUNCTION_GAP = 0.05
MAX_TIE_DISTANCE = 0.10
BASE_TOL = 0.01
PENALTY_K = 1.0e12                   # N/m, only for --ties penalty

T_START = argval("--t-start", 15.0, float)     # s, de-scaled time
T_END = argval("--t-end", 15.15 if SMOKE else 18.0, float)
TAPER = argval("--taper", 0.05 if SMOKE else 0.5, float)
DT = 0.005 * TIME_SCALE
EXC_DOF = 1
XI = 0.03
N_ROOF = 20
G_ACCEL = 9.81
G_BODY = -9.81

os.makedirs(MODEL_DIR, exist_ok=True)
LOG = open(os.path.join(OUT_DIR, "build.log"), "w", buffering=1)


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")


T_ALL = time.perf_counter()
say(f"{'SMOKE' if SMOKE else 'FULL'} build -> {OUT_DIR}")

# --- 1. geometry: the pipeline numbering, then unit 417 only --------------
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("unit417")
occ = gmsh.model.occ
gmsh.open(STEP_PATH)
occ.fragment(occ.getEntities(3), [])
occ.synchronize()
vol_material = load_volume_materials(VOLUME_MATERIALS_PATH)
all_vols = [t for _d, t in gmsh.model.getEntities(3)]


def centroid(t):
    return occ.getCenterOfMass(3, t)


keep = [t for t in all_vols
        if BOX[0] <= centroid(t)[0] <= BOX[1] and BOX[2] <= centroid(t)[1] <= BOX[3]]
say(f"{len(keep)} of {len(all_vols)} volumes in the plan box of unit 417")
occ.remove([(3, t) for t in all_vols if t not in keep], recursive=True)
occ.synchronize()
vol_before = sum(occ.getMass(3, t) for t in keep)


def vertices(t):
    return [gmsh.model.getValue(0, p[1], []) for p in
            gmsh.model.getBoundary([(3, t)], combined=False, oriented=False, recursive=True)]


# 2 cm tolerance: the walls of unit 417 itself end ON the eaves line (to the
# centimetre of the survey), and cutting them would leave slivers
to_cut = [t for t in keep if any(v[2] > z_eaves(v[0]) + 0.02 or v[2] < -0.02 for v in vertices(t))]
say(f"volumes above the eaves line or below ground: {to_cut}")
p = [occ.addPoint(x, -30.0, z_eaves(x)) for x in (5.0, 30.0)]
p += [occ.addPoint(30.0, -30.0, 40.0), occ.addPoint(5.0, -30.0, 40.0)]
loop = occ.addCurveLoop([occ.addLine(p[i], p[(i + 1) % 4]) for i in range(4)])
wedge = [e for e in occ.extrude([(2, occ.addPlaneSurface([loop]))], 0, 40.0, 0) if e[0] == 3]
ground = occ.addBox(5.0, -30.0, -10.0, 25.0, 40.0, 10.0)
material_of = {t: vol_material[t] for t in keep}
cut_out, cut_map = occ.cut([(3, t) for t in to_cut], wedge + [(3, ground)],
                           removeObject=True, removeTool=True)
current = [t for t in keep if t not in to_cut]
for t, pieces in zip(to_cut, cut_map):
    for _d, nt in pieces:
        material_of[nt] = material_of[t]
        current.append(nt)
# fragment again so the cut volumes stay conformal with their neighbours
frag_out, frag_map = occ.fragment([(3, t) for t in current], [])
occ.synchronize()
final_material = {}
for t, pieces in zip(current, frag_map):
    for _d, nt in pieces:
        final_material[nt] = material_of[t]
vol_tags = sorted(final_material)
total_volume = sum(occ.getMass(3, t) for t in vol_tags)
say(f"{len(vol_tags)} volumes, {total_volume:.2f} m^3 (before the cut {vol_before:.2f} m^3)")
material_groups = add_physical_groups(final_material, vol_tags)
for n, vs in material_groups.items():
    say(f"    {n}: {len(vs)} volumes")

candidates = InterfaceDetection.find_touching_surface_pairs()
touching = {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
            for c in candidates}
say(f"{len(candidates)} touching surface pairs")

# --- 2. mesh: the Chapter 8 two-pass mesh -----------------------------------
gmsh.model.mesh.setOrder(1)
gmsh.option.setNumber("Mesh.MeshSizeMax", GLOBAL_MESH_SIZE)


def bbox_adjacent(a, b, tol=MAX_JUNCTION_GAP):
    return (a[0] - tol <= b[3] and b[0] - tol <= a[3] and a[1] - tol <= b[4]
            and b[1] - tol <= a[4] and a[2] - tol <= b[5] and b[2] - tol <= a[5])


def min_dist(pa, pb):
    best = np.inf
    for s in range(0, len(pa), 512):
        blk = pa[s:s + 512]
        best = min(best, float(np.sqrt(((blk[:, None, :] - pb[None, :, :]) ** 2).sum(axis=2).min())))
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
        bbox[v] = occ.getBoundingBox(3, v)
        _e1, _e2, en = gmsh.model.mesh.getElements(dim=3, tag=v)
        st = set(int(x) for x in en[0]) if (en and len(en[0])) else set()
        nodes[v] = st
        pts[v] = np.array([cbt[t] for t in st]) if st else np.zeros((0, 3))
    pair_iter = (list(only_pairs) if only_pairs is not None else
                 [(vol_tags[i], vb) for i in range(len(vol_tags)) for vb in vol_tags[i + 1:]])
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
gmsh.model.mesh.generate(3)
open_junctions = locate_open_junctions()
say(f"mesh pass 1: {len(open_junctions)} open junctions ({time.perf_counter() - t0:.1f} s)")
for va, vb, gap in open_junctions:
    say(f"    {va}-{vb}: {gap * 1000:.1f} mm")
if open_junctions and not SMOKE:
    face_jobs = find_open_junctions(
        vol_tags, touching, max_gap=MAX_JUNCTION_GAP,
        only_pairs={(min(a, b), max(a, b)) for a, b, _g in open_junctions},
        measured_gaps={(min(a, b), max(a, b)): g for a, b, g in open_junctions})
    junction_faces = sorted({f for j in face_jobs for f in (j["face_small"], j["face_big"])})
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
    gmsh.model.mesh.generate(3)
    open_junctions = locate_open_junctions(only_pairs=[(a, b) for a, b, _g in open_junctions])
    say(f"mesh pass 2, refined to {JUNCTION_MESH_SIZE} m around {len(junction_faces)} "
        f"facing surfaces: {len(open_junctions)} open junctions ({time.perf_counter() - t0:.1f} s)")
gmsh.option.setNumber("Mesh.SaveAll", 1)
gmsh.write(os.path.join(MODEL_DIR, "mesh.msh"))

# --- 3. nodes, elements, base, ties ------------------------------------------
ntags, ncoords, _ = gmsh.model.mesh.getNodes()
ntags = ntags.astype(np.int64)
ncoords = ncoords.reshape(-1, 3)
coord_by_tag = {int(t): c for t, c in zip(ntags, ncoords)}

ele_tags, ele_conn, ele_vol = [], [], []
volume_node_ids = {}
for v in vol_tags:
    et, etg, en = gmsh.model.mesh.getElements(dim=3, tag=v)
    if not len(et):
        continue
    assert len(et) == 1 and et[0] == 4, f"volume {v}: element types {et}, expected Tet4 only"
    conn = np.asarray(en[0], dtype=np.int64).reshape(-1, 4)
    ele_tags.append(np.asarray(etg[0], dtype=np.int64))
    ele_conn.append(conn)
    ele_vol.append(np.full(len(conn), v))
    volume_node_ids[v] = set(int(n) for n in conn.ravel())
ele_tags = np.concatenate(ele_tags)
ele_conn = np.concatenate(ele_conn)
ele_vol = np.concatenate(ele_vol)
used_nodes = np.unique(ele_conn)
say(f"mesh: {len(used_nodes)} nodes, {len(ele_tags)} Tet4 elements (global size {GLOBAL_MESH_SIZE} m)")

base_ids = {int(t) for t in used_nodes if coord_by_tag[int(t)][2] <= BASE_TOL}
say(f"{len(base_ids)} base nodes at z <= {BASE_TOL} m")

ties, tie_counts = find_junction_ties(open_junctions, volume_node_ids, coord_by_tag,
                                      excluded_nodes=base_ids, max_tie_distance=MAX_TIE_DISTANCE)
say(f"{len(ties)} ties across {sum(1 for c in tie_counts.values() if c)} of "
    f"{len(open_junctions)} open junctions")

# --- 4. materials, one ASDConcrete3D per masonry element ---------------------
materials = materials_from_ifc(MATERIALS_IFC_PATH, material_groups)
weight = total_weight(material_groups, materials, G_ACCEL)
mat_summary = materials_summary(material_groups, materials)   # needs the OCC model, cleared below
say(f"self-weight {weight:,.1f} N")
t0 = time.perf_counter()
ele_volume = np.asarray(gmsh.model.mesh.getElementQualities(ele_tags.tolist(), "volume"))
side = (6.0 * math.sqrt(2.0) * ele_volume) ** (1.0 / 3.0)
say(f"element sizes read ({time.perf_counter() - t0:.1f} s): side length "
    f"{side.min():.3f}-{side.max():.3f} m, median {np.median(side):.3f} m")

mat_names = sorted(material_groups)
vol_to_name = {v: n for n, vs in material_groups.items() for v in vs}
ele_mat = np.array([vol_to_name[v] for v in ele_vol])


def si_params(m):
    """The same SI conversion and code-formula fallbacks as
    model_builder.Element.create_plastic_damage_elements."""
    fc_MPa, ft_MPa = m.compressive_strength, m.tensile_strength
    Gc_Nmm = float(m.compression_fracture_energy) if m.compression_fracture_energy else \
        15 + 0.43 * fc_MPa - 0.0036 * fc_MPa ** 2
    Gt_Nmm = float(m.tensile_fracture_energy) if m.tensile_fracture_energy else \
        0.025 * (fc_MPa / 10) ** 0.7
    E = float(m.young_modulus) * 1e6
    fc, ft = fc_MPa * 1e6, ft_MPa * 1e6
    f0 = float(m.compressive_elastic_behaviour) * 1e6 if m.compressive_elastic_behaviour else fc / 3
    return dict(E=E, nu=m.poisson_ratio, rho=m.density, fc=fc, ft=ft, f0=f0,
                Gc=Gc_Nmm * 1000, Gt=Gt_Nmm * 1000)


params = {n: si_params(materials[n]) for n in mat_names}
plastic = {n for n in mat_names if materials[n].material_model_type == "PlasticDamage"}
ELASTIC_TAG = {n: 9_000_000 + i for i, n in enumerate(mat_names) if n not in plastic}
say(f"plastic-damage materials: {sorted(plastic)}; elastic: {sorted(ELASTIC_TAG)}")


def fmt(vals):
    return " ".join(f"{v:.8g}" for v in vals)


t0 = time.perf_counter()
ele_line = {}
for tag, conn, name, lch in zip(ele_tags, ele_conn, ele_mat, side):
    p_ = params[name]
    bz = f"{p_['rho'] * G_BODY:.8g}"
    nodes = " ".join(str(int(n)) for n in conn)
    if name in plastic:
        Te, Ts, Td = ConstitutiveLaws.ExponentialSoftening_Tension.tension(p_["E"], p_["ft"], p_["Gt"], lch)
        Ce, Cs, Cd = ConstitutiveLaws.BezierCurve_Compression.compression(
            p_["E"], p_["f0"], p_["fc"], p_["Gc"], lch)
        mat = (f"nDMaterial ASDConcrete3D {int(tag)} {p_['E']:.8g} {p_['nu']:.6g} -rho {p_['rho']:.8g} "
               f"-Te {fmt(Te)} -Ts {fmt(Ts)} -Td {fmt(Td)} -Ce {fmt(Ce)} -Cs {fmt(Cs)} -Cd {fmt(Cd)} "
               f"-implex -autoRegularization {lch:.8g}\n")
        ele_line[int(tag)] = mat + f"element FourNodeTetrahedron {int(tag)} {nodes} {int(tag)} 0 0 {bz}\n"
    else:
        ele_line[int(tag)] = (f"element FourNodeTetrahedron {int(tag)} {nodes} "
                              f"{ELASTIC_TAG[name]} 0 0 {bz}\n")
say(f"material laws of {len(ele_line)} elements ({time.perf_counter() - t0:.1f} s)")

# --- 5. Rayleigh anchors: modes 1 and 10 of the unit (linear elastic) --------
F_ANCHOR = argval("--rayleigh-hz", None, lambda s: tuple(float(v) for v in s.split(",")))
freqs = []
if F_ANCHOR is None:
    import openseespy.opensees as ops
    t0 = time.perf_counter()
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 3)
    for t in used_nodes:
        ops.node(int(t), *[float(x) for x in coord_by_tag[int(t)]])
    for n in base_ids:
        ops.fix(n, 1, 1, 1)
    for m_, s_, _d in ties:
        ops.equalDOF(int(m_), int(s_), 1, 2, 3)
    for i, n in enumerate(mat_names):
        ops.nDMaterial("ElasticIsotropic", i + 1, params[n]["E"], params[n]["nu"], params[n]["rho"])
    mtag = {n: i + 1 for i, n in enumerate(mat_names)}
    for tag, conn, name in zip(ele_tags, ele_conn, ele_mat):
        ops.element("FourNodeTetrahedron", int(tag), *[int(n) for n in conn], mtag[name])
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    lam = ops.eigen(10)
    freqs = [math.sqrt(l) / (2 * math.pi) for l in lam]
    ops.wipe()
    F_ANCHOR = (freqs[0], freqs[9])
    say(f"eigen ({time.perf_counter() - t0:.1f} s): " + ", ".join(f"{f:.3f}" for f in freqs) + " Hz")
w1, w2 = 2 * math.pi * F_ANCHOR[0], 2 * math.pi * F_ANCHOR[1]
A0 = 2 * XI * w1 * w2 / (w1 + w2)
A1 = 2 * XI / (w1 + w2)
say(f"Rayleigh {XI * 100:.0f}% at {F_ANCHOR[0]:.4f} and {F_ANCHOR[1]:.4f} Hz: "
    f"alphaM {A0:.6g}, betaK {A1:.6g}")

# --- 6. ground motion window ---------------------------------------------------
vals = np.array([float(x) for line in open(RECORD) if line.strip() and not line.lstrip().startswith("#")
                 for x in line.split()])
i0, i1 = int(round(T_START / DT)), int(round(T_END / DT))
acc = vals[i0:i1].copy()
n_taper = min(max(1, int(round(TAPER / DT))), len(acc) // 2)
acc[:n_taper] *= 0.5 * (1 - np.cos(np.pi * np.arange(n_taper) / n_taper))
np.savetxt(os.path.join(MODEL_DIR, "accel_window.txt"), acc, fmt="%.8g")
N_STEPS = len(acc)
say(f"record window {T_START}-{T_END} s of the de-scaled record: {N_STEPS} steps of {DT:.6f} s, "
    f"peak {np.abs(acc).max():.3f} m/s^2, {TAPER} s taper")

# --- 7. Tcl: common part (every rank) -------------------------------------------
roof = [int(t) for t in sorted(used_nodes, key=lambda t: -coord_by_tag[int(t)][2])[:N_ROOF]]
base_sorted = sorted(base_ids)
with open(os.path.join(MODEL_DIR, "common.tcl"), "w") as fh:
    fh.write("# nodes, fixities, ties and elastic materials - defined by every rank\n")
    for t in used_nodes:
        x, y, z = coord_by_tag[int(t)]
        fh.write(f"node {int(t)} {x:.6f} {y:.6f} {z:.6f}\n")
    for n in base_sorted:
        fh.write(f"fix {n} 1 1 1\n")
    for n in mat_names:
        if n in ELASTIC_TAG:
            p_ = params[n]
            fh.write(f"nDMaterial ElasticIsotropic {ELASTIC_TAG[n]} {p_['E']:.8g} {p_['nu']:.6g} {p_['rho']:.8g}\n")
    if TIES == "equaldof":
        for m_, s_, _d in ties:
            fh.write(f"equalDOF {int(m_)} {int(s_)} 1 2 3\n")
    else:
        fh.write(f"uniaxialMaterial Elastic 8999999 {PENALTY_K:.6g}\n")
    fh.write(f"set ROOF_NODES {{{' '.join(map(str, roof))}}}\n")
    fh.write(f"set BASE_NODES {{{' '.join(map(str, base_sorted))}}}\n")

# --- 8. partitions: one file per rank for every process count -----------------
first_ele_of_node = {}
for tag, conn in zip(ele_tags, ele_conn):
    for n in conn:
        first_ele_of_node.setdefault(int(n), int(tag))
link_base = int(ele_tags.max()) + 1
partition_info = {}
for npart in NPARTS:
    part_of = {}
    if npart == 1:
        part_of = {int(t): 0 for t in ele_tags}
    else:
        t0 = time.perf_counter()
        # A fresh copy of the mesh for every partition: unpartition() crashes
        # gmsh 4.11 (segmentation fault, found in the smoke test), and the
        # .msh keeps the element tags.
        gmsh.clear()
        gmsh.open(os.path.join(MODEL_DIR, "mesh.msh"))
        gmsh.model.mesh.partition(npart)
        for d, ent in gmsh.model.getEntities(3):
            parts = gmsh.model.getPartitions(d, ent)
            if len(parts) != 1:
                continue
            _et, etg, _en = gmsh.model.mesh.getElements(d, ent)
            for block in etg:
                for t in block:
                    part_of[int(t)] = int(parts[0]) - 1
        missing = set(int(t) for t in ele_tags) - set(part_of)
        assert not missing, f"np={npart}: {len(missing)} elements without a partition"
        say(f"np={npart}: METIS partition ({time.perf_counter() - t0:.1f} s)")
    pdir = os.path.join(MODEL_DIR, f"np{npart}")
    os.makedirs(pdir, exist_ok=True)
    counts = [0] * npart
    files = [open(os.path.join(pdir, f"rank{r}.tcl"), "w") for r in range(npart)]
    for t in ele_tags:
        r = part_of[int(t)]
        files[r].write(ele_line[int(t)])
        counts[r] += 1
    if TIES == "penalty":
        for k, (m_, s_, _d) in enumerate(ties):
            r = part_of[first_ele_of_node[int(m_)]]
            files[r].write(f"element twoNodeLink {link_base + k} {int(m_)} {int(s_)} "
                           f"-mat 8999999 8999999 8999999 -dir 1 2 3\n")
    for f in files:
        f.close()
    # interface size: nodes used by elements of more than one part
    owners = {}
    for t, conn in zip(ele_tags, ele_conn):
        r = part_of[int(t)]
        for n in conn:
            owners.setdefault(int(n), set()).add(r)
    shared = sum(1 for s in owners.values() if len(s) > 1)
    partition_info[npart] = {"elements_per_rank": counts, "shared_nodes": shared,
                             "imbalance": max(counts) / (sum(counts) / npart)}
    say(f"np={npart}: elements per rank {counts}, {shared} nodes shared between ranks, "
        f"imbalance {partition_info[npart]['imbalance']:.3f}")

# --- 9. analysis script and drivers -------------------------------------------------
# equalDOF needs the Transformation handler (Plain ignores it); with no
# equalDOF in the model, Plain is used
HANDLER = "Transformation" if (TIES == "equaldof" and ties) else "Plain"
analysis = f"""# Unit 417 scalability benchmark - analysis, sourced by every driver.
# Set before sourcing: MODEL_DIR, NPART, SYSTEM (list), NUMBERER, OUT.
set pid [getPID]
set np [getNP]
if {{$np != $NPART}} {{ error "run with $NPART processes, not $np" }}
file mkdir $OUT
set T0 [clock milliseconds]
model basic -ndm 3 -ndf 3
source [file join $MODEL_DIR common.tcl]
source [file join $MODEL_DIR np$NPART rank$pid.tcl]
set T1 [clock milliseconds]

# gravity, the Chapter 8 static step
constraints {HANDLER}
numberer $NUMBERER
system {{*}}$SYSTEM
test EnergyIncr 1e-3 200 0
algorithm NewtonLineSearch
integrator LoadControl 0.1
analysis Static
set okG [analyze 10]
loadConst -time 0.0
set T2 [clock milliseconds]
if {{$okG != 0}} {{ error "gravity did not converge" }}

# transient
wipeAnalysis
rayleigh {A0:.10g} {A1:.10g} 0.0 0.0
timeSeries Path 1 -dt {DT:.10g} -filePath [file join $MODEL_DIR accel_window.txt]
pattern UniformExcitation 1 {EXC_DOF} -accel 1
if {{$pid == 0}} {{
    recorder Node -file [file join $OUT roof_disp.txt] -time -node {{*}}$ROOF_NODES -dof 1 2 3 disp
}}
recorder Node -file [file join $OUT base_reaction_r$pid.txt] -time -node {{*}}$BASE_NODES -dof 1 2 3 reaction
constraints {HANDLER}
numberer $NUMBERER
system {{*}}$SYSTEM
test EnergyIncr 1e-3 200 0
algorithm NewtonLineSearch
integrator TRBDF2
analysis Transient

set nSteps {N_STEPS}
set dt {DT:.10g}
set iters 0
set subdiv 0
set failed 0
set T3 [clock milliseconds]
for {{set i 1}} {{$i <= $nSteps}} {{incr i}} {{
    set ok [analyze 1 $dt]
    incr iters [testIter]
    if {{$ok != 0}} {{
        incr subdiv
        for {{set k 0}} {{$k < 10}} {{incr k}} {{
            set ok [analyze 1 [expr {{$dt / 10.0}}]]
            incr iters [testIter]
            if {{$ok != 0}} {{ break }}
        }}
        if {{$ok != 0}} {{
            incr failed
            if {{$failed >= 5}} {{ break }}
        }}
    }}
    if {{$pid == 0 && ($i % 25 == 0 || $i == $nSteps)}} {{
        set el [expr {{([clock milliseconds] - $T3) / 1000.0}}]
        puts "step $i/$nSteps t=[format %.3f [getTime]] s elapsed [format %.1f $el] s iterations $iters"
    }}
}}
set T4 [clock milliseconds]
remove recorders
if {{$pid == 0}} {{
    set fh [open [file join $OUT timing.txt] w]
    puts $fh "np $np"
    puts $fh "system $SYSTEM"
    puts $fh "numberer $NUMBERER"
    puts $fh "build_s [expr {{($T1 - $T0) / 1000.0}}]"
    puts $fh "gravity_s [expr {{($T2 - $T1) / 1000.0}}]"
    puts $fh "transient_s [expr {{($T4 - $T3) / 1000.0}}]"
    puts $fh "steps $nSteps"
    puts $fh "steps_done $i"
    puts $fh "iterations $iters"
    puts $fh "subdivided_steps $subdiv"
    puts $fh "failed_steps $failed"
    puts $fh "final_time [getTime]"
    close $fh
    puts "done: transient [expr {{($T4 - $T3) / 1000.0}}] s, $iters iterations, $failed failed steps"
}}
"""
with open(os.path.join(MODEL_DIR, "analysis.tcl"), "w") as fh:
    fh.write(analysis)

runs = [("np1_umfpack", 1, "UmfPack", "RCM")]
runs += [(f"np{n}_mumps", n, "Mumps", "ParallelRCM") for n in NPARTS]
for label, npart, system, numberer in runs:
    with open(os.path.join(OUT_DIR, f"run_{label}.tcl"), "w") as fh:
        fh.write(f"set MODEL_DIR {{{MODEL_DIR}}}\nset NPART {npart}\nset SYSTEM {{{system}}}\n"
                 f"set NUMBERER {numberer}\nset OUT {{{os.path.join(OUT_DIR, 'runs', label)}}}\n"
                 f"source [file join $MODEL_DIR analysis.tcl]\n")
with open(os.path.join(OUT_DIR, "runs.txt"), "w") as fh:
    for label, npart, _s, _n in runs:
        fh.write(f"{label} {npart}\n")

summary = {
    "run": "smoke" if SMOKE else "full",
    "unit": 417, "plan_box_xy": BOX, "eaves_line_xz": EAVES,
    "volumes": len(vol_tags), "total_volume_m3": total_volume, "volume_before_cut_m3": vol_before,
    "materials": mat_summary,
    "mesh_size_m": GLOBAL_MESH_SIZE, "nodes": int(len(used_nodes)), "elements": int(len(ele_tags)),
    "dofs_free": int(3 * (len(used_nodes) - len(base_ids))),
    "base_nodes": len(base_ids), "open_junctions": len(open_junctions), "ties": len(ties),
    "tie_model": TIES, "constraint_handler": HANDLER, "self_weight_N": weight,
    "eigen_frequencies_Hz": freqs, "rayleigh_anchor_Hz": list(F_ANCHOR),
    "rayleigh_alphaM": A0, "rayleigh_betaK": A1, "damping_ratio": XI,
    "record": os.path.basename(RECORD), "time_scale": TIME_SCALE,
    "window_s": [T_START, T_END], "taper_s": TAPER, "dt_s": DT, "steps": N_STEPS,
    "roof_nodes": roof, "partitions": partition_info,
    "integrator": "TRBDF2", "algorithm": "NewtonLineSearch", "test": "EnergyIncr 1e-3 200",
    "runs": [r[0] for r in runs], "build_time_s": time.perf_counter() - T_ALL,
}
with open(os.path.join(OUT_DIR, "build_summary.json"), "w") as fh:
    json.dump(summary, fh, indent=2)
say(f"wrote {OUT_DIR}/build_summary.json; runs: {', '.join(r[0] for r in runs)}")
gmsh.finalize()
