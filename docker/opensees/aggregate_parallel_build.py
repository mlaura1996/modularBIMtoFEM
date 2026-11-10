"""The Chapter 8 time-history of the whole Castelnuovo aggregate, written as
an OpenSeesMP model partitioned over N processes.

WHAT IT IS
----------
The same model as docker/opensees/timehistory_castelnuovo.py, built by the
same pipeline functions in the same order: the cleaned STEP geometry, the
Task A contact interfaces (node duplication + zeroLengthContactASDimplex),
the two-pass mesh refined around the open junctions, the equalDOF junction
ties, the base fixity, one regularised ASDConcrete3D per masonry element,
the four masonry types from the enriched IFC, Rayleigh 3 % at the Chapter 8
anchors, TRBDF2, NewtonLineSearch, EnergyIncr 1e-3 200 and the de-scaled
Montenegro 1979 record (Run 2.1 as delivered by the table, time x sqrt 2:
27.58 s in 3900 steps of 0.00707 s).

Only the execution changes. Instead of calling openseespy, every OpenSees
command the pipeline issues is captured and written as Tcl:

  * nodes, fixities, equalDOF ties and the elastic materials go to a
    common file every rank sources (the OpenSeesMP idiom of the unit 417
    benchmark: every rank defines every node);
  * each tetrahedron and its own ASDConcrete3D go to the file of the rank
    that owns the element, from a METIS partition of the mesh;
  * each contact element goes to the rank that owns a tetrahedron using
    its original node.

Capturing the calls, rather than re-implementing the model, is the point:
the parallel model cannot drift from the Chapter 8 one, because it is the
same code producing it.

THE TIES IN PARALLEL
--------------------
equalDOF is defined on every rank, with the Transformation handler, so the
constrained DOFs are eliminated identically in every subdomain. The smoke
test compares 1, 2 and 4 processes on a model that has ties and contact
elements; run it before the full model. --ties penalty replaces each tie
with a stiff twoNodeLink owned by one rank, the fallback if the
transformation across subdomains turns out not to hold.

OUTPUT
------
<out>/model/common.tcl, analysis.tcl, accel.txt, mesh.msh
<out>/model/np<N>/rank<r>.tcl, rank<r>_lists.tcl
<out>/run_np<N>.tcl                 one driver per process count
<out>/build_summary.json            everything the merge step needs
<out>/interface_node_pairs.txt, sampled_elements.txt, mesh.msh
                                    as in the Chapter 8 run directory

The run writes per-rank recorders to <out>/runs/np<N>/;
aggregate_parallel_merge.py turns them into the files of a Chapter 8 run
directory, so scripts/postprocess_timehistory.py and the rendering scripts
read them unchanged.

    # wiring check: coarse mesh, 30 steps, 1, 2 and 4 processes - minutes
    python docker/opensees/aggregate_parallel_build.py --smoke --nparts 1,2,4 \
        --out-dir output/castelnuovo/aggregate_parallel_smoke

    # the Chapter 8 model on 8 processes
    python docker/opensees/aggregate_parallel_build.py --nparts 8 \
        --out-dir /app_output/aggregate_parallel

docker/opensees/run_aggregate_parallel.sh runs the build, the analysis, the
merge and the post-processing in sequence.
"""
import json
import math
import os
import subprocess
import sys
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/app")
sys.path.insert(0, REPO)


def argval(flag, default=None, cast=str):
    if flag in sys.argv:
        return cast(sys.argv[sys.argv.index(flag) + 1])
    return default


# --- partition worker: run in a separate process, because gmsh 4.11 crashes
# on unpartition() and the main process still needs its own model ---------
if "--partition-worker" in sys.argv:
    import gmsh
    msh, npart, dest = sys.argv[sys.argv.index("--partition-worker") + 1:][:3]
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.open(msh)
    gmsh.model.mesh.partition(int(npart))
    with open(dest, "w") as fh:
        for d, ent in gmsh.model.getEntities(3):
            parts = gmsh.model.getPartitions(d, ent)
            if len(parts) != 1:
                continue
            _et, etg, _en = gmsh.model.mesh.getElements(d, ent)
            for block in etg:
                for t in block:
                    fh.write(f"{int(t)} {int(parts[0]) - 1}\n")
    gmsh.finalize()
    sys.exit(0)

