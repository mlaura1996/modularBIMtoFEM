"""Closes wall-to-wall junctions that the source geometry left open.

Why this exists
---------------
The cleaned Castelnuovo STEP has ~21 wall-to-wall junctions where the two
solids were drawn 1.5 mm - 5 cm APART instead of in contact. ``fragment()``
correctly refuses to fuse solids that do not touch, so those walls end up
structurally independent: they carry no load to each other and, in a modal
analysis, a wall braced by nothing swings out of plane on its own. That is
visible directly in the mode shapes ("si vede chiaramente in diversi modi
che questo muro non e' connesso a quelli ortogonali").

Every standard gmsh/OCC lever was tried first and none of them fixes it
(measured on this geometry, see docker/opensees/test_*.py):

=========================================  ==========================
recipe                                     junctions recovered
=========================================  ==========================
``Geometry.Tolerance`` (import) up to 5cm  0 / 21
``occ.removeAllDuplicates()`` any tol      0 / 21
``Geometry.ToleranceBoolean`` 2-5 cm       10 / 21 (and shifts volume tags)
``OCCSewFaces`` + ``OCCMakeSolids``        destroys the model (0 volumes)
=========================================  ==========================

What this does instead
----------------------
For each open junction it finds the two boundary faces that face each
other across the gap, takes the SMALLER of the two - at a T-junction that
is the abutting wall's end face, i.e. its cross-section, not the long
side face of the wall it runs into - and extrudes a copy of it across the
gap so it penetrates the neighbour. A subsequent ``fragment()`` then fuses
everything through that bridge.

Extruding the smaller face is the point: extruding the large side face
would hang a thin slab of material out into empty space wherever the
neighbour does not actually abut it. The added mass is the face area times
the gap (millimetres), which is negligible and physically stands for the
mortar/quoin interlock the BIM model omitted.

Only junctions closer than ``max_gap`` are bridged; the ~108 volume pairs
that merely have adjacent bounding boxes but sit >10 cm apart are
different walls across a room and must stay unconnected.
"""

import math

import gmsh


def _bbox_separation(a, b):
    """Euclidean distance between two axis-aligned bounding boxes (0 if
    they overlap). Each box is gmsh's (xmin, ymin, zmin, xmax, ymax, zmax)."""
    d2 = 0.0
    for i in range(3):
        lo_a, hi_a = a[i], a[i + 3]
        lo_b, hi_b = b[i], b[i + 3]
        gap = max(0.0, lo_a - hi_b, lo_b - hi_a)
        d2 += gap * gap
    return math.sqrt(d2)


def _bboxes_within(a, b, tol):
    return _bbox_separation(a, b) <= tol


def _face_normal(surf):
    """Outward-ish unit normal at the middle of a face's REAL parameter
    range - [0.5, 0.5] would be wrong here, OCC faces imported from STEP
    do not have a normalised [0,1]x[0,1] parametrisation."""
    (u0, v0), (u1, v1) = gmsh.model.getParametrizationBounds(2, surf)
    n = gmsh.model.getNormal(surf, [(u0 + u1) / 2, (v0 + v1) / 2])
    mag = math.sqrt(sum(c * c for c in n))
    if mag == 0:
        return None
    return [c / mag for c in n]


def find_open_junctions(volume_tags, touching_pairs, max_gap=0.05,
                        min_bridge_area=1e-4, only_pairs=None,
                        measured_gaps=None):
    """Locate volume pairs that should be connected but are not.

    volume_tags:    all 3-D entity tags (after fragment + synchronize)
    touching_pairs: set of (min, max) volume-tag pairs fragment() already
                    fused - i.e. what InterfaceDetection.
                    find_touching_surface_pairs() reports
    max_gap:        only bridge junctions closer than this (m)
    only_pairs:     optional set of (min, max) volume-tag pairs to restrict
                    to. STRONGLY recommended: screening on bounding boxes
                    alone caught 208 "junctions" on this geometry (large
                    faces whose boxes come close without the solids being
                    anywhere near each other), which bridged far too much
                    and left the model unmeshable. Pass the pairs whose
                    real solid-to-solid distance was measured instead.

    Returns a list of dicts describing each bridge to build.
    """
    vol_bbox = {v: gmsh.model.occ.getBoundingBox(3, v) for v in volume_tags}
    vol_faces = {}
    for v in volume_tags:
        faces = [abs(t) for _d, t in gmsh.model.getBoundary([(3, v)], oriented=False,
                                                             combined=False)]
        vol_faces[v] = faces

    face_bbox, face_area, face_com = {}, {}, {}
    for faces in vol_faces.values():
        for f in faces:
            if f in face_bbox:
                continue
            face_bbox[f] = gmsh.model.occ.getBoundingBox(2, f)
            face_area[f] = gmsh.model.occ.getMass(2, f)
            face_com[f] = gmsh.model.occ.getCenterOfMass(2, f)

    jobs = []
    tags = list(volume_tags)
    for i, va in enumerate(tags):
        for vb in tags[i + 1:]:
            key = (min(va, vb), max(va, vb))
            if only_pairs is not None and key not in only_pairs:
                continue
            if key in touching_pairs:
                continue  # already fused - nothing to do
            if not _bboxes_within(vol_bbox[va], vol_bbox[vb], max_gap):
                continue

            best = None
            for fa in vol_faces[va]:
                for fb in vol_faces[vb]:
                    sep = _bbox_separation(face_bbox[fa], face_bbox[fb])
                    if sep > max_gap:
                        continue
                    if best is None or sep < best[0]:
                        best = (sep, fa, fb)
            if best is None:
                continue

            sep, fa, fb = best
            # Extrude the SMALLER face - at a T-junction that is the
            # abutting wall's cross-section, which keeps the bridge local.
            if face_area[fa] <= face_area[fb]:
                f_small, f_big = fa, fb
            else:
                f_small, f_big = fb, fa
            if face_area[f_small] < min_bridge_area:
                continue  # sliver face, not a real junction

            normal = _face_normal(f_small)
            if normal is None:
                continue
            # Point the extrusion at the other face.
            com_s, com_b = face_com[f_small], face_com[f_big]
            toward = [com_b[k] - com_s[k] for k in range(3)]
            if sum(normal[k] * toward[k] for k in range(3)) < 0:
                normal = [-c for c in normal]

            # `sep` is the separation between the two faces' BOUNDING
            # BOXES, which is 0 whenever the boxes touch - true for most of
            # these junctions even where the solids are centimetres apart,
            # so sizing the bridge from it would extrude 5 mm across a
            # 47 mm gap and never reach the neighbour. Prefer the measured
            # solid-to-solid distance when the caller has one.
            key_pair = (min(va, vb), max(va, vb))
            gap = sep
            if measured_gaps is not None and key_pair in measured_gaps:
                gap = max(sep, measured_gaps[key_pair])

            jobs.append({
                "volume_a": va, "volume_b": vb,
                "face_small": f_small, "face_big": f_big,
                "gap": gap, "bbox_gap": sep,
                "area": face_area[f_small], "normal": normal,
            })
    return jobs


