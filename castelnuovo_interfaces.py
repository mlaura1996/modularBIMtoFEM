"""
Chapter 7 (Castelnuovo) - Task A driver: detect wall-to-wall contact
interface candidates, let the user confirm the selection (or reuse a saved
one), and tag the confirmed surfaces as physical groups ready for meshing.

Usage:
    python castelnuovo_interfaces.py

First run: prints the candidate table and asks for confirmation, then saves
the selection to output/castelnuovo/interface_selection.json. Subsequent
runs load that file and skip the prompt (brief requirement: re-running the
pipeline must not require re-selecting).

Delete output/castelnuovo/interface_selection.json to re-select from scratch.

What this script does NOT do yet (see core/mesh_generation/wall_interfaces.py
docstrings and the chat log for why): mesh the full geometry, or generate
the actual OpenSees contact elements. It stops at candidate detection +
selection + physical-group tagging, which is everything that does not
require an OpenSees-capable environment and is fully testable on this
machine. Meshing at Chapter-7 scale (~279k nodes / 954k tets) and the full
zeroLengthContactASDimplex generation belong to a run in the Docker image
(Task C), where OpenSeesMP and MUMPS are actually available.
"""

import os
import gmsh

from core.mesh_generation.wall_interfaces import (
    InterfaceDetection,
    InterfaceSelection,
    ContactInterfaceGenerator,
)

GEOMETRY_STEP = "resources/ifc_examples/castelnuovo/final_example_PRONTO.stp"
SELECTION_PATH = "output/castelnuovo/interface_selection.json"


def main():
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.mesh.setOrder(1)  # Tet4 per PROJECT_BRIEF.md 4.1, not this repo's usual order-2 default

    print(f"Loading Castelnuovo geometry: {GEOMETRY_STEP}")
    gmsh.open(GEOMETRY_STEP)

    print("Fragmenting to establish shared topology between touching solids "
          "(required: the STEP file alone has 0 shared faces between adjacent "
          "solids, verified empirically - see chat log).")
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    volumes = gmsh.model.getEntities(3)
    print(f"{len(volumes)} solids after fragment.")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidate touching-surface pairs found.")

    selected = InterfaceSelection.select_interactive_or_cached(candidates, SELECTION_PATH)

    ContactInterfaceGenerator.tag_physical_groups(selected)
    print(f"{len(selected)} interfaces tagged as physical groups, ready for meshing.")

    os.makedirs("output/castelnuovo", exist_ok=True)
    gmsh.write("output/castelnuovo/castelnuovo_tagged.brep")

    gmsh.finalize()


if __name__ == "__main__":
    main()
