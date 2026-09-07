"""
Interactive, LOCAL wall-to-wall interface inspection and selection (Task A,
PROJECT_BRIEF.md section 5, option (a) - visual inspection, now paired with
the already-built option (b), the CLI table).

Run this OUTSIDE Docker, on the local `castelnuovo_viewer` conda
environment (has ifcopenshell, pythonocc-core, gmsh, apeGmsh, and the
apeGmsh "viewer" extras - PySide6/pyvista/vtk - which the Docker image
deliberately does NOT install, since the run image is headless):

    conda activate castelnuovo_viewer
    python scripts/inspect_interfaces.py

What it does:
1. Loads the Castelnuovo STEP geometry, then classifies each volume by
   its original IFC element type (IfcWall/IfcSlab/IfcStair/IfcWindow/
   IfcDoor - core.ifc_processing.ifc_step_matching, since the STEP
   geometry itself carries no such label) and, by default, EXCLUDES
   slabs, windows and doors from what follows (brief section 8, open
   questions 2 and 5 - "in this phase I don't want to model slabs").
   Volumes the matcher couldn't classify confidently ("ambiguous" -
   inside more than one IFC element's solid, or "unmatched" - inside
   none) are kept, not silently dropped, and flagged in the printed
   summary so you know to double-check them visually.
2. Detects every candidate wall-to-wall touching pair among what's left
   (core.mesh_generation.wall_interfaces - the exact same code the
   Docker-based analysis scripts use, so a selection made here is
   directly compatible with them).
3. Tags EVERY candidate as its own numbered physical group
   ("IF_003_vertical_joint_area1.23", ...), plus one physical group per
   IFC type still present, then opens gmsh's own GUI (gmsh.fltk.run())
   so you can rotate/zoom the real geometry and toggle each candidate's
   visibility by name in the physical-group panel to see exactly where
   it is. The number in each group's name matches the row number in the
   table printed below.
4. After you close that window, prints the same numbered table
   (area, centroid, normal, orientation) and asks which interface numbers
   to confirm as contact elements - core.mesh_generation.wall_interfaces.
   InterfaceSelection.present_cli(), unchanged.
5. Saves your selection to
   resources/survey_data/castelnuovo/interface_selection.json - the
   Docker-based scripts can then load it back with
   InterfaceSelection.select_interactive_or_cached() instead of picking a
   hard-coded slice (which is what they've been doing so far, and part of
   why recent runs kept hitting stability problems - an arbitrary
   selection has no engineering basis).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

from core.ifc_processing.ifc_step_matching import classify_step_volumes_by_ifc_type
from core.mesh_generation.wall_interfaces import InterfaceDetection, InterfaceSelection

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
IFC_PATH = "resources/ifc_examples/castelnuovo/final_example.ifc"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
VOLUME_TYPES_PATH = "resources/survey_data/castelnuovo/volume_ifc_types.json"

# Types excluded by default, per the current phase's scope. Set to () to
# keep everything (e.g. to double check what's being excluded).
EXCLUDE_TYPES = ("IfcSlab", "IfcWindow", "IfcDoor")

with apeGmsh(model_name="inspect_interfaces") as g:
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    print("Classifying volumes against the original IFC element types "
          "(this re-derives the geometry per element, can take a minute)...")
    vol_types = classify_step_volumes_by_ifc_type(IFC_PATH, [t for _, t in all_vols])
    with open(VOLUME_TYPES_PATH, "w") as f:
        json.dump({str(k): v for k, v in vol_types.items()}, f, indent=2)
    counts = {}
    for t in vol_types.values():
        counts[t] = counts.get(t, 0) + 1
    print(f"Classification ({VOLUME_TYPES_PATH}): {counts}")

    keep_vols = [(d, t) for d, t in all_vols if vol_types.get(t) not in EXCLUDE_TYPES]
    excluded_vols = [(d, t) for d, t in all_vols if vol_types.get(t) in EXCLUDE_TYPES]
    print(f"Excluding {len(excluded_vols)} volumes of type {EXCLUDE_TYPES}, "
          f"keeping {len(keep_vols)} (walls/stairs/ambiguous/unmatched).")
    if excluded_vols:
        gmsh.model.occ.remove(excluded_vols, recursive=True)
        gmsh.model.occ.synchronize()

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidate touching pairs found among the kept volumes.")

    # Tag every candidate as its own numbered physical group, so its
    # number in the GUI's group list matches its row number in the table
    # printed after you close the window.
    for i, c in enumerate(candidates, start=1):
        name = f"IF_{i:03d}_{c['orientation']}_area{c['area_m2']:.2f}"
        gmsh.model.addPhysicalGroup(2, [c["surface"]], tag=-1, name=name)

    # One physical group per remaining IFC type, for spatial context and
    # to sanity-check the "ambiguous"/"unmatched" volumes visually.
    by_type = {}
    for d, t in keep_vols:
        by_type.setdefault(vol_types.get(t), []).append(t)
    for etype, vols in by_type.items():
        gmsh.model.addPhysicalGroup(3, vols, tag=-1, name=f"TYPE_{etype}")

    print(
        "\nOpening the gmsh viewer. In the panel on the left, open "
        "'Physical groups' to toggle each IF_### candidate's visibility, "
        "or the TYPE_* groups (e.g. TYPE_ambiguous, TYPE_unmatched) to "
        "check the volumes the IFC-type classifier wasn't sure about. "
        "Close the window when you're done looking - you'll then be "
        "asked which interface numbers to confirm, in this same terminal."
    )
    gmsh.fltk.run()

    selected = InterfaceSelection.present_cli(candidates)
    InterfaceSelection.save(candidates, selected, SELECTION_PATH)
    print(f"\nSaved {len(selected)} selected interface(s) to {SELECTION_PATH}")