import numpy as np

SMOKE = "--smoke" in sys.argv
OUT_DIR = os.path.abspath(argval("--out-dir", "output/castelnuovo/aggregate_parallel"
                                 + ("_smoke" if SMOKE else "")))
MODEL_DIR = os.path.join(OUT_DIR, "model")
NPARTS = [int(v) for v in argval("--nparts", "1,2,4" if SMOKE else "8").split(",")]
TIES = argval("--ties", "equaldof")
assert TIES in ("equaldof", "penalty"), "--ties is equaldof or penalty"
PENALTY_K = 1.0e12

# --- the Chapter 8 settings (timehistory_castelnuovo.py, de-scaled run) ----
STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
VOLUME_MATERIALS_PATH = "resources/survey_data/castelnuovo/volume_materials.json"
MATERIALS_IFC_PATH = "output/castelnuovo/castelnuovo_case.ifc"
RECORD = argval("--record", "resources/records/castelnuovo/montenegro1979_run21_long.txt")
TIME_SCALE = math.sqrt(2.0) if argval("--time-scale", "sqrt2").lower() == "sqrt2" \
    else float(argval("--time-scale"))
DT = 0.005 * TIME_SCALE
DURATION = argval("--duration", 30 * DT if SMOKE else 19.5 * TIME_SCALE, float)
EXC_DOF = argval("--dof", 1, int)
# only for wiring checks: start the record this many seconds (de-scaled time)
# in, so a few steps already shake the model; the Chapter 8 run starts at 0
RECORD_START = argval("--record-start", 0.0, float)
GLOBAL_MESH_SIZE = 0.6 if SMOKE else argval("--mesh-size", 0.3, float)
JUNCTION_MESH_SIZE = 0.6 if SMOKE else 0.10
JUNCTION_REFINE_RADIUS = 0.4
MAX_JUNCTION_GAP = 0.05
MAX_TIE_DISTANCE = 0.10
BASE_TOL = 0.05
KN_NOMINAL = 69000.0 * 1e9
KT_NOMINAL = 0.001 * 1e9
MU_FRICTION = 0.6
# the anchors of the de-scaled Chapter 8 run (modes 1 and 10 of the tied
# model with the four masonry types)
F1_HZ, F2_HZ = argval("--rayleigh-hz", (6.2875, 11.3738),
                      lambda s: tuple(float(v) for v in s.split(",")))
XI = 0.03
SOLID_SAMPLE = 1 if SMOKE else argval("--solid-sample", 1, int)
FIELDS_EVERY = argval("--fields-every", 1, int)
G_ACCEL = 9.81

os.makedirs(MODEL_DIR, exist_ok=True)
LOG = open(os.path.join(OUT_DIR, "build.log"), "w", buffering=1)


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")


def num(v):
    return f"{float(v):.10g}"


