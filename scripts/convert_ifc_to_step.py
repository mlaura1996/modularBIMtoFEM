"""
Raw IFC -> STEP geometry export, LOCAL (needs ifcopenshell/pythonocc-core,
see docs/source/user_guide/installation.md's castelnuovo_viewer conda
recipe). Reuses core.ifc_processing.geometry_extractor's
GeometryProcessor/StepExporter (the same code main.py's own IFC->STEP
step uses) - not a new export path.

Output is RAW: no duplicate removal, no interpenetration resolution, no
conformal imprint (fragment()). Run scripts/repair_step_geometry.py on
the result before using it anywhere else in the pipeline - see that
script's docstring for why (PROJECT_BRIEF.md 3.3's original Castelnuovo
STEP needed the same kind of repair, done manually outside this
repository at the time; this pair of scripts does it as a repeatable,
inspectable process instead).

Skips Material.create_material_database/assign_material_tags (main.py's
own approach): Castelnuovo's materials have no Pset_MaterialCommon
(known gap, see docs/source/case_study/materials.md), which crashes that
path with KeyError. Not needed for a geometry-only export - the label
dict StepExporter.generate_step_file() wants is only used for STEP
product naming, not geometric validity - so element type + GlobalId is
used instead of a real material name.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ifcopenshell
from core.config import STEP_WRITER
from core.ifc_processing.geometry_extractor import StepExporter

IFC_PATH = "resources/ifc_examples/castelnuovo/example_clean.ifc"
OUT_DIR = "export/castelnuovo_clean"
os.makedirs(OUT_DIR, exist_ok=True)

ifc_model = ifcopenshell.open(IFC_PATH)
elements = [e for e in ifc_model.by_type("IfcBuildingElement")
            if not e.is_a("IfcBuildingElementProxy")]
print(f"{len(elements)} building elements")

elements_dictionary = {e: f"{e.is_a()}_{e.GlobalId[:8]}" for e in elements}

step_exporter = StepExporter(STEP_WRITER)
step_path, labels = step_exporter.generate_step_file(
    elements, elements_dictionary, os.path.join(OUT_DIR, "castelnuovo_clean")
)
print(f"Wrote raw STEP: {step_path}")
print("Run scripts/repair_step_geometry.py next - this output is not repaired yet.")
