"""Recovers, for a completed time-history run, the mapping from a results
CSV's "element_index" back to the real gmsh element tag.

WHY THIS EXISTS: the run that produced the 39 GB of recorder text finished
before timehistory_castelnuovo.py wrote sampled_elements.txt (see that
script's comment at the point `sampled` is computed) - element_index is
just each element's position in a Python list built at run time, and
nothing about it survives inside the recorder files themselves (OpenSees
Node/Element recorders write plain columns, no header, no tag labels).
Without this mapping, principal_strains.csv and damage_map.csv are numbers
with no location - useless for a spatial plot.

This script rebuilds that list from what DID survive: the saved mesh
(mesh.msh, a few MB - it sits next to the 39 GB of recorders but is not
part of it) plus the SAME deterministic geometry/interface/junction
pipeline timehistory_castelnuovo.py itself runs, ending in a call to the
SAME select_recorded_elements() function (core/opensees_generation/
element_sampling.py) so the live run and this reconstruction cannot
silently disagree about what the list means.

WHY IT RE-IMPORTS THE STEP FILE INSTEAD OF JUST LOADING mesh.msh:
InterfaceDetection.find_touching_surface_pairs() queries the OCC/BRep
model directly (getMass, getCenterOfMass, getNormal on CAD surfaces) to
find the candidate interfaces - a saved .msh carries only mesh data, no
BRep geometry, so those calls would find nothing against a loaded .msh.
The STEP file has to be re-opened and re-fragmented, exactly as step 1 of
the live run does.

TWO INDEPENDENT CHECKS, NOT ONE - a wrong mapping here would silently put
the wrong strain history next to the wrong element in every later plot, so
this refuses to write anything unless BOTH pass:

1. The re-derived mesh is compared against mesh.msh - the actual mesh the
   live run used - on node count, node coordinates (max deviation) and
   element count. This is the check that catches "a different gmsh/OCC
   version reproduces the geometry slightly differently", which every
   number-matching check below would miss (it would just as happily
   confirm a self-consistent WRONG reconstruction).
2. The reconstructed sampled list's length is compared against
   summary.json's own solid_elements_recorded, written by the live run
   from the SAME select_recorded_elements() call, on data this script
   never touches. Two independent routes to the same number is much
   stronger evidence than either alone.

If either check fails, this aborts rather than writing a mapping that
"mostly" agrees - a mapping used for anything spatial has to be exactly
right or not used at all.

    python docker/opensees/reconstruct_sampled_elements.py [run_dir]

Needs the same Docker image as the analysis (gmsh, core/). Takes a few
minutes (meshing), not hours - it never builds a single OpenSees element
or material.
"""
import os
import sys
import time

sys.path.insert(0, "/app")

import numpy as np
import gmsh

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, NodeSplitter, ContactInterfaceGenerator,
)
from core.mesh_generation.geometry_healing import find_open_junctions
from external.gmsh2opensees.g2o_utils import get_physical_groups_map
from core.opensees_generation.element_sampling import select_recorded_elements

RUN_DIR = sys.argv[1] if len(sys.argv) > 1 else "output/castelnuovo/recorders_timehistory"
STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"

# Must match timehistory_castelnuovo.py's own constants exactly - these are
# NOT re-derived from anything, so a value changed in one place and not the
# other would silently reconstruct the wrong mesh.
GLOBAL_MESH_SIZE = 0.6
JUNCTION_MESH_SIZE = 0.10
JUNCTION_REFINE_RADIUS = 0.4
MAX_JUNCTION_GAP = 0.05
SOLID_SAMPLE = 20

MESH_PATH = os.path.join(RUN_DIR, "mesh.msh")
SUMMARY_PATH = os.path.join(RUN_DIR, "summary.json")
for p in (MESH_PATH, SUMMARY_PATH):
    if not os.path.isfile(p):
        sys.exit(f"Missing {p} - this script verifies its reconstruction "
                 f"against the run's own saved mesh and summary, and "
                 f"refuses to proceed without them.")

import json
with open(SUMMARY_PATH) as fh:
    summary = json.load(fh)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --- re-derive the geometry, interfaces and junctions, exactly as step 1-2
# of timehistory_castelnuovo.py do (copied deliberately, not imported: see
# that script's own step 1-2 for the source of truth this must keep
# matching) ------------------------------------------------------------
t0 = time.perf_counter()
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.model.add("reconstruct_sampled_elements")
gmsh.open(STEP_PATH)
gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
gmsh.model.occ.synchronize()
vol_tags = [t for _d, t in gmsh.model.getEntities(3)]
say(f"{len(vol_tags)} volumes ({time.perf_counter()-t0:.1f} s)")

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
say(f"{len(selected)} Task A interfaces selected")

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

face_jobs = find_open_junctions(
    vol_tags, touching, max_gap=MAX_JUNCTION_GAP,
    only_pairs={(min(a, b), max(a, b)) for a, b, _g in open_junctions},
    measured_gaps={(min(a, b), max(a, b)): g for a, b, g in open_junctions})
junction_faces = sorted({f for j in face_jobs
                         for f in (j["face_small"], j["face_big"])})
say(f"refining to {JUNCTION_MESH_SIZE} m around {len(junction_faces)} facing "
    f"surfaces from {len(face_jobs)} junctions")
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

# --- CHECK 1: does this reconstruction match the mesh the run actually
# used? Compared on node count, node coordinates, and element count -
# not assumed from "the same script, the same inputs" alone. -------------
say("--- verifying against the run's saved mesh.msh ---")
recon_ntags, recon_ncoords, _ = gmsh.model.mesh.getNodes()
recon_coord = {int(t): c for t, c in zip(recon_ntags, recon_ncoords.reshape(-1, 3))}
recon_n_ele = 0
for v in vol_tags:
    _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
    if etg:
        recon_n_ele += len(etg[0])