# --- the capture backend ---------------------------------------------------
class TclCapture:
    """Stands in for openseespy.opensees while the pipeline builds the model.

    Phase 1 (before the partition is known) keeps nodes, fixities, ties and
    materials in memory; elements are written straight to the rank files of
    every requested partition once start_elements() has opened them, each
    plastic element preceded by its own material, so the 286k ASDConcrete3D
    definitions are never all held at once.
    """

    def __init__(self):
        self.nodes = {}
        self.fixes = []
        self.ties = []
        self.common_materials = []
        self.pending_materials = {}
        self.ele_tags = []
        self.solid_tags = []
        self.contact_tags = []
        self.links = []
        self.part_of = None          # {npart: {element tag: rank}}
        self.files = None            # {npart: [file per rank]}
        self.node_rank = None        # {npart: {node: rank of first element}}
        self.rank_eles = None        # {npart: [[element tags] per rank]}
        self.other = []

    # node, fixity and constraint commands
    def node(self, tag, *coords):
        self.nodes[int(tag)] = tuple(float(c) for c in coords)

    def fix(self, tag, *dofs):
        self.fixes.append((int(tag),) + tuple(int(d) for d in dofs))

    def equalDOF(self, m, s, *dofs):
        self.ties.append((int(m), int(s)) + tuple(int(d) for d in dofs))

    def getNodeTags(self):
        return list(self.nodes)

    def getEleTags(self):
        return self.ele_tags

    def getNP(self):
        return 1

    def getPID(self):
        return 0

    def model(self, *args):
        pass

    def wipe(self, *args):
        pass

    # materials and elements
    def nDMaterial(self, mtype, tag, *args):
        line = f"nDMaterial {mtype} {int(tag)} " + " ".join(
            a if isinstance(a, str) else num(a) for a in args) + "\n"
        if mtype == "ASDConcrete3D":
            self.pending_materials[int(tag)] = line
        else:
            self.common_materials.append(line)

    def start_elements(self, part_of, out_dir):
        self.part_of = part_of
        self.files, self.node_rank, self.rank_eles = {}, {}, {}
        for npart in part_of:
            pdir = os.path.join(out_dir, f"np{npart}")
            os.makedirs(pdir, exist_ok=True)
            self.files[npart] = [open(os.path.join(pdir, f"rank{r}.tcl"), "w")
                                 for r in range(npart)]
            self.node_rank[npart] = {}
            self.rank_eles[npart] = [[] for _ in range(npart)]

    def element(self, etype, tag, *args):
        tag = int(tag)
        if self.files is None:
            raise RuntimeError("element() before start_elements()")
        self.ele_tags.append(tag)
        if etype == "FourNodeTetrahedron":
            nodes = [int(n) for n in args[:4]]
            mat = int(args[4])
            mat_line = self.pending_materials.pop(mat, "")
            line = (f"element FourNodeTetrahedron {tag} {' '.join(map(str, nodes))} {mat} "
                    + " ".join(num(a) for a in args[5:]) + "\n")
            self.solid_tags.append(tag)
            for npart, files in self.files.items():
                r = self.part_of[npart][tag]
                files[r].write(mat_line + line)
                self.rank_eles[npart][r].append(tag)
                nr = self.node_rank[npart]
                for n in nodes:
                    nr.setdefault(n, r)
        elif etype == "zeroLengthContactASDimplex":
            line = f"element {etype} {tag} " + " ".join(
                a if isinstance(a, str) else (str(int(a)) if isinstance(a, (int, np.integer)) else num(a))
                for a in args) + "\n"
            self.contact_tags.append(tag)
            for npart, files in self.files.items():
                r = self.node_rank[npart][int(args[0])]
                files[r].write(line)
                self.rank_eles[npart][r].append(tag)
        else:
            raise RuntimeError(f"element type {etype} is not handled by the capture")

    def write_links(self, link_base):
        """--ties penalty: one stiff twoNodeLink per tie, owned by one rank."""
        for k, (m, s, *_d) in enumerate(self.ties):
            tag = link_base + k
            self.links.append(tag)
            for npart, files in self.files.items():
                r = self.node_rank[npart].get(m, self.node_rank[npart].get(s, 0))
                files[r].write(f"element twoNodeLink {tag} {m} {s} -mat 8999999 8999999 8999999 "
                               f"-dir 1 2 3\n")

    def close(self):
        for files in self.files.values():
            for f in files:
                f.close()
        assert not self.pending_materials, f"{len(self.pending_materials)} materials without an element"


CAP = TclCapture()
_fake = types.ModuleType("openseespy.opensees")
_names = ["node", "fix", "equalDOF", "getNodeTags", "getEleTags", "getNP", "getPID",
          "model", "wipe", "nDMaterial", "element"]
for _n in _names:
    setattr(_fake, _n, getattr(CAP, _n))
_fake.__all__ = _names


def _unexpected(name):
    def call(*args, **kw):
        raise RuntimeError(f"the pipeline called ops.{name}, which the Tcl capture does not handle")
    return call


_fake.__getattr__ = _unexpected
_pkg = types.ModuleType("openseespy")
_pkg.__path__ = []
_pkg.opensees = _fake
sys.modules["openseespy"] = _pkg
sys.modules["openseespy.opensees"] = _fake

import gmsh  # noqa: E402

