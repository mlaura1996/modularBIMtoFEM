"""
Interactive, LOCAL wall-to-wall interface inspection and selection (Task A,
PROJECT_BRIEF.md section 5, option (a) - visual inspection).

Run this OUTSIDE Docker, on the local `castelnuovo_viewer` conda
environment (ifcopenshell, pythonocc-core, gmsh, apeGmsh - see
docs/source/user_guide/installation.md):

    conda activate castelnuovo_viewer
    python scripts/inspect_interfaces.py

Companion to scripts/plot_candidate_interfaces.py: run that one first to
get a static, numbered overview image (matplotlib, always works), then
use THIS script to actually confirm a selection - the candidate numbers
match between the two (same detection order, same MIN_VOLUME_M3 filter),
so a number you noted from the plot means the same interface here.

What it does:
1. Loads the Castelnuovo STEP geometry and detects every candidate
   wall-to-wall touching pair (core.mesh_generation.wall_interfaces - the
   exact same code the Docker-based analysis scripts use, so a selection
   made here is directly compatible with them).
2. Tags EVERY candidate as its own numbered physical group
   ("IF_003_vertical_joint_area1.23", ...); vertical_joint ones whose
   both volumes are >= MIN_VOLUME_M3 (a cheap door/window-frame filter -
   walls are far bigger - NOT the real IFC-type classifier, which does a
   real point-in-solid test per IFC element and took several minutes on
   this machine) start VISIBLE, everything else starts hidden (toggle
   back on from the Physical groups panel if you want to check one).
   Then opens gmsh's own GUI (gmsh.fltk.run()).

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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection, InterfaceSelection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
MIN_VOLUME_M3 = 0.3  # matches scripts/plot_candidate_interfaces.py - keeps numbering consistent

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

    # NOT removed from the model - only used to decide default visibility
    # below. Removing volumes before detection would change gmsh's
    # touching-pair results and indices, breaking the number-matching
    # with plot_candidate_interfaces.py (which detects on the FULL,
    # unfiltered geometry too).
    big_vol_tags = {t for _d, t in all_vols if gmsh.model.occ.getMass(3, t) >= MIN_VOLUME_M3}
    print(f"{len(big_vol_tags)}/{len(all_vols)} volumes >= {MIN_VOLUME_M3} m^3.")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidate touching pairs found.")

    for i, c in enumerate(candidates, start=1):
        name = f"IF_{i:03d}_{c['orientation']}_area{c['area_m2']:.2f}"
        gmsh.model.addPhysicalGroup(2, [c["surface"]], tag=-1, name=name)
        visible = (c["orientation"] in DEFAULT_VISIBLE_ORIENTATIONS
                   and c["volume_a"] in big_vol_tags and c["volume_b"] in big_vol_tags)
        gmsh.model.setVisibility([(2, c["surface"])], 1 if visible else 0, recursive=False)

    # All volumes visible, for spatial context while orbiting.
    gmsh.model.addPhysicalGroup(3, [t for _, t in all_vols], tag=-1, name="Masonry")
    gmsh.model.setVisibility(list(all_vols), 1, recursive=False)

    n_default_visible = sum(
        1 for c in candidates if c["orientation"] in DEFAULT_VISIBLE_ORIENTATIONS
        and c["volume_a"] in big_vol_tags and c["volume_b"] in big_vol_tags
    )
    print(
        f"\nOpening the gmsh viewer. {n_default_visible}/{len(candidates)} candidates start "
        "visible (vertical_joint, both volumes >= "
        f"{MIN_VOLUME_M3} m^3 - matches scripts/plot_candidate_interfaces.py's numbering), "
        "as thin highlighted surfaces among the wall volumes.\n"
        "In the 'Physical groups' panel (List tab), UNTICK the checkbox for any "
        "IF_### you do NOT want as a contact interface, and TICK any hidden one "
        "(non-vertical_joint, or a filtered-out small volume) you DO want. What's "
        "left ticked when you close the window becomes the selection."
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
