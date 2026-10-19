"""
Recovers, per STEP volume, the original IFC element type (IfcWall,
IfcSlab, IfcStair, IfcWindow, IfcDoor) - lost when the prepared STEP
geometry (resources/ifc_examples/castelnuovo/final_example_PRONTO.stp)
was generated, since the export/repair/imprint pipeline it went through
(sewing open shells, removing duplicates, cutting interpenetrations,
general fuse) produces generic OCC solids with no IFC-derived label
(verified: confirmed no material/type tag survives, see
core.mesh_generation.wall_interfaces' own module docstring).

Needed because "in this phase I don't want to model slabs" (or windows/
doors - brief section 8, open question 5) requires knowing which STEP
volumes ARE slabs/windows/doors in the first place.

Method: for each IFC building element, build its OCC solid
(ifcopenshell.geom.create_shape) and bounding box. For each STEP volume,
test whether its centroid is genuinely INSIDE that solid
(BRepClass3d_SolidClassifier - true point-in-solid, not just bounding-box
overlap, which was tried first and left 81% of volumes ambiguous because
adjacent building elements' bounding boxes overlap heavily in a real
building). The bounding box is kept only as a cheap pre-filter before the
more expensive solid classification.

Not perfect: on Castelnuovo, 270/316 volumes (85%) get a single,
unambiguous type; 4 fall inside more than one element's solid (touching/
overlapping geometry) and 42 fall inside none (their centroid doesn't
land inside any single original element's solid, plausibly because the
STEP geometry went through shape repair - sewing, interpenetration
cuts - that can shift a piece's boundary slightly relative to the
original IFC element it came from). Both are reported, not silently
dropped, so a caller can decide how to treat them.
"""
import ifcopenshell
import ifcopenshell.geom
import gmsh
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib_Add
from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
from OCC.Core.gp import gp_Pnt
from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON

BBOX_TOL = 0.05      # m - coarse pre-filter tolerance
CLASSIFY_TOL = 1e-4  # m - BRepClass3d_SolidClassifier tolerance
LARGE_VOLUME = 1.0   # m^3 - above this, an unclear volume is matched to walls only


