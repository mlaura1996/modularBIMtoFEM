"""
Interactive, LOCAL wall-to-wall interface inspection and selection (Task A,
PROJECT_BRIEF.md section 5, option (a) - visual inspection).

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
   ("IF_003_vertical_joint_area1.23", ...); vertical_joint ones start
   VISIBLE, everything else starts hidden (toggle back on from the
   Physical groups panel if you want to check one). Then opens gmsh's
   own GUI (gmsh.fltk.run()).

SELECTION IS BY VISIBILITY: in the window's "Physical groups" panel
(List tab), tick/untick each IF_### candidate's checkbox - visible when
you close the window = selected as a contact interface, hidden = not
selected. (An earlier version of this script tried "delete the ones you
don't want" instead - doesn't work, gmsh won't delete a face that's
shared between two solids' boundaries without touching the solids
themselves, tested and confirmed broken before shipping this version.)

After closing the window, prints what was captured (KEPT/not selected)
and asks you to confirm or type an explicit override - a safety net in
case the visibility read-back doesn't match what you intended.

Saves the result to
resources/survey_data/castelnuovo/interface_selection.json - the
Docker-based scripts can then load it back with
InterfaceSelection.select_interactive_or_cached() instead of picking a
hard-coded slice (which is what they've been doing so far, and part of
why recent runs kept hitting stability problems - an arbitrary selection
has no engineering basis).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

from core.ifc_processing.ifc_step_matching import classify_step_volumes_by_ifc_type
from core.mesh_generation.wall_interfaces import InterfaceDetection, InterfaceSelection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
IFC_PATH = "resources/ifc_examples/castelnuovo/example_clean.ifc"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
VOLUME_TYPES_PATH = "resources/survey_data/castelnuovo/volume_ifc_types.json"

# Types excluded by default, per the current phase's scope. Set to () to
# keep everything (e.g. to double check what's being excluded).
EXCLUDE_TYPES = ("IfcSlab", "IfcWindow", "IfcDoor")

# Candidates outside this set start hidden (still selectable via the
# physical groups panel checkbox, just out of the way initially) - cuts
# down what you have to wade through before deciding.
DEFAULT_VISIBLE_ORIENTATIONS = ("vertical_joint",)

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

    for i, c in enumerate(candidates, start=1):
        name = f"IF_{i:03d}_{c['orientation']}_area{c['area_m2']:.2f}"
        gmsh.model.addPhysicalGroup(2, [c["surface"]], tag=-1, name=name)
        visible = 1 if c["orientation"] in DEFAULT_VISIBLE_ORIENTATIONS else 0
        gmsh.model.setVisibility([(2, c["surface"])], visible, recursive=False)

    # Wall/stair volumes visible, for spatial context.
    by_type = {}
    for d, t in keep_vols:
        by_type.setdefault(vol_types.get(t), []).append(t)
    for etype, vols in by_type.items():
        gmsh.model.addPhysicalGroup(3, vols, tag=-1, name=f"TYPE_{etype}")
    gmsh.model.setVisibility(keep_vols, 1, recursive=False)

    n_default_visible = sum(1 for c in candidates if c["orientation"] in DEFAULT_VISIBLE_ORIENTATIONS)
    print(
        f"\nOpening the gmsh viewer. {n_default_visible}/{len(candidates)} candidates "
        f"(orientation in {DEFAULT_VISIBLE_ORIENTATIONS}) start visible, as thin "
        "highlighted surfaces among the wall volumes.\n"
        "In the 'Physical groups' panel (List tab), UNTICK the checkbox for any "
        "IF_### you do NOT want as a contact interface, and TICK any hidden one "
        "(non-vertical_joint) you DO want. What's left ticked when you close the "
        "window becomes the selection."
    )
    gmsh.fltk.run()

    auto_selected = [c for c in candidates if gmsh.model.getVisibility(2, c["surface"]) == 1]
    auto_excluded = [c for c in candidates if gmsh.model.getVisibility(2, c["surface"]) == 0]
    print(f"\nCaptured from the viewer: {len(auto_selected)} visible (selected), "
          f"{len(auto_excluded)} hidden (not selected).")
    for c in auto_selected:
        print(f"  SELECTED  vol {c['volume_a']}-{c['volume_b']}  area={c['area_m2']:.4f} m2  {c['orientation']}")

    raw = input(
        "\nPress Enter to accept this selection as-is, or type explicit "
        "indices/ranges (e.g. 1,3,5-9) to override it: "
    ).strip()
    if raw == "":
        selected = auto_selected
    else:
        selected_idx = set()
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-")
                selected_idx.update(range(int(lo), int(hi) + 1))
            elif part:
                selected_idx.add(int(part))
        selected = [c for i, c in enumerate(candidates, start=1) if i in selected_idx]

    InterfaceSelection.save(candidates, selected, SELECTION_PATH)
    print(f"\nSaved {len(selected)} selected interface(s) to {SELECTION_PATH}")