from external.gmsh2opensees.g2o_nodes_functions import get_all_nodes, add_nodes_to_ops  # noqa: E402
from core.opensees_generation.model_builder import ModelBuilder, Element  # noqa: E402
from core.opensees_generation.junction_ties import find_junction_ties, apply_ties  # noqa: E402
from core.opensees_generation.element_sampling import select_recorded_elements  # noqa: E402
from core.mesh_generation.geometry_healing import find_open_junctions  # noqa: E402
from core.opensees_generation.volume_materials import (  # noqa: E402
    load as load_volume_materials, add_physical_groups, materials_from_ifc, total_weight,
    summary as materials_summary)
from core.mesh_generation.wall_interfaces import (  # noqa: E402
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)

T_ALL = time.perf_counter()
say(f"{'SMOKE' if SMOKE else 'FULL'} build -> {OUT_DIR}, partitions {NPARTS}, ties {TIES}")

# --- ground motion (read_record of timehistory_castelnuovo.py, plain file) --
lines = open(RECORD).readlines()
accel = np.array([float(x) for line in lines if line.strip() and not line.lstrip().startswith("#")
                  for x in line.split()])
record_dt_own = 0.005
for line in lines:
    words = line.lstrip("#").replace("=", " ").split()
    if line.lstrip().startswith("#") and len(words) >= 2 and words[0].lower() == "dt":
        record_dt_own = float(words[1])
        break
record_dt = record_dt_own * TIME_SCALE
if RECORD_START > 0:
    accel = accel[int(round(RECORD_START / record_dt)):]
N_STEPS = int(round(DURATION / DT))
with open(os.path.join(MODEL_DIR, "accel.txt"), "w") as fh:
    fh.write("\n".join(repr(float(a)) for a in accel) + "\n")
say(f"record {os.path.basename(RECORD)}: {len(accel)} points, dt {record_dt:.6f} s, "
    f"peak {np.abs(accel).max():.3f} m/s^2; {N_STEPS} steps of {DT:.6f} s ({DURATION:.2f} s)")