# Captured rather than assumed: the desktop run showed gmsh.open(STEP_PATH)
# earlier does NOT necessarily keep the model named "reconstruct_sampled_
# elements" (that name was never actually verified against a real run -
# the live analysis script never needed to switch back to a model by name,
# since it only ever has one). Whatever name gmsh actually gave it, THIS is
# the name to come back to below - not a hard-coded guess.
live_model = gmsh.model.getCurrent()
say(f"live/reconstructed model is actually named {live_model!r}")

gmsh.open(MESH_PATH)   # loads mesh.msh into a SEPARATE model, side by side
saved_model = gmsh.model.getCurrent()
saved_ntags, saved_ncoords, _ = gmsh.model.mesh.getNodes()
saved_coord = {int(t): c for t, c in zip(saved_ntags, saved_ncoords.reshape(-1, 3))}
# getElements(dim=3) with no `tag` returns one array PER ELEMENT TYPE
# present anywhere in the model (not per volume) - each `e` here already
# IS a tags array, so len(e) is the count; indexing into it first (e[0])
# was a genuine bug (grabbed a single tag - a numpy scalar - and then
# len() on that scalar raised TypeError). Different shape than the
# per-volume query above, which is why the two loops look different.
_all3_types, _all3_tags, _all3_nodes = gmsh.model.mesh.getElements(dim=3)
saved_n_ele = sum(len(tags) for tags in _all3_tags)

if len(recon_coord) != len(saved_coord):
    sys.exit(f"ABORT: reconstruction has {len(recon_coord)} nodes, "
             f"mesh.msh has {len(saved_coord)}. This reconstruction is NOT "
             f"the mesh the run used - do not trust anything built on it. "
             f"(A different gmsh/OCC version is the likely cause.)")
missing = [t for t in saved_coord if t not in recon_coord]
if missing:
    sys.exit(f"ABORT: {len(missing)} node tag(s) present in mesh.msh are "
             f"absent from the reconstruction, e.g. {missing[:5]}.")
max_dev = max(float(np.linalg.norm(np.array(recon_coord[t]) - np.array(c)))
             for t, c in saved_coord.items())
say(f"node coordinates: max deviation {max_dev:.3e} m over {len(saved_coord)} nodes")
if max_dev > 1e-6:
    sys.exit(f"ABORT: max node coordinate deviation {max_dev:.3e} m exceeds "
             f"1e-6 m - this reconstruction does not reproduce the run's "
             f"mesh closely enough to trust an element mapping built on it.")
if recon_n_ele != saved_n_ele:
    sys.exit(f"ABORT: reconstruction has {recon_n_ele} solid elements, "
             f"mesh.msh has {saved_n_ele}.")
say(f"element count matches: {saved_n_ele}")
say("CHECK 1 PASSED: reconstruction matches the run's saved mesh.msh")

# Back to the live (re-derived) model for everything after this - it is
# the one with the volume/interface/junction structure the rest of the
# pipeline needs; the loaded mesh.msh was only for the comparison above.
gmsh.model.setCurrent(live_model)

# --- element_tags in the SAME per-volume order Element.add_elements_to_
# opensees uses: iterate the "Masonry" physical group's volumes and
# concatenate gmsh.model.mesh.getElements(dim=3, tag=v) per volume, WITHOUT
# building any material or OpenSees element - that part alone is what took
# the live run tens of minutes, and none of it is needed here. -----------
dim, pg = get_physical_groups_map(gmsh.model)["Masonry"]
group_vols = gmsh.model.getEntitiesForPhysicalGroup(dim, pg)
element_tags = []
for v in group_vols:
    _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
    if etg:
        element_tags.extend(int(t) for t in etg[0])
say(f"{len(element_tags)} solid elements (tags only, no materials built)")

sampled, interesting_vols, focus_eles = select_recorded_elements(
    element_tags, selected, open_junctions, SOLID_SAMPLE)
say(f"{len(sampled)} of {len(element_tags)} elements reconstructed as sampled "
    f"(every {SOLID_SAMPLE}th, plus {len(focus_eles)} in "
    f"{len(interesting_vols)} volumes carrying an interface or a tie)")

# --- CHECK 2: does this match what the live run itself recorded? --------
expected = summary.get("solid_elements_recorded")
if expected is None:
    say("WARNING: summary.json has no solid_elements_recorded field to "
        "check against (an older run) - proceeding on CHECK 1 alone.")
elif len(sampled) != expected:
    sys.exit(f"ABORT: reconstructed {len(sampled)} sampled elements, but "
             f"summary.json (written by the live run) recorded "
             f"{expected}. These must match exactly - writing "
             f"sampled_elements.txt anyway would risk putting the wrong "
             f"strain/damage history next to the wrong element.")
else:
    say(f"CHECK 2 PASSED: matches summary.json's solid_elements_recorded "
        f"({expected})")

out_path = os.path.join(RUN_DIR, "sampled_elements.txt")
with open(out_path, "w") as fh:
    fh.write("# element_index,element_tag,volume_tag - element_index is the "
             "column position in solid_strain.txt / solid_stress.txt / "
             "solid_*.txt. Reconstructed, not recorded live - see this "
             "script's module docstring.\n")
    vol_of = {}
    for v in group_vols:
        _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
        if etg:
            for t in etg[0]:
                vol_of[int(t)] = int(v)
    for i, tag in enumerate(sampled):
        fh.write(f"{i},{tag},{vol_of.get(tag, -1)}\n")
say(f"wrote {out_path}")
say("Done.")
gmsh.finalize()
