"""
Same job as inspect_interfaces.py (Task A candidate interface selection),
using apeGmsh's own interactive viewer instead of gmsh's native FLTK GUI -
real click-to-pick on the 3D surfaces (PyVista/VTK-backed), not a filtered
list panel. Try this one if the list-based selection in
inspect_interfaces.py feels awkward.

Run OUTSIDE Docker, on the local `castelnuovo_viewer` conda environment
(see docs/source/user_guide/installation.md):

    conda activate castelnuovo_viewer
    python scripts/inspect_interfaces_apegmsh.py

Interaction: the window opens in "brep" pick mode (the default - press
'b' if it ever switches to element/node mode by mistake). CLICK a
candidate interface surface to select it (turns highlighted); CTRL+CLICK
a selected one to deselect it. Rotate/zoom/pan as usual. Close the window
when you're done - the script reads back exactly what's selected via
apeGmsh's own MeshViewer.tags (a list of (dim, tag) BRep entities,
populated by MeshViewer.show(), which returns self - see
apeGmsh.viewers.mesh_viewer.MeshViewer).

Same upstream steps as inspect_interfaces.py: IFC-type classification to
exclude slabs/windows/doors by default, then Task A candidate detection
(core.mesh_generation.wall_interfaces). This version needs an actual mesh
(not just BRep geometry) to build the FEMData the viewer wants, so it
takes a bit longer to open than the gmsh-native script.
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

import gmsh
from apeGmsh import apeGmsh

from core.ifc_processing.ifc_step_matching import classify_step_volumes_by_ifc_type
from core.mesh_generation.wall_interfaces import InterfaceDetection, InterfaceSelection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
IFC_PATH = "resources/ifc_examples/castelnuovo/example_clean.ifc"
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
VOLUME_TYPES_PATH = "resources/survey_data/castelnuovo/volume_ifc_types.json"
EXCLUDE_TYPES = ("IfcSlab", "IfcWindow", "IfcDoor")
GLOBAL_MESH_SIZE = 0.6  # coarse - this is for picking geometry, not analysis

with apeGmsh(model_name="inspect_interfaces_apegmsh") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    vol_types = classify_step_volumes_by_ifc_type(IFC_PATH, [t for _, t in all_vols])
    with open(VOLUME_TYPES_PATH, "w") as f:
        json.dump({str(k): v for k, v in vol_types.items()}, f, indent=2)

    keep_vols = [(d, t) for d, t in all_vols if vol_types.get(t) not in EXCLUDE_TYPES]
    excluded_vols = [(d, t) for d, t in all_vols if vol_types.get(t) in EXCLUDE_TYPES]
    print(f"Excluding {len(excluded_vols)} volumes of type {EXCLUDE_TYPES}, keeping {len(keep_vols)}.")
    if excluded_vols:
        gmsh.model.occ.remove(excluded_vols, recursive=True)
        gmsh.model.occ.synchronize()

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidate touching pairs found among the kept volumes.")

    for i, c in enumerate(candidates, start=1):
        name = f"IF_{i:03d}_{c['orientation']}_area{c['area_m2']:.2f}"
        gmsh.model.addPhysicalGroup(2, [c["surface"]], tag=-1, name=name)

    g.parts.from_model("inspect_interfaces_apegmsh")
    g.physical.add_volume([t for _, t in keep_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)

    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"Meshed: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    print(
        "\nOpening apeGmsh's viewer (brep pick mode). CLICK a candidate "
        "interface surface to select it, CTRL+CLICK to deselect. Close "
        "the window when done."
    )
    mv = g.mesh.viewer(fem=fem, dims=[2, 3])
    picked = mv.tags  # list of (dim, tag)
    picked_surfaces = {tag for dim, tag in picked if dim == 2}

    selected = [c for c in candidates if c["surface"] in picked_surfaces]
    print(f"\n{len(selected)} interface(s) picked in the viewer:")
    for c in selected:
        print(f"  vol {c['volume_a']}-{c['volume_b']}  area={c['area_m2']:.4f} m2  {c['orientation']}")

    raw = input(
        "\nPress Enter to accept this selection as-is, or type explicit "
        "indices/ranges (e.g. 1,3,5-9) to override it: "
    ).strip()
    if raw != "":
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