def build_bridges(jobs, penetration=0.005, setback=0.005):
    """Extrude a copy of each job's small face across its gap.

    The prism is deliberately sunk into BOTH solids: it starts `setback`
    behind the face it was copied from (i.e. inside wall A) and ends
    `penetration` past the gap (inside wall B). Both matter:

    - Ending inside B is obvious: a bridge that merely reaches B's surface
      leaves the boolean with the same tangential contact that failed to
      fuse in the first place.
    - STARTING inside A is the less obvious half, and skipping it is what
      broke the first working attempt: with the prism's base exactly
      coplanar with A's face, fusing it to A is again a tangential
      face-on-face contact, and the boolean produced slivers instead of a
      clean union - open junctions went from 21 to 145 and weakly-coupled
      pairs from 92 to 141, i.e. the "healing" made the model worse.

    Both offsets are small absolute lengths, not multiples of the gap: an
    even earlier attempt used gap x 3, which on the 49 mm junctions
    extruded 147 mm of material and left the model unmeshable. Walls here
    are ~0.5 m thick, so 5 mm each way stays well inside them.

    Returns the list of created volume tags.
    """
    created = []
    for job in jobs:
        nx, ny, nz = job["normal"]
        length = job["gap"] + penetration + setback
        copy = gmsh.model.occ.copy([(2, job["face_small"])])
        # Sink the starting face back into wall A before extruding.
        gmsh.model.occ.translate(copy, -nx * setback, -ny * setback, -nz * setback)
        out = gmsh.model.occ.extrude(copy, nx * length, ny * length, nz * length)
        vols = [t for d, t in out if d == 3]
        created.extend(vols)
        job["bridge_volumes"] = vols
        job["bridge_length"] = length
    gmsh.model.occ.synchronize()
    return created


def heal_open_junctions(max_gap=0.05, verbose=True, only_pairs=None,
                        measured_gaps=None):
    """Find and bridge every open junction in the current model.

    Call AFTER the first fragment()+synchronize (so volume tags and
    fragment()'s own view of what already touches are available), and
    fragment() again afterwards to fuse the bridges in. Returns the job
    list, each entry annotated with the bridge volumes it produced.

    Pass `only_pairs` (see find_open_junctions) unless you have a reason
    not to.
    """
    from core.mesh_generation.wall_interfaces import InterfaceDetection

    volume_tags = [t for _d, t in gmsh.model.getEntities(3)]
    candidates = InterfaceDetection.find_touching_surface_pairs()
    touching = {(min(c["volume_a"], c["volume_b"]),
                 max(c["volume_a"], c["volume_b"])) for c in candidates}

    jobs = find_open_junctions(volume_tags, touching, max_gap=max_gap,
                               only_pairs=only_pairs,
                               measured_gaps=measured_gaps)
    if verbose:
        print(f"{len(jobs)} open junction(s) found within {max_gap} m")
        for j in sorted(jobs, key=lambda j: j["gap"]):
            print(f"  vol {j['volume_a']:4d} <-> {j['volume_b']:4d}: "
                  f"gap {j['gap']*1000:7.2f} mm (bbox {j['bbox_gap']*1000:6.2f} mm), "
                  f"bridging face {j['face_small']} ({j['area']:.3f} m^2)")

    created = build_bridges(jobs)
    if verbose:
        added = sum(gmsh.model.occ.getMass(3, v) for v in created) if created else 0.0
        print(f"{len(created)} bridge volume(s) created, {added:.6f} m^3 added")
    return jobs