# --- 1. geometry and interfaces (sections 1-2 of the Chapter 8 script) -------
t0 = time.perf_counter()
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("castelnuovo_timehistory")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
vol_tags = [t for _d, t in gmsh.model.getEntities(3)]
total_volume = sum(gmsh.model.occ.getMass(3, t) for t in vol_tags)
say(f"{len(vol_tags)} volumes, {total_volume:.2f} m^3 ({time.perf_counter() - t0:.1f} s)")
material_groups = add_physical_groups(load_volume_materials(VOLUME_MATERIALS_PATH), vol_tags)

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)
touching = {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"])) for c in candidates}
selected = InterfaceSelection.load_selected(SELECTION_PATH, candidates)
NodeSplitter.assign_split_side(selected)
ContactInterfaceGenerator.tag_physical_groups(selected)
say(f"{len(candidates)} touching surface pairs, {len(selected)} contact interfaces selected")

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
        bbox[v] = gmsh.model.occ.getBoundingBox(3, v)
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
if not SMOKE:
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
    say(f"mesh pass 2, refined around {len(junction_faces)} facing surfaces: "
        f"{len(open_junctions)} open junctions ({time.perf_counter() - t0:.1f} s)")
gmsh.option.setNumber("Mesh.SaveAll", 1)
MSH = os.path.join(MODEL_DIR, "mesh.msh")
gmsh.write(MSH)
n_mesh_elements = 0
for v in vol_tags:
    _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
    if len(etg):
        n_mesh_elements += len(etg[0])
say(f"mesh: {len(gmsh.model.mesh.getNodes()[0])} nodes, {n_mesh_elements} elements "
    f"(global size {GLOBAL_MESH_SIZE} m)")

# --- 2. METIS partitions of the mesh, in separate processes -------------------
part_of = {}
for npart in NPARTS:
    t0 = time.perf_counter()
    if npart == 1:
        part_of[1] = None
        continue
    dest = os.path.join(MODEL_DIR, f"partition_np{npart}.txt")
    subprocess.run([sys.executable, os.path.abspath(__file__), "--partition-worker", MSH,
                    str(npart), dest], check=True)
    part_of[npart] = {int(a): int(b) for a, b in (line.split() for line in open(dest))}
    say(f"np={npart}: METIS partition ({time.perf_counter() - t0:.1f} s)")


class AllZero(dict):
    def __missing__(self, key):
        return 0


part_of = {n: (p if p is not None else AllZero()) for n, p in part_of.items()}

# --- 3. the model, through the pipeline (sections 3-6 of the Chapter 8 script)
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()
node_tags_all, node_coords_all = get_all_nodes(gmsh.model)
add_nodes_to_ops(node_tags_all, gmsh.model)
n_nodes = len(node_tags_all)
coord_by_tag = {int(t): c for t, c in zip(node_tags_all, node_coords_all)}
node_z = {int(t): float(c[2]) for t, c in zip(node_tags_all, node_coords_all)}
say(f"{n_nodes} nodes")

substitution = NodeSplitter.create_duplicate_nodes(gmsh.model, selected)
duplicated_originals = {orig for m in substitution.values() for orig in m}
say(f"{len(duplicated_originals)} interface nodes duplicated across {len(substitution)} split volume(s)")


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
ground_volumes = InterfaceDetection.find_ground_bearing_volumes(candidates, volume_z_ranges)
base_ids = set()
for vol in ground_volumes:
    zmin = volume_z_ranges[vol][0]
    for n in volume_node_ids[vol]:
        if node_z[n] <= zmin + BASE_TOL:
            base_ids.add(element_node(vol, n))
base_arr = np.asarray(sorted(base_ids), dtype=np.int64)
for n in base_arr:
    CAP.fix(int(n), 1, 1, 1)
n_base_dups = int(sum(1 for n in base_arr if n >= NodeSplitter.TAG_OFFSET))
say(f"{len(base_arr)} base nodes fixed ({n_base_dups} interface duplicates)")

ties, tie_counts, tie_vols = find_junction_ties(
    open_junctions, volume_node_ids, coord_by_tag, excluded_nodes=base_ids,
    max_tie_distance=MAX_TIE_DISTANCE, node_substitution=substitution, return_volumes=True)
retargeted = [(m, s) for (m, s, _d) in ties
              if m >= NodeSplitter.TAG_OFFSET or s >= NodeSplitter.TAG_OFFSET]
elem_nodes = {v: {element_node(v, n) for n in ns} for v, ns in volume_node_ids.items()}
dangling = [(m, s, va, vb) for (m, s, _d), (va, vb) in zip(ties, tie_vols)
            if m not in elem_nodes.get(va, ()) or s not in elem_nodes.get(vb, ())]
if dangling:
    say(f"ABORT: {len(dangling)} tie(s) reference a node their own volume's elements do not use")
    sys.exit(2)
n_applied = apply_ties(ties, CAP)
say(f"{n_applied} ties across {sum(1 for c in tie_counts.values() if c)} of "
    f"{len(open_junctions)} junctions ({len(retargeted)} on interface duplicates); "
    f"invariant check passed")

CAP.start_elements(part_of, MODEL_DIR)
t0 = time.perf_counter()
materials = materials_from_ifc(MATERIALS_IFC_PATH, material_groups)
say("elements and their ASDConcrete3D materials (the slow part)...")
element_tags = Element.add_elements_to_opensees(gmsh.model, materials, node_substitution=substitution)
say(f"{len(element_tags)} solid elements written ({time.perf_counter() - t0:.1f} s)")
contact = ContactInterfaceGenerator.generate(
    selected, Kn_nominal=KN_NOMINAL, Kt_nominal=KT_NOMINAL, mu=MU_FRICTION)
contact_eles = [int(e) for c in contact for e in c["elements"]]
say(f"{len(contact_eles)} zeroLengthContactASDimplex elements on {len(contact)} interfaces")
if TIES == "penalty":
    CAP.write_links(max(CAP.ele_tags) + 1)
CAP.close()
weight = total_weight(material_groups, materials, G_ACCEL)
say(f"self-weight {weight:,.1f} N")

# --- 4. recorded quantities, as in the Chapter 8 run ----------------------------
top_nodes = [int(n) for n in sorted(node_z, key=lambda n: -node_z[n])[:20]]
if_pairs = [(o, d) for c in selected for o, d in c["node_map"].items()]
if_nodes = sorted({int(n) for pair in if_pairs for n in pair})
with open(os.path.join(OUT_DIR, "interface_node_pairs.txt"), "w") as fh:
    fh.write("# original_node,duplicate_node,interface_key\n")
    for c in selected:
        k = InterfaceSelection.key_for(c)
        for o, d in c["node_map"].items():
            fh.write(f"{o},{d},{k}\n")
sampled, interesting_vols, focus_eles = select_recorded_elements(
    element_tags, selected, open_junctions, SOLID_SAMPLE)
with open(os.path.join(OUT_DIR, "sampled_elements.txt"), "w") as fh:
    fh.write("# element_index,element_tag - element_index is the column "
             "position in solid_strain.txt / solid_stress.txt / solid_*.txt\n")
    for i, tag in enumerate(sampled):
        fh.write(f"{i},{tag}\n")
say(f"{len(sampled)} of {len(element_tags)} solid elements recorded")
gmsh.write(os.path.join(OUT_DIR, "mesh.msh"))
mat_summary = materials_summary(material_groups, materials)

# --- 5. Tcl: common part and per-rank lists ----------------------------------------
with open(os.path.join(MODEL_DIR, "common.tcl"), "w") as fh:
    fh.write("# nodes, fixities, ties and elastic materials - defined by every rank\n")
    for t, c in CAP.nodes.items():
        fh.write(f"node {t} {' '.join(repr(v) for v in c)}\n")
    for f in CAP.fixes:
        fh.write("fix " + " ".join(map(str, f)) + "\n")
    fh.writelines(CAP.common_materials)
    if TIES == "equaldof":
        for t in CAP.ties:
            fh.write("equalDOF " + " ".join(map(str, t)) + "\n")
    else:
        fh.write(f"uniaxialMaterial Elastic 8999999 {PENALTY_K:.6g}\n")
    fh.write(f"set ROOF_NODES {{{' '.join(map(str, top_nodes))}}}\n")
    fh.write(f"set BASE_NODES {{{' '.join(map(str, base_arr.tolist()))}}}\n")
    fh.write(f"set IF_NODES {{{' '.join(map(str, if_nodes))}}}\n")

sampled_set = set(int(t) for t in sampled)
contact_set = set(contact_eles)
partition_info = {}
for npart in NPARTS:
    pdir = os.path.join(MODEL_DIR, f"np{npart}")
    counts = []
    for r in range(npart):
        mine = CAP.rank_eles[npart][r]
        mine_set = set(mine)
        rs = sorted(t for t in mine if t in sampled_set)
        rc = [t for t in contact_eles if t in mine_set]
        counts.append(sum(1 for t in mine if t not in contact_set))
        with open(os.path.join(pdir, f"rank{r}_lists.tcl"), "w") as fh:
            fh.write(f"set RANK_SAMPLED {{{' '.join(map(str, rs))}}}\n")
            fh.write(f"set RANK_CONTACT {{{' '.join(map(str, rc))}}}\n")
    partition_info[npart] = {"solid_elements_per_rank": counts,
                             "imbalance": max(counts) / (sum(counts) / npart)}
    say(f"np={npart}: solid elements per rank {counts}, imbalance "
        f"{partition_info[npart]['imbalance']:.3f}")

w1, w2 = 2 * math.pi * F1_HZ, 2 * math.pi * F2_HZ
A0 = 2 * XI * w1 * w2 / (w1 + w2)
A1 = 2 * XI / (w1 + w2)
HANDLER = "Transformation" if (TIES == "equaldof" and CAP.ties) else "Plain"

analysis = f"""# Castelnuovo aggregate, Chapter 8 time-history on OpenSeesMP. Sourced by
# every driver; set before sourcing: MODEL_DIR, NPART, OUT, SYSTEM, NUMBERER.
set pid [getPID]
set np [getNP]
if {{$np != $NPART}} {{ error "run with $NPART processes, not $np" }}
file mkdir $OUT
set T0 [clock milliseconds]
model basic -ndm 3 -ndf 3
source [file join $MODEL_DIR common.tcl]
source [file join $MODEL_DIR np$NPART rank$pid.tcl]
source [file join $MODEL_DIR np$NPART rank${{pid}}_lists.tcl]
set T1 [clock milliseconds]
if {{$pid == 0}} {{ puts "model built in [expr {{($T1 - $T0) / 1000.0}}] s" }}

# static gravity, nonlinear and stepped (Chapter 8 section 7)
constraints {HANDLER}
numberer $NUMBERER
system {{*}}$SYSTEM
test EnergyIncr 1e-3 200 0
algorithm NewtonLineSearch
integrator LoadControl {1.0 / (2 if SMOKE else 10):.10g}
analysis Static
set okG [analyze {2 if SMOKE else 10}]
if {{$okG != 0}} {{ error "gravity did not converge" }}
reactions
set rz 0.0
foreach n $BASE_NODES {{ set rz [expr {{$rz + [nodeReaction $n 3]}}] }}
set fh [open [file join $OUT gravity_reaction_r$pid.txt] w]
puts $fh $rz
close $fh
loadConst -time 0.0
set T2 [clock milliseconds]
if {{$pid == 0}} {{ puts "gravity converged in [expr {{($T2 - $T1) / 1000.0}}] s" }}

# transient (Chapter 8 section 8)
wipeAnalysis
rayleigh {A0:.12g} {A1:.12g} 0.0 0.0
timeSeries Path 1 -dt {record_dt:.12g} -filePath [file join $MODEL_DIR accel.txt]
pattern UniformExcitation 1 {EXC_DOF} -accel 1

# recorders: node quantities on rank 0 (every rank holds every node and the
# global solution), reactions and element quantities on every rank for its
# own elements, merged afterwards by aggregate_parallel_merge.py
if {{$pid == 0}} {{
    recorder Node -file [file join $OUT roof_disp.txt] -time -node {{*}}$ROOF_NODES -dof 1 2 3 disp
    recorder Node -file [file join $OUT roof_accel.txt] -time -node {{*}}$ROOF_NODES -dof 1 2 3 accel
    if {{[llength $IF_NODES]}} {{
        recorder Node -file [file join $OUT interface_disp.txt] -time -node {{*}}$IF_NODES -dof 1 2 3 disp
    }}
}}
recorder Node -file [file join $OUT base_reaction_r$pid.txt] -time -node {{*}}$BASE_NODES -dof 1 2 3 reaction
if {{[llength $RANK_CONTACT]}} {{
    recorder Element -file [file join $OUT contact_force_r$pid.txt] -time -ele {{*}}$RANK_CONTACT force
}}
if {{[llength $RANK_SAMPLED]}} {{
    set dTrec [expr {{{FIELDS_EVERY} * {DT:.12g} - 1e-9}}]
    if {{{FIELDS_EVERY} > 1}} {{
        recorder Element -file [file join $OUT solid_strain_r$pid.txt] -time -dT $dTrec -ele {{*}}$RANK_SAMPLED material 1 strain
    }} else {{
        recorder Element -file [file join $OUT solid_strain_r$pid.txt] -time -ele {{*}}$RANK_SAMPLED material 1 strain
    }}
}}

constraints {HANDLER}
numberer $NUMBERER
system {{*}}$SYSTEM
test EnergyIncr 1e-3 200 0
algorithm NewtonLineSearch
integrator TRBDF2
analysis Transient

set nSteps {N_STEPS}
set dt {DT:.12g}
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
            if {{$pid == 0}} {{ puts "step $i failed at dt and dt/10 (failure $failed)" }}
            if {{$failed >= 5}} {{
                if {{$pid == 0}} {{ puts "ABORT: 5 steps failed even subdivided" }}
                break
            }}
        }} elseif {{$pid == 0}} {{ puts "step $i needed subdivision into 10" }}
    }}
    if {{$pid == 0 && ($i % {5 if SMOKE else 50} == 0 || $i == $nSteps)}} {{
        set el [expr {{([clock milliseconds] - $T3) / 1000.0}}]
        set eta [expr {{$el / $i * ($nSteps - $i) / 3600.0}}]
        puts "step $i/$nSteps t=[format %.3f [getTime]] s elapsed [format %.2f [expr {{$el / 3600.0}}]] h ETA [format %.2f $eta] h iterations $iters"
    }}
}}
set T4 [clock milliseconds]
remove recorders
# damage never heals: its value at the end is its peak (the Chapter 8
# post-processing reads only the last row of the damage recorder)
set fh [open [file join $OUT damage_final_r$pid.txt] w]
foreach e $RANK_SAMPLED {{ puts $fh "$e [eleResponse $e material 1 damage]" }}
close $fh
if {{$pid == 0}} {{
    set fh [open [file join $OUT timing.txt] w]
    puts $fh "np $np"
    puts $fh "system $SYSTEM"
    puts $fh "build_s [expr {{($T1 - $T0) / 1000.0}}]"
    puts $fh "gravity_s [expr {{($T2 - $T1) / 1000.0}}]"
    puts $fh "transient_s [expr {{($T4 - $T3) / 1000.0}}]"
    puts $fh "steps $nSteps"
    puts $fh "steps_done [expr {{min($i, $nSteps)}}]"
    puts $fh "iterations $iters"
    puts $fh "subdivided_steps $subdiv"
    puts $fh "failed_steps $failed"
    puts $fh "final_time [getTime]"
    close $fh
    puts "done: transient [expr {{($T4 - $T3) / 3600000.0}}] h, $iters iterations, $subdiv subdivided, $failed failed steps"
}}
"""
with open(os.path.join(MODEL_DIR, "analysis.tcl"), "w") as fh:
    fh.write(analysis)

for npart in NPARTS:
    system = "Mumps" if npart > 1 or "--mumps-np1" in sys.argv else "UmfPack"
    numberer = "ParallelRCM" if npart > 1 else "RCM"
    with open(os.path.join(OUT_DIR, f"run_np{npart}.tcl"), "w") as fh:
        fh.write(f"set MODEL_DIR {{{MODEL_DIR}}}\nset NPART {npart}\n"
                 f"set OUT {{{os.path.join(OUT_DIR, 'runs', f'np{npart}')}}}\n"
                 f"set SYSTEM {{{system}}}\nset NUMBERER {numberer}\n"
                 f"source [file join $MODEL_DIR analysis.tcl]\n")

summary = {
    "run": "smoke" if SMOKE else "full",
    "record": os.path.basename(RECORD), "record_scale_to_m_s2": 1.0,
    "record_time_scale": TIME_SCALE, "record_dt_s": record_dt, "record_start_s": RECORD_START,
    "duration_s": DURATION, "dt_s": DT, "steps_requested": N_STEPS,
    "mesh_nodes": n_nodes, "mesh_elements": len(element_tags),
    "global_mesh_size_m": GLOBAL_MESH_SIZE, "solid_sample_stride": SOLID_SAMPLE,
    "total_volume_m3": total_volume, "materials": mat_summary,
    "material_model": "ASDConcrete3D (implex, autoRegularization)",
    "equaldof_constraints": n_applied, "tie_model": TIES, "constraint_handler": HANDLER,
    "ties_on_interface_duplicates": len(retargeted),
    "base_nodes_on_interface_duplicates": n_base_dups,
    "open_junctions": len(open_junctions), "contact_elements": len(contact_eles),
    "contact_interfaces": len(contact), "interface_nodes_duplicated": len(duplicated_originals),
    "Kn_nominal_N_m3": KN_NOMINAL, "Kt_nominal_N_m3": KT_NOMINAL, "friction": MU_FRICTION,
    "damping_ratio": XI, "rayleigh_anchor_Hz": [F1_HZ, F2_HZ],
    "rayleigh_alphaM": A0, "rayleigh_betaK": A1,
    "base_nodes_fixed": len(base_arr), "self_weight_N": weight,
    "excitation_dof": EXC_DOF, "integrator": "TRBDF2", "algorithm": "NewtonLineSearch",
    "convergence_test": "EnergyIncr 1e-3, 200 iterations",
    "solid_elements_recorded": len(sampled), "fields_every_steps": FIELDS_EVERY,
    "sampled_elements": [int(t) for t in sampled], "contact_element_order": contact_eles,
    "plastic_materials": sorted(n for n, m in materials.items()
                                if m.material_model_type == "PlasticDamage"),
    "partitions": partition_info, "build_time_s": time.perf_counter() - T_ALL,
}
with open(os.path.join(OUT_DIR, "build_summary.json"), "w") as fh:
    json.dump(summary, fh)
say(f"wrote {OUT_DIR}/build_summary.json; drivers: "
    + ", ".join(f"run_np{n}.tcl" for n in NPARTS))
gmsh.finalize()
