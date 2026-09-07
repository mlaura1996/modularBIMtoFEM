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
