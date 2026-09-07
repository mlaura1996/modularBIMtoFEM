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
1. Loads the Castelnuovo STEP geometry and detects every candidate
   wall-to-wall touching pair (core.mesh_generation.wall_interfaces,
   the exact same code the Docker-based analysis scripts use - so a
   selection made here is directly compatible with them).
2. Tags EVERY candidate as its own numbered physical group
   ("IF_003_vertical_joint_area1.23", ...), then opens gmsh's own GUI
   (gmsh.fltk.run()) so you can rotate/zoom the real geometry and toggle
   each candidate's visibility by name in the physical-group panel to see
   exactly where it is. The number in each group's name matches the row
   number in the table printed below.
3. After you close that window, prints the same numbered table
   (area, centroid, normal, orientation) and asks which interface numbers
   to confirm as contact elements - core.mesh_generation.wall_interfaces.
   InterfaceSelection.present_cli(), unchanged.
4. Saves your selection to
   resources/survey_data/castelnuovo/interface_selection.json - the
   Docker-based scripts can then load it back with
   InterfaceSelection.select_interactive_or_cached() instead of picking a
   hard-coded slice (which is what they've been doing so far, and part of
   why recent runs kept hitting stability problems - an arbitrary
   selection has no engineering basis).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection, InterfaceSelection

STEP_PATH = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"

with apeGmsh(model_name="inspect_interfaces") as g:
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidate touching pairs found.")

    # Tag every candidate as its own numbered physical group, so its
    # number in the GUI's group list matches its row number in the table
    # printed after you close the window.
    for i, c in enumerate(candidates, start=1):
        name = f"IF_{i:03d}_{c['orientation']}_area{c['area_m2']:.2f}"
        gmsh.model.addPhysicalGroup(2, [c["surface"]], tag=-1, name=name)

    # Also tag the volumes, for spatial context while orbiting.
    gmsh.model.addPhysicalGroup(3, [t for _, t in all_vols], tag=-1, name="Masonry")

    print(
        "\nOpening the gmsh viewer. In the panel on the left, open "
        "'Physical groups' to toggle each IF_### candidate's visibility "
        "and see exactly where it is on the building. Close the window "
        "when you're done looking - you'll then be asked which interface "
        "numbers to confirm, in this same terminal."
    )
    gmsh.fltk.run()

    selected = InterfaceSelection.present_cli(candidates)
    InterfaceSelection.save(candidates, selected, SELECTION_PATH)
    print(f"\nSaved {len(selected)} selected interface(s) to {SELECTION_PATH}")