def classify_step_volumes_by_ifc_type(ifc_path, volume_tags):
    """Returns {volume_tag: ifc_type_or_status}.

    ifc_type_or_status is one of "IfcWall", "IfcSlab", "IfcStair",
    "IfcWindow", "IfcDoor" (unique match), "ambiguous" (inside more than
    one element's solid), or "unmatched" (inside none).

    Must be called with the STEP geometry already loaded into the active
    gmsh model (gmsh.model.occ.fragment() + synchronize() already done) -
    this function only reads volume centroids via gmsh.model.occ, it does
    not load geometry itself.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_PYTHON_OPENCASCADE, True)

    ifc_file = ifcopenshell.open(ifc_path)
    elements = [e for e in ifc_file.by_type("IfcBuildingElement")
                if not e.is_a("IfcBuildingElementProxy")]

    element_data = []
    for e in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, e).geometry
        except Exception:
            continue
        box = Bnd_Box()
        brepbndlib_Add(shape, box)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        element_data.append((e.is_a(), shape, xmin, ymin, zmin, xmax, ymax, zmax))

    result = {}
    for vol in volume_tags:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(3, vol)
        pnt = gp_Pnt(cx, cy, cz)
        hits = []
        for etype, shape, xmin, ymin, zmin, xmax, ymax, zmax in element_data:
            if not (xmin - BBOX_TOL <= cx <= xmax + BBOX_TOL and
                    ymin - BBOX_TOL <= cy <= ymax + BBOX_TOL and
                    zmin - BBOX_TOL <= cz <= zmax + BBOX_TOL):
                continue
            classifier = BRepClass3d_SolidClassifier(shape, pnt, CLASSIFY_TOL)
            if classifier.State() in (TopAbs_IN, TopAbs_ON):
                hits.append(etype)
        if len(hits) == 0:
            result[vol] = "unmatched"
        elif len(hits) == 1:
            result[vol] = hits[0]
        else:
            result[vol] = "ambiguous"
    return result


def _element_material(element):
    """Name of the material of an IFC element: on the instance, else on its
    type; for a layer set or a list, the first masonry layer if there is
    one, else the first layer (for a constituent set, the constituent with
    the largest fraction)."""
    def names(rel_owner):
        out = []
        for rel in getattr(rel_owner, "HasAssociations", []) or []:
            if not rel.is_a("IfcRelAssociatesMaterial"):
                continue
            m = rel.RelatingMaterial
            if m.is_a("IfcMaterial"):
                out.append(m.Name)
            elif m.is_a("IfcMaterialLayerSetUsage"):
                out += [l.Material.Name for l in m.ForLayerSet.MaterialLayers if l.Material]
            elif m.is_a("IfcMaterialLayerSet"):
                out += [l.Material.Name for l in m.MaterialLayers if l.Material]
            elif m.is_a("IfcMaterialList"):
                out += [x.Name for x in m.Materials]
            elif m.is_a("IfcMaterialConstituentSet"):     # the largest fraction first
                cons = sorted((c for c in m.MaterialConstituents or [] if c.Material),
                              key=lambda c: -(c.Fraction or 0))
                out += [c.Material.Name for c in cons]
        return out
    found = names(element)
    if not found:
        for rel in getattr(element, "IsTypedBy", []) or []:
            found = names(rel.RelatingType)
            if found:
                break
    masonry = [n for n in found if "masonry" in (n or "").lower()]
    return (masonry or found or [None])[0]


def _vote_inside(vol, data, n=6):
    """Most frequent element among those containing points sampled inside
    the volume (an n x n x n grid over its bounding box, kept where gmsh
    finds the point inside the volume). Returns ((element, material), votes)
    or None when fewer than 30% of the sampled points lie inside one
    element."""
    import collections
    import numpy as np
    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(3, vol)
    counts = collections.Counter()
    inside = 0
    for x in np.linspace(xmin, xmax, n + 2)[1:-1]:
        for y in np.linspace(ymin, ymax, n + 2)[1:-1]:
            for z in np.linspace(zmin, zmax, n + 2)[1:-1]:
                if not gmsh.model.isInside(3, vol, [x, y, z]):
                    continue
                inside += 1
                p = gp_Pnt(x, y, z)
                for k, (e, mat, shape, (a, b, c, d, f, g)) in enumerate(data):
                    if not (a - BBOX_TOL <= x <= d + BBOX_TOL and b - BBOX_TOL <= y <= f + BBOX_TOL and
                            c - BBOX_TOL <= z <= g + BBOX_TOL):
                        continue
                    if BRepClass3d_SolidClassifier(shape, p, CLASSIFY_TOL).State() in (TopAbs_IN, TopAbs_ON):
                        counts[k] += 1
    if not counts:
        return None
    k, votes = counts.most_common(1)[0]
    if votes < 0.3 * inside:            # a few points in a neighbouring element: not evidence enough
        return None
    return (data[k][0], data[k][1]), votes


def assign_step_volumes_to_ifc_elements(ifc_path, volume_tags):
    """Returns {volume_tag: {"guid", "ifc_class", "material", "how"}}.

    Same test as classify_step_volumes_by_ifc_type (centroid inside the
    element's solid), with the two failure cases resolved instead of
    reported: a centroid inside several solids takes the masonry wall among
    them, or else the first; a centroid inside none takes the nearest
    element. When the centroid is inside none or several solids, points
    sampled inside the volume vote first ("votes"), and the two fallbacks
    apply only if no sampled point lies inside an element. "how" records
    which case applied ("inside", "votes", "several", "nearest"), so that the
    assignment can be checked.

    The STEP geometry must already be loaded and fragmented in the active
    gmsh model.
    """
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_PYTHON_OPENCASCADE, True)
    ifc_file = ifcopenshell.open(ifc_path)
    elements = [e for e in ifc_file.by_type("IfcBuildingElement")
                if not e.is_a("IfcBuildingElementProxy")]
    data = []
    for e in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, e).geometry
        except Exception:
            continue
        box = Bnd_Box()
        brepbndlib_Add(shape, box)
        data.append((e, _element_material(e), shape, box.Get()))

    def entry(e, mat, how):
        return {"guid": e.GlobalId, "ifc_class": e.is_a(), "material": mat, "how": how}

    result = {}
    for vol in volume_tags:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(3, vol)
        pnt = gp_Pnt(cx, cy, cz)
        hits = []
        for e, mat, shape, (xmin, ymin, zmin, xmax, ymax, zmax) in data:
            if not (xmin - BBOX_TOL <= cx <= xmax + BBOX_TOL and
                    ymin - BBOX_TOL <= cy <= ymax + BBOX_TOL and
                    zmin - BBOX_TOL <= cz <= zmax + BBOX_TOL):
                continue
            if BRepClass3d_SolidClassifier(shape, pnt, CLASSIFY_TOL).State() in (TopAbs_IN, TopAbs_ON):
                hits.append((e, mat))
        if len(hits) == 1:
            result[vol] = entry(*hits[0], "inside")
            continue
        # a large piece without a clear match is a wall: frames, doors and
        # stairs are small, and their solids, which overlap the walls they sit
        # in, would otherwise attract it
        pool = data if gmsh.model.occ.getMass(3, vol) <= LARGE_VOLUME else [d for d in data if d[0].is_a("IfcWall")]
        votes = _vote_inside(vol, pool)
        if votes:
            (e, mat), n = votes
            result[vol] = entry(e, mat, "votes")
            result[vol]["votes"] = n
        elif hits:
            walls = [h for h in hits if h[0].is_a("IfcWall") and "masonry" in (h[1] or "").lower()]
            result[vol] = entry(*(walls or hits)[0], "several")
        else:
            vertex = BRepBuilderAPI_MakeVertex(pnt).Vertex()
            best = None
            for e, mat, shape, (xmin, ymin, zmin, xmax, ymax, zmax) in pool:
                gap = max(xmin - cx, cx - xmax, ymin - cy, cy - ymax, zmin - cz, cz - zmax, 0.0)
                if best is not None and gap > best[0]:
                    continue
                d = BRepExtrema_DistShapeShape(vertex, shape).Value()
                if best is None or d < best[0]:
                    best = (d, e, mat)
            result[vol] = entry(best[1], best[2], "nearest")
            result[vol]["distance"] = round(best[0], 3)
    return result
