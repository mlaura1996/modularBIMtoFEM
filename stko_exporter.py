import os
import ifcopenshell
import gmsh
import openseespy.opensees as ops
from core.config import GEOMETRY_SETTINGS, STEP_WRITER, EXPORT_DIR  # Load global settings
from core.ifc_processing.geometry_extractor import GeometryProcessor, StepExporter
from core.ifc_processing.data_extractor import Material, MaterialsAndThicknesses
from core.mesh_generation.mesh import GmshModel 
from core.config import *



# ✅ Define file paths
IFC_FILE_PATH = "resources/ifc_examples/example_19_5v3.ifc"
STEP_FILE_NAME = "example_19_5_v3"

os.makedirs(EXPORT_DIR, exist_ok=True)  # Ensure export folder exists


print("🚀 Starting IFC to STEP Conversion Pipeline...\n")


# ✅ Load IFC File
print(f"📂 Loading IFC file: {IFC_FILE_PATH}")
ifc_model = ifcopenshell.open(IFC_FILE_PATH)

materials = ifc_model.by_type("IfcMaterial")

print("Materiali trovati:")
for m in materials:
    print(m.Name if hasattr(m, "Name") else m)

material_db = Material.create_material_database(ifc_model)
print(material_db)
#     # ✅ Initialize Geometry Processor
# geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)

# # doors = ifc_model.by_type("IfcDoor")
# # for door in doors:
# #     StepExporter.export_shape(geometry_processor, door)

# # ✅ Extract IFC Elements (Walls, Slabs, etc.)
# elements = [element for element in ifc_model.by_type("IfcBuildingElement")
#     if not element.is_a("IfcBuildingElementProxy")]
# print(f"🔍 Found {len(elements)} building elements in the IFC model.\n")
# elements_dictionary = Material.assign_material_tags(elements, material_db)
# print(elements_dictionary)


# # ✅ Generate STEP File
# step_exporter = StepExporter(STEP_WRITER)
# step_path, labels = step_exporter.generate_step_file(elements, elements_dictionary, os.path.join(EXPORT_DIR, STEP_FILE_NAME))

# # ✅ Print Results
# print("\n🎉 IFC to STEP conversion completed successfully!")

# print(STEP_FILE_NAME)
# # # ✅ GmshModel
# gmsh_labels = list(material_db.keys())
# gmshmodel = GmshModel.createGmshModel("export/example_19_5_v3.step", gmsh_labels, run_gmsh = False, use_adaptive_mesh=False)
# gmsh.fltk.run()